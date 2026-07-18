"""Task state machine and task_audit audit-table persistence.

The state machine covers the full lifecycle of a document from enqueue to indexing
completion: ``PENDING → RENDERING → EMBEDDING → INDEXING → SUCCESS``. A dedup hit
may short-circuit directly ``PENDING → SUCCESS``. Any processing stage may transition
to ``RETRYING`` (in retry) or ``FAILED`` (terminal failure); from ``RETRYING`` the
task may return to any processing stage. ``SUCCESS`` is the success terminal state;
``FAILED`` may return to ``PENDING`` via manual replay.

All functions are synchronous (built on psycopg2) and intended for direct calls from
Celery tasks; they do not depend on the Celery task context and perform pure DB ops.
Schema is managed by Alembic; run ``alembic upgrade head`` before deployment.
"""

from __future__ import annotations

import datetime
import enum
import json
from typing import Any

from eagle_rag.config import get_settings
from eagle_rag.db import sync_execute, sync_fetchall, sync_fetchone
from eagle_rag.telemetry import get_logger

logger = get_logger(__name__)

__all__ = [
    "TaskState",
    "InvalidStateTransitionError",
    "ALLOWED_TRANSITIONS",
    "validate_transition",
    "transition",
    "create_audit",
    "update_state",
    "get_audit",
    "list_audits",
    "delete_audit",
    "append_log",
]


class TaskState(enum.StrEnum):
    """Task lifecycle states."""

    PENDING = "pending"  # Enqueued, awaiting processing
    RENDERING = "rendering"  # PixelRAG rendering / Knowhere parsing in progress
    EMBEDDING = "embedding"  # Vectorization in progress
    INDEXING = "indexing"  # Writing to index in progress
    SUCCESS = "success"  # Success (terminal)
    FAILED = "failed"  # Failed (may be manually replayed)
    RETRYING = "retrying"  # Retrying


# Allowed transition graph: from_state -> {permitted to_state}.
# Processing stages may self-transition (progress update without state change);
# SUCCESS is an absorbing terminal state; FAILED may self-transition (idempotent
# update) and return to PENDING (manual replay).
ALLOWED_TRANSITIONS: dict[TaskState, set[TaskState]] = {
    TaskState.PENDING: {
        TaskState.RENDERING,
        TaskState.SUCCESS,
        TaskState.RETRYING,
        TaskState.FAILED,
        TaskState.PENDING,
    },
    TaskState.RENDERING: {
        TaskState.EMBEDDING,
        TaskState.RETRYING,
        TaskState.FAILED,
        TaskState.RENDERING,
    },
    TaskState.EMBEDDING: {
        TaskState.INDEXING,
        TaskState.RETRYING,
        TaskState.FAILED,
        TaskState.EMBEDDING,
    },
    TaskState.INDEXING: {
        TaskState.SUCCESS,
        TaskState.RETRYING,
        TaskState.FAILED,
        TaskState.INDEXING,
    },
    TaskState.RETRYING: {
        TaskState.RENDERING,
        TaskState.EMBEDDING,
        TaskState.INDEXING,
        TaskState.PENDING,
        TaskState.FAILED,
        TaskState.RETRYING,
    },
    TaskState.SUCCESS: set(),  # Terminal state, no further transitions
    TaskState.FAILED: {
        TaskState.PENDING,
        TaskState.RENDERING,
        TaskState.FAILED,
    },  # Auto-retry / manual replay
}


class InvalidStateTransitionError(Exception):
    """Raised on illegal state transition or missing audit record."""


def validate_transition(from_state: TaskState, to_state: TaskState) -> bool:
    """Return whether ``from_state -> to_state`` is a legal transition."""
    return to_state in ALLOWED_TRANSITIONS.get(from_state, set())


def transition(from_state: TaskState, to_state: TaskState) -> None:
    """Validate the state transition; raise ``InvalidStateTransitionError`` if illegal."""
    if not validate_transition(from_state, to_state):
        raise InvalidStateTransitionError(
            f"illegal state transition: {from_state.value} -> {to_state.value}"
        )


