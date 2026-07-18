"""Ingest and task management API routes."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from eagle_rag.api.schemas.common import DeletedResponse
from eagle_rag.api.schemas.ingest import (
    IngestQueueMetricsResponse,
    IngestResponse,
    QueueMetricItem,
    TaskAuditOut,
    TaskListResponse,
    TaskLogsResponse,
    TaskRetryResponse,
)
from eagle_rag.config import get_settings
from eagle_rag.db import sync_execute
from eagle_rag.index import registry
from eagle_rag.ingest.runner import ingest, ingest_url
from eagle_rag.ingest.url_validator import (
    UrlValidationError,
    assert_not_ssrf_target,
    prefetch_url,
    validate_url_format,
)
from eagle_rag.tasks import state as task_state
from eagle_rag.tasks.celery_app import app as celery_app
from eagle_rag.tasks.state import TaskState
from eagle_rag.telemetry import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["ingest"])

_TERMINAL_STATES = {"success", "failed"}

_PIPELINE_QUEUE: dict[str, tuple[str, str]] = {
    "router": ("eagle_rag.ingest.router.ingest_router", "router_queue"),
    "knowhere": ("eagle_rag.tasks.knowhere_parse", "knowhere_queue"),
    "pixelrag": ("eagle_rag.tasks.pixelrag_build", "pixelrag_queue"),
    "knowhere_visual": ("eagle_rag.tasks.knowhere_visual_chunks", "pixelrag_queue"),
}

_SSE_POLL_INTERVAL = 1.5
_SSE_NO_CHANGE_TIMEOUT = 300


async def _run_sync(fn: Any, /, *args: Any, **kwargs: Any) -> Any:
    """Run a sync DB/external call in a thread pool."""
    return await asyncio.to_thread(fn, *args, **kwargs)


def _serialize(audit: dict[str, Any]) -> str:
    """Serialize an audit dict to a JSON string."""
    return json.dumps(audit, default=str, ensure_ascii=False)


@router.post("/ingest", response_model=IngestResponse)
async def post_ingest(
    file: UploadFile | None = File(None),
    url: str | None = Form(None),
    source_type_hint: str | None = Form(None),
    kb_name: str | None = Form(None),
) -> IngestResponse | JSONResponse:
    """Unified ingest entry: multipart file or URL."""
    if file is None and not url:
        raise HTTPException(status_code=422, detail="Either file or url is required")

    try:
        if file is not None:
            data = await file.read()
            result = await _run_sync(
                ingest,
                file_bytes=data,
                filename=file.filename,
                source_type_hint=source_type_hint,
                kb_name=kb_name,
            )
        else:
            # URL prefetch: validate format, guard SSRF, check reachability before dispatching.
            try:
                validate_url_format(url)
                assert_not_ssrf_target(url)
                cfg = get_settings()
                prefetch_url(
                    url,
                    timeout=cfg.ingest.url_prefetch.timeout_sec,
                    max_redirects=cfg.ingest.url_prefetch.max_redirects,
                )
            except UrlValidationError as exc:
                raise HTTPException(status_code=422, detail=exc.to_detail()) from exc
            result = await _run_sync(
                ingest_url, url, source_type_hint=source_type_hint, kb_name=kb_name
            )
    except ValueError as exc:
        if "knowledge base not registered" in str(exc).lower():
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except HTTPException:
        # Re-raise HTTPException (e.g. URL validation 422) without converting to 500.
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("ingest call failed")
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    response = IngestResponse.model_validate(result)
    status_code = 200 if result.get("dedup_hit") else 201
    return JSONResponse(status_code=status_code, content=response.model_dump())


@router.get("/ingest/queue-metrics", response_model=IngestQueueMetricsResponse)
async def ingest_queue_metrics() -> IngestQueueMetricsResponse:
    """Ingest queue metrics.

    Per-queue concurrency cap (from settings) + backlog size (Redis LLEN,
    best-effort).

    Always returns 200 (concurrency is static config, always available); size is
    null when Redis is unavailable.
    """
    cfg = get_settings().celery

    # Per-queue backlog size: read LLEN from the Redis broker (best-effort).
    sizes: dict[str, int | None] = {}
    try:
        import redis

        client = redis.Redis.from_url(
            cfg.broker_url,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        try:
            for qname in cfg.queues:
                sizes[qname] = int(client.llen(qname))
        finally:
            client.close()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Redis LLEN failed (size falls back to null): %s", exc)

    queues = [
        QueueMetricItem(
            name=name,
            concurrency=q.concurrency,
            size=sizes.get(name),
        )
        for name, q in cfg.queues.items()
    ]
    return IngestQueueMetricsResponse(queues=queues)


@router.get("/tasks", response_model=TaskListResponse)
async def list_tasks(
    pipeline: str | None = Query(None),
    status: str | None = Query(None),
    q: str | None = Query(None, description="Fuzzy match on job_id or document_id"),
    kb_name: str | None = Query(None, description="Filter by knowledge base (multi-tenant)"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> TaskListResponse:
    """List task audit records."""
    try:
        items = await _run_sync(
            task_state.list_audits,
            status=status,
            pipeline=pipeline,
            kb_name=kb_name,
            limit=limit,
            offset=offset,
        )
    except Exception:  # noqa: BLE001
        logger.exception("list_audits failed; database may be unavailable")
        return TaskListResponse(
            items=[],
            limit=limit,
            offset=offset,
            error="database unavailable",
        )

    if q:
        ql = q.lower()
        items = [
            it
            for it in items
            if ql in (it.get("job_id") or "").lower() or ql in (it.get("document_id") or "").lower()
        ]

    return TaskListResponse(
        items=[TaskAuditOut.from_store(it) for it in items],
        limit=limit,
        offset=offset,
    )


@router.get("/tasks/{job_id}", response_model=TaskAuditOut)
async def get_task(job_id: str) -> TaskAuditOut:
    """Get a single task audit detail."""
    try:
        audit = await _run_sync(task_state.get_audit, job_id)
    except Exception:  # noqa: BLE001
        logger.exception("get_audit failed; database may be unavailable")
        raise HTTPException(status_code=503, detail="database unavailable") from None

    if audit is None:
        raise HTTPException(status_code=404, detail="task not found")

    return TaskAuditOut.from_store(audit)


@router.get(
    "/tasks/{job_id}/stream",
    response_class=EventSourceResponse,
    responses={
        200: {
            "description": "SSE task progress stream (event: progress | timeout)",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        }
    },
)
async def stream_task(job_id: str) -> EventSourceResponse:
    """Subscribe to task progress via SSE stream."""

    async def event_generator() -> AsyncIterator[dict[str, str]]:
        last_updated: Any = None
        stable_seconds = 0.0

        while True:
            audit: dict[str, Any] | None = None
            try:
                audit = await _run_sync(task_state.get_audit, job_id)
            except Exception:  # noqa: BLE001
                logger.debug("SSE get_audit failed; database may be unavailable")

            if audit is not None:
                current_updated = audit.get("updated_at")
                if current_updated == last_updated:
                    stable_seconds += _SSE_POLL_INTERVAL
                else:
                    stable_seconds = 0.0
                    last_updated = current_updated

                yield {
                    "event": "progress",
                    "data": _serialize(audit),
                }

                status = (audit.get("status") or "").lower()
                if status in _TERMINAL_STATES:
                    return
            else:
                stable_seconds += _SSE_POLL_INTERVAL

            if stable_seconds >= _SSE_NO_CHANGE_TIMEOUT:
                yield {
                    "event": "timeout",
                    "data": _serialize(
                        {
                            "job_id": job_id,
                            "reason": "no change timeout",
                            "seconds": int(stable_seconds),
                        }
                    ),
                }
                return

            await asyncio.sleep(_SSE_POLL_INTERVAL)

    return EventSourceResponse(event_generator())


@router.get("/tasks/{job_id}/logs", response_model=TaskLogsResponse)
async def get_task_logs(job_id: str) -> TaskLogsResponse:
    """Read task logs (JSONB array)."""
    try:
        audit = await _run_sync(task_state.get_audit, job_id)
    except Exception:  # noqa: BLE001
        logger.exception("get_audit failed; database may be unavailable")
        raise HTTPException(status_code=503, detail="database unavailable") from None

    if audit is None:
        raise HTTPException(status_code=404, detail="task not found")

    return TaskLogsResponse(job_id=job_id, logs=audit.get("logs") or [])


def _visual_chunks_from_minio(document_id: str) -> list[dict[str, Any]]:
    """Rebuild ``knowhere_visual_chunks`` descriptors from MinIO object keys."""
    from eagle_rag.config import get_settings
    from eagle_rag.storage.minio_client import get_minio_client

    bucket = get_settings().minio.bucket
    prefix = f"{document_id}/visual_chunks/"
    client = get_minio_client()
    chunks: list[dict[str, Any]] = []
    for obj in client.list_objects(bucket, prefix=prefix, recursive=True):
        key = obj.object_name
        if not key or key.endswith("/"):
            continue
        stem = Path(key).stem
        suffix = Path(key).suffix.lower()
        chunks.append(
            {
                "chunk_id": stem,
                "type": "table" if suffix == ".html" else "image",
                "object_key": key,
                "summary": "",
                "parent_section": "",
                "file_path": key,
            }
        )
    return chunks


@router.post("/tasks/{job_id}/retry", response_model=TaskRetryResponse)
async def retry_task(job_id: str) -> TaskRetryResponse | JSONResponse:
    """Re-dispatch a task to its Celery queue.

    Restores ``name`` / ``object_key`` / ``source_uri`` / ``source_type_hint`` from
    the ``documents`` table so the downstream task can locate the file (MinIO
    object key or HTTP URL). ``local_path`` is intentionally left None — the
    original temp file lived in the API container's filesystem and is not
    available to workers.

    For ``knowhere_visual`` sub-tasks, rebuilds the ``chunks`` payload from
    MinIO ``{document_id}/visual_chunks/`` (the original Celery kwargs are not
    persisted in ``task_audit``).
    """
    try:
        audit = await _run_sync(task_state.get_audit, job_id)
    except Exception:  # noqa: BLE001
        logger.exception("get_audit failed; database may be unavailable")
        return JSONResponse(status_code=503, content={"detail": "database unavailable"})

    if audit is None:
        raise HTTPException(status_code=404, detail="task not found")

    pipeline_raw = (audit.get("pipeline") or "router").lower().strip()
    pipeline_key = "router" if "," in pipeline_raw else pipeline_raw
    task_name, queue = _PIPELINE_QUEUE.get(pipeline_key, _PIPELINE_QUEUE["router"])
    document_id = audit.get("document_id")
    kb_name = audit.get("kb_name")

    # Recover file-location fields from the documents registry so the retried
    # task can actually fetch the file (the original local_path was a temp file
    # in the API container and is gone).
    name = ""
    object_key: str | None = None
    source_uri: str | None = None
    source_type_hint: str | None = None
    if document_id:
        doc = await _run_sync(registry.get_document_sync, document_id)
        if doc is not None:
            name = doc.get("name") or ""
            stored_uri = doc.get("source_uri")
            source_type_hint = doc.get("source_type")
            if stored_uri and stored_uri.startswith(("http://", "https://")):
                source_uri = stored_uri
            elif stored_uri:
                # documents.source_uri stores the MinIO object_key for file sources
                # (see runner.py: source_uri=source_uri or object_key).
                object_key = stored_uri

    # Reset the audit state to PENDING *before* dispatching, so the worker
    # sees a legal pending→rendering transition when it starts. Doing this
    # after send_task races the worker (it may read the old failed status).
    try:
        await _run_sync(
            sync_execute,
            "UPDATE task_audit SET status = %s, progress = 0, "
            "error = NULL, updated_at = NOW() WHERE job_id = %s",
            (TaskState.PENDING.value, job_id),
        )
    except Exception:  # noqa: BLE001
        logger.warning("Failed to reset audit status to PENDING (non-fatal)")

    if pipeline_key == "knowhere_visual":
        if not document_id:
            raise HTTPException(status_code=422, detail="visual retry requires document_id")
        chunks = await _run_sync(_visual_chunks_from_minio, document_id)
        if not chunks:
            raise HTTPException(
                status_code=422,
                detail=f"no visual chunks in MinIO for document_id={document_id}",
            )
        parent_job_id = job_id.removesuffix(":visual") if job_id.endswith(":visual") else job_id
        kwargs: dict[str, Any] = {
            "job_id": job_id,
            "parent_job_id": parent_job_id,
            "document_id": document_id,
            "kb_name": kb_name,
            "source_type": source_type_hint or "other",
            "chunks": chunks,
        }
    else:
        kwargs = {
            "job_id": job_id,
            "document_id": document_id,
            "name": name,
            "object_key": object_key,
            "local_path": None,
            "source_uri": source_uri,
            "source_type_hint": source_type_hint,
            "kb_name": kb_name,
        }

    try:
        celery_app.send_task(
            task_name,
            kwargs=kwargs,
            queue=queue,
            routing_key=queue,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("retry send_task failed")
        return JSONResponse(
            status_code=502,
            content={"detail": f"retry dispatch failed: {exc}"},
        )

    return TaskRetryResponse(job_id=job_id, status="pending", retried=True)


@router.delete("/tasks/{job_id}", response_model=DeletedResponse)
async def delete_task(job_id: str) -> DeletedResponse:
    """Delete a task audit record."""
    try:
        affected = await _run_sync(task_state.delete_audit, job_id)
    except Exception:  # noqa: BLE001
        logger.exception("delete_audit failed; database may be unavailable")
        raise HTTPException(status_code=503, detail="database unavailable") from None

    if not affected:
        raise HTTPException(status_code=404, detail="task not found")

    return DeletedResponse(deleted=True)
