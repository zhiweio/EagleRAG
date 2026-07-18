"""Task audit repository (G9/G11)."""

from __future__ import annotations

from typing import Any

from eagle_rag.tasks import state as task_state
from eagle_rag.tasks.state import TaskState

__all__ = [
    "create_audit",
    "get_audit",
    "list_audits",
    "count_audits",
    "update_state",
    "append_log",
    "delete_audit",
]


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
    task_state.create_audit(
        job_id,
        document_id,
        pipeline,
        kb_name=kb_name,
        name=name,
        source_uri=source_uri,
        plugin_namespace=plugin_namespace,
    )


def get_audit(job_id: str) -> dict[str, Any] | None:
    return task_state.get_audit(job_id)


def list_audits(
    *,
    status: TaskState | str | None = None,
    pipeline: str | None = None,
    document_id: str | None = None,
    kb_name: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
    plugin_namespace: str | None = None,
) -> list[dict[str, Any]]:
    return task_state.list_audits(
        status=status,
        pipeline=pipeline,
        document_id=document_id,
        kb_name=kb_name,
        q=q,
        limit=limit,
        offset=offset,
        plugin_namespace=plugin_namespace,
    )


def count_audits(
    *,
    status: TaskState | str | None = None,
    pipeline: str | None = None,
    document_id: str | None = None,
    kb_name: str | None = None,
    q: str | None = None,
    plugin_namespace: str | None = None,
) -> int:
    return task_state.count_audits(
        status=status,
        pipeline=pipeline,
        document_id=document_id,
        kb_name=kb_name,
        q=q,
        plugin_namespace=plugin_namespace,
    )


def update_state(job_id: str, state: TaskState, **kwargs: Any) -> None:
    task_state.update_state(job_id, state, **kwargs)


def append_log(job_id: str, entry: Any) -> None:
    task_state.append_log(job_id, entry)


def delete_audit(job_id: str) -> int:
    return task_state.delete_audit(job_id)