# ---------------------------------------------------------------------------
# Audit table CRUD
# ---------------------------------------------------------------------------

_COLUMNS = (
    "job_id",
    "document_id",
    "name",
    "source_uri",
    "pipeline",
    "status",
    "progress",
    "current",
    "total",
    "error",
    "logs",
    "created_at",
    "updated_at",
    "kb_name",
    "plugin_namespace",
)
_SELECT_SQL = (
    "SELECT job_id, document_id, name, source_uri, pipeline, status, progress, "
    "current, total, error, logs, created_at, updated_at, kb_name, plugin_namespace "
    "FROM task_audit"
)


def _now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def _wrap_log(entry: Any) -> dict[str, Any]:
    """Wrap a log entry into a timestamped dict."""
    ts = _now_iso()
    if isinstance(entry, dict):
        return {"ts": ts, **entry}
    if isinstance(entry, str):
        return {"ts": ts, "msg": entry}
    return {"ts": ts, "msg": str(entry)}


def _row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    return dict(zip(_COLUMNS, row))


def _resolve_kb(kb_name: str | None) -> str:
    """Fall back to the global ``settings.kb_name`` when kb_name is None."""
    return kb_name if kb_name is not None else get_settings().kb_name


def create_audit(
    job_id: str,
    document_id: str | None,
    pipeline: str,
    *,
    kb_name: str | None = None,
    name: str | None = None,
    source_uri: str | None = None,
    plugin_namespace: str | None = None,
) -> None:
    """Insert a PENDING audit record (called when a task is enqueued)."""
    from eagle_rag.db.repositories.base import instance_namespace

    kb = _resolve_kb(kb_name)
    ns = instance_namespace(plugin_namespace)
    sync_execute(
        "INSERT INTO task_audit "
        "(job_id, document_id, name, source_uri, pipeline, status, progress, logs, kb_name, "
        "plugin_namespace) "
        "VALUES (%s, %s, %s, %s, %s, %s, 0, '[]', %s, %s)",
        (job_id, document_id, name, source_uri, pipeline, TaskState.PENDING.value, kb, ns),
    )


def update_state(
    job_id: str,
    state: TaskState,
    *,
    current: int | None = None,
    total: int | None = None,
    progress: int | None = None,
    error: str | None = None,
    log_entry: Any = None,
) -> None:
    """Update the task state and write to the audit table.

    - Reads the current status first and validates ``current -> state``; raises
      ``InvalidStateTransitionError`` on illegal transitions or missing audit records.
    - When ``progress`` is omitted but ``current``/``total`` are both given with
      total > 0, computes ``int(current/total*100)`` clamped to 0-100.
    - When ``log_entry`` is given, appends it to the ``logs`` JSONB array (via
      ``logs || %s::jsonb``); dict/str/other entries are wrapped as
      ``{"ts": iso_now, ...}``.
    - Sets ``updated_at = NOW()``.
    """
    row = sync_fetchone("SELECT status FROM task_audit WHERE job_id = %s", (job_id,))
    if row is None:
        raise InvalidStateTransitionError(f"task_audit record not found: job_id={job_id}")
    from_state = TaskState(row[0])
    transition(from_state, state)

    sets: list[str] = ["status = %s", "updated_at = NOW()"]
    params: list[Any] = [state.value]

    if current is not None:
        sets.append("current = %s")
        params.append(current)
    if total is not None:
        sets.append("total = %s")
        params.append(total)
    if progress is not None:
        sets.append("progress = %s")
        params.append(min(100, max(0, int(progress))))
    elif current is not None and total is not None and total > 0:
        sets.append("progress = %s")
        params.append(min(100, max(0, int(current / total * 100))))

    if error is not None:
        sets.append("error = %s")
        params.append(error)

    if log_entry is not None:
        sets.append("logs = logs || %s::jsonb")
        params.append(json.dumps([_wrap_log(log_entry)], ensure_ascii=False))

    params.append(job_id)
    sql = f"UPDATE task_audit SET {', '.join(sets)} WHERE job_id = %s"
    sync_execute(sql, tuple(params))

    if state in (TaskState.SUCCESS, TaskState.FAILED):
        _maybe_notify(job_id, state, error=error)


