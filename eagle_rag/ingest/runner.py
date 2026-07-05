"""Unified ingest entry point (runner).

Synchronous function called directly by FastAPI routes; actual dispatch is
asynchronous via Celery. Supports four sources:

1. Local file path (``file_path``)
2. In-memory byte stream (``file_bytes`` + ``filename``)
3. MinIO object key (``object_key`` + ``filename``)
4. Web URL (``source_uri`` starting with http)

Flow: generate job/document ID → deduplicate (file sources) → upload to MinIO
(local/bytes sources) → create audit → register document → ``app.send_task``
dispatches the router task to ``router_queue``.

Supports per-``kb_name`` (knowledge base) isolation: all dedup, audit, document
registration and routing dispatch pass ``kb_name`` through, falling back to
``get_settings().kb_name`` when it is None.

No services (PostgreSQL/MinIO/Redis) are contacted at import time; all external
calls happen inside function bodies. PostgreSQL outages degrade gracefully
(logged, dispatch not blocked); MinIO upload failures are fatal, because the
file must live in shared storage for distributed workers to fetch it.
"""

from __future__ import annotations

import mimetypes
import tempfile
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from eagle_rag.config import get_settings
from eagle_rag.index import registry
from eagle_rag.ingest.router import infer_source_type
from eagle_rag.storage import dedup, minio_client
from eagle_rag.tasks import state as task_state
from eagle_rag.telemetry import get_ai_logger, get_logger, send_task_with_trace, truncate

logger = get_logger(__name__)
ai_logger = get_ai_logger(__name__)

__all__ = [
    "ingest",
    "ingest_file",
    "ingest_bytes",
    "ingest_url",
    "get_job_status",
]

_ROUTER_TASK = "eagle_rag.ingest.router.ingest_router"
_ROUTER_QUEUE = "router_queue"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _prepare_local_source(
    *,
    file_path: str | Path | None,
    file_bytes: bytes | None,
    filename: str | None,
    object_key: str | None,
) -> tuple[Path, str]:
    """Unify file_path/file_bytes/object_key into a local temp file path.

    Returns ``(local_path, filename)``:
    - ``file_path``: used directly; filename is the path basename or the explicit arg.
    - ``file_bytes``: written to a temp file; ``filename`` must be provided.
    - ``object_key``: downloaded from MinIO into a temp file under
      ``settings.storage.data_dir``.

    URL sources do not go through this helper (the caller must skip it).
    """
    if file_path is not None:
        p = Path(file_path)
        name = filename or p.name
        return p, name

    if file_bytes is not None:
        if not filename:
            raise ValueError("filename is required for file_bytes source")
        suffix = Path(filename).suffix or ""
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        try:
            tmp.write(file_bytes)
        finally:
            tmp.close()
        return Path(tmp.name), filename

    if object_key is not None:
        name = filename or Path(object_key).name or "object"
        suffix = Path(name).suffix or ".bin"
        data_dir = Path(get_settings().storage.data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = data_dir / f"runner_{uuid4().hex}{suffix}"
        minio_client.download_file(object_key, tmp_path)
        return tmp_path, name

    raise ValueError("one of file_path, file_bytes, object_key, or source_uri is required")


def _guess_content_type(filename: str) -> str:
    """Guess content_type from the filename; returns ``application/octet-stream`` if unknown."""
    guessed = mimetypes.guess_type(filename)[0]
    return guessed or "application/octet-stream"


# ---------------------------------------------------------------------------
# Unified entry point
# ---------------------------------------------------------------------------


def ingest(
    *,
    file_path: str | Path | None = None,
    file_bytes: bytes | None = None,
    filename: str | None = None,
    object_key: str | None = None,
    source_uri: str | None = None,
    source_type_hint: str | None = None,
    kb_name: str | None = None,
) -> dict[str, Any]:
    """Unified ingest entry point.

    Supports the four sources described in the module docstring. Returns
    ``{"job_id", "status", "dedup_hit", "document_id"}``. On a dedup hit it
    returns ``status="success"`` immediately without dispatching; otherwise it
    dispatches the router task and returns ``status="pending"``.

    ``kb_name`` falls back to ``get_settings().kb_name`` when None and is passed
    through to dedup, audit, document registration and the router task for
    knowledge-base isolation.

    MinIO/PostgreSQL outages degrade gracefully (logged, dispatch not blocked).
    """
    kb = kb_name if kb_name is not None else get_settings().kb_name
    from eagle_rag.kb.registry import kb_exists_sync

    if not kb_exists_sync(kb):
        raise ValueError(f"knowledge base not registered: {kb}")
    t0 = time.monotonic()
    job_id = str(uuid4())
    document_id = str(uuid4())

    is_url = bool(source_uri and source_uri.startswith(("http://", "https://")))

    if is_url:
        # URL source: skip dedup and upload.
        local_path: Path | None = None
        sha256: str | None = None
        name = filename or source_uri or "untitled"
        source_type = infer_source_type(
            name, source_uri=source_uri, source_type_hint=source_type_hint
        )
    else:
        # File source: prepare local file + dedup.
        local_path, name = _prepare_local_source(
            file_path=file_path,
            file_bytes=file_bytes,
            filename=filename,
            object_key=object_key,
        )
        source_type = infer_source_type(
            name, source_uri=source_uri, source_type_hint=source_type_hint
        )
        sha256 = dedup.compute_sha256(local_path)
        dup = dedup.check_duplicate(sha256, kb_name=kb)
        if dup is not None:
            try:
                task_state.create_audit(
                    job_id,
                    dup["document_id"],
                    "router",
                    kb_name=kb,
                    name=name,
                    source_uri=source_uri,
                )
                task_state.update_state(
                    job_id,
                    task_state.TaskState.SUCCESS,
                    progress=100,
                    log_entry=f"Dedup hit, existing document {dup['document_id']}",
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("audit write after dedup hit failed (non-fatal)：%s", exc)
            try:
                ai_logger.info(
                    "ingest",
                    job_id=job_id,
                    document_id=dup["document_id"],
                    pipeline="router",
                    kb_name=kb,
                    source_type=source_type,
                    name=truncate(name, 128),
                    status="success",
                    dedup_hit=True,
                    duration_ms=int((time.monotonic() - t0) * 1000),
                )
            except Exception:  # noqa: BLE001
                logger.debug("telemetry emit failed", exc_info=True)
            return {
                "job_id": job_id,
                "status": "success",
                "dedup_hit": True,
                "document_id": dup["document_id"],
            }

        # Upload to MinIO (local/bytes source without an explicit object_key).
        # MinIO is the shared storage for distributed workers; a local temp file
        # in the API container is unreachable from worker containers, so upload
        # failure is fatal rather than degrading to local_path.
        if object_key is None:
            obj_key = f"{source_type}/{document_id}/{name}"
            content_type = _guess_content_type(name)
            if file_bytes is not None:
                minio_client.upload_bytes(
                    obj_key,
                    file_bytes,
                    content_type=content_type,
                    length=len(file_bytes),
                )
            else:
                minio_client.upload_file(obj_key, local_path, content_type=content_type)
            object_key = obj_key

    # Note: dedup.register is deferred to knowhere_parse success, so failed
    # tasks don't leave behind dedup records that would block re-uploads.

    # Create audit record.
    try:
        task_state.create_audit(
            job_id, document_id, "router", kb_name=kb, name=name, source_uri=source_uri
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("audit creation failed (non-fatal)：%s", exc)

    # Register document (PostgreSQL outage does not block dispatch).
    try:
        registry.register_document(
            document_id,
            name=name,
            source_type=source_type,
            pipeline="pending",
            source_uri=source_uri or object_key,
            sha256=sha256,
            status="pending",
            kb_name=kb,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("document registration failed (non-fatal; dispatch continues)：%s", exc)

    # Dispatch the router task (inject trace headers to continue the FastAPI↔Celery trace).
    # local_path is intentionally not dispatched: it points to a temp file inside the
    # API container's filesystem, unreachable from worker containers. Workers fetch the
    # file from MinIO via object_key instead.
    send_task_with_trace(
        _ROUTER_TASK,
        queue=_ROUTER_QUEUE,
        kwargs={
            "job_id": job_id,
            "document_id": document_id,
            "name": name,
            "object_key": object_key,
            "local_path": None,
            "source_uri": source_uri,
            "source_type_hint": source_type_hint,
            "kb_name": kb,
            "sha256": sha256,
        },
    )

    try:
        ai_logger.info(
            "ingest",
            job_id=job_id,
            document_id=document_id,
            pipeline="router",
            kb_name=kb,
            source_type=source_type,
            name=truncate(name, 128),
            status="pending",
            dedup_hit=False,
            duration_ms=int((time.monotonic() - t0) * 1000),
        )
    except Exception:  # noqa: BLE001
        logger.debug("telemetry emit failed", exc_info=True)

    return {
        "job_id": job_id,
        "status": "pending",
        "dedup_hit": False,
        "document_id": document_id,
    }


# ---------------------------------------------------------------------------
# Convenience wrappers
# ---------------------------------------------------------------------------


def ingest_file(
    file_path: str | Path,
    *,
    filename: str | None = None,
    source_type_hint: str | None = None,
    kb_name: str | None = None,
) -> dict[str, Any]:
    """Convenience wrapper: ingest a local file path."""
    return ingest(
        file_path=file_path,
        filename=filename,
        source_type_hint=source_type_hint,
        kb_name=kb_name,
    )


def ingest_url(
    url: str,
    *,
    source_type_hint: str | None = None,
    kb_name: str | None = None,
) -> dict[str, Any]:
    """Convenience wrapper: ingest a web URL (filename is the URL)."""
    return ingest(
        source_uri=url,
        filename=url,
        source_type_hint=source_type_hint,
        kb_name=kb_name,
    )


def ingest_bytes(
    data: bytes,
    filename: str,
    *,
    source_type_hint: str | None = None,
    kb_name: str | None = None,
) -> dict[str, Any]:
    """Convenience wrapper: ingest in-memory bytes (write a temp file, then call ``ingest``)."""
    suffix = Path(filename).suffix or ""
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        tmp.write(data)
    finally:
        tmp.close()
    return ingest(
        file_path=tmp.name,
        filename=filename,
        source_type_hint=source_type_hint,
        kb_name=kb_name,
    )


def get_job_status(job_id: str) -> dict[str, Any] | None:
    """Look up the job audit record; returns ``None`` if it does not exist."""
    return task_state.get_audit(job_id)