def _maybe_notify(job_id: str, state: TaskState, *, error: str | None = None) -> None:
    """Best-effort notification on terminal state."""
    try:
        from eagle_rag.notifications.store import create_notification_sync

        audit = get_audit(job_id)
        if audit is None:
            return
        kb = audit.get("kb_name")
        ns = audit.get("plugin_namespace")
        pipeline = (audit.get("pipeline") or "ingest").lower()
        if pipeline == "rebuild":
            if state == TaskState.SUCCESS:
                create_notification_sync(
                    ntype="rebuild_complete",
                    title="Reindex complete",
                    body=f"Knowledge base {kb or ''} reindex job {job_id[:8]}… finished",
                    kb_name=kb,
                    job_id=job_id,
                    plugin_namespace=ns,
                )
            else:
                create_notification_sync(
                    ntype="rebuild_failed",
                    title="Reindex failed",
                    body=error or f"Knowledge base {kb or ''} reindex job {job_id[:8]}… failed",
                    kb_name=kb,
                    job_id=job_id,
                    plugin_namespace=ns,
                )
        elif state == TaskState.SUCCESS:
            create_notification_sync(
                ntype="ingest_complete",
                title="Ingest complete",
                body=f"Job {job_id[:8]}… ({pipeline}) succeeded",
                kb_name=kb,
                job_id=job_id,
                plugin_namespace=ns,
            )
        else:
            create_notification_sync(
                ntype="ingest_failed",
                title="Ingest failed",
                body=error or f"Job {job_id[:8]}… failed",
                kb_name=kb,
                job_id=job_id,
                plugin_namespace=ns,
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug("notification write failed (non-fatal): %s", exc)


def append_log(job_id: str, entry: Any) -> None:
    """Append a single log entry to the ``logs`` array without changing state or progress."""
    wrapped = json.dumps([_wrap_log(entry)], ensure_ascii=False)
    sync_execute(
        "UPDATE task_audit SET logs = logs || %s::jsonb, updated_at = NOW() WHERE job_id = %s",
        (wrapped, job_id),
    )


def get_audit(job_id: str) -> dict[str, Any] | None:
    """Return a single audit record by job_id, or None if not found."""
    row = sync_fetchone(f"{_SELECT_SQL} WHERE job_id = %s", (job_id,))
    return _row_to_dict(row) if row is not None else None


def list_audits(
    *,
    status: TaskState | str | None = None,
    pipeline: str | None = None,
    document_id: str | None = None,
    kb_name: str | None = None,
    limit: int = 50,
    offset: int = 0,
    plugin_namespace: str | None = None,
) -> list[dict[str, Any]]:
    """List audit records matching the filters (newest first, paginated)."""
    from eagle_rag.db.repositories.base import instance_namespace

    ns = instance_namespace(plugin_namespace)
    where: list[str] = ["plugin_namespace = %s"]
    params: list[Any] = [ns]
    if status is not None:
        where.append("status = %s")
        params.append(status.value if isinstance(status, TaskState) else status)
    if pipeline is not None:
        where.append("pipeline = %s")
        params.append(pipeline)
    if document_id is not None:
        where.append("document_id = %s")
        params.append(document_id)
    if kb_name is not None:
        where.append("kb_name = %s")
        params.append(kb_name)
    where_clause = " WHERE " + " AND ".join(where)
    sql = f"{_SELECT_SQL}{where_clause} ORDER BY created_at DESC LIMIT %s OFFSET %s"
    params.extend([limit, offset])
    rows = sync_fetchall(sql, tuple(params))
    return [_row_to_dict(r) for r in rows]


def delete_audit(job_id: str) -> int:
    """Delete a single audit record; return the number of affected rows."""
    return sync_execute("DELETE FROM task_audit WHERE job_id = %s", (job_id,))
