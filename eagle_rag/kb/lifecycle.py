"""KB lifecycle: cascading deletion and index rebuild."""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from eagle_rag.db import sync_execute
from eagle_rag.tasks.celery_app import app as celery_app
from eagle_rag.tasks.state import TaskState, create_audit, update_state

logger = logging.getLogger(__name__)

__all__ = ["delete_kb_namespace", "start_rebuild"]

_REBUILD_TASK = "eagle_rag.kb.lifecycle.kb_rebuild"


def delete_kb_namespace(kb_name: str) -> dict[str, int]:
    """Cascade-delete all data under the KB namespace, then the registry row.

    Returns:
        Per-layer deletion counts.
    """
    counts: dict[str, int] = {
        "milvus_text": 0,
        "milvus_visual": 0,
        "documents": 0,
        "images": 0,
        "dedup": 0,
        "task_audit": 0,
    }

    try:
        from eagle_rag.index.milvus_text_store import delete_text_by_kb

        counts["milvus_text"] = delete_text_by_kb(kb_name)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Milvus text delete failed kb=%s: %s", kb_name, exc)

    try:
        from eagle_rag.index.milvus_visual_store import delete_visual_by_kb

        counts["milvus_visual"] = delete_visual_by_kb(kb_name)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Milvus visual delete failed kb=%s: %s", kb_name, exc)

    counts["documents"] = sync_execute("DELETE FROM documents WHERE kb_name = %s", (kb_name,))
    counts["images"] = sync_execute("DELETE FROM images WHERE kb_name = %s", (kb_name,))
    counts["dedup"] = sync_execute("DELETE FROM document_dedup WHERE kb_name = %s", (kb_name,))
    counts["task_audit"] = sync_execute("DELETE FROM task_audit WHERE kb_name = %s", (kb_name,))

    sync_execute("DELETE FROM knowledge_bases WHERE kb_name = %s", (kb_name,))
    return counts


def start_rebuild(kb_name: str) -> str:
    """Start an async rebuild task and return its job_id.

    The rebuild re-embeds existing text vectors without re-parsing documents,
    so no document count query is needed upfront — the task itself reads
    the actual vector count from Milvus.
    """
    job_id = str(uuid4())
    create_audit(
        job_id,
        document_id=f"rebuild:{kb_name}",
        pipeline="rebuild",
        kb_name=kb_name,
    )
    update_state(job_id, TaskState.PENDING, log_entry="Reindex (re-embed only)")

    celery_app.send_task(
        _REBUILD_TASK,
        kwargs={"job_id": job_id, "kb_name": kb_name},
        queue="router_queue",
        routing_key="router_queue",
        task_id=job_id,
    )
    return job_id


@celery_app.task(name=_REBUILD_TASK, bind=True)  # type: ignore[misc]
def kb_rebuild(self, job_id: str, kb_name: str) -> dict[str, Any]:  # noqa: ARG001
    """Re-embed and re-index all text nodes for a KB without re-parsing.

    Lightweight rebuild: reads existing text + metadata from Milvus, deletes
    old vectors, re-embeds with the current embedding model, and writes back.
    No Knowhere re-parse, no file download, no visual chunk re-processing —
    just embedding + index write.

    Visual (pixelrag) index is not touched; re-embedding visual vectors
    requires the original images and is left for a separate operation.
    """
    try:
        update_state(job_id, TaskState.RENDERING, log_entry="Reindex started (re-embed only)")

        from eagle_rag.index.milvus_text_store import count_text, reindex_kb_text

        total = count_text(kb_name=kb_name)
        update_state(
            job_id,
            TaskState.EMBEDDING,
            current=0,
            total=total,
            log_entry=f"{total} text vectors queued for re-embed",
        )

        if total == 0:
            update_state(job_id, TaskState.SUCCESS, log_entry="No documents to reindex")
            return {"job_id": job_id, "rebuilt": 0}

        reindexed = reindex_kb_text(kb_name)

        update_state(
            job_id,
            TaskState.SUCCESS,
            current=reindexed,
            total=reindexed,
            progress=100,
            log_entry=f"Reindex complete, {reindexed} vectors re-embedded",
        )
        return {"job_id": job_id, "rebuilt": reindexed}
    except Exception as exc:  # noqa: BLE001
        update_state(job_id, TaskState.FAILED, error=str(exc), log_entry=f"Reindex failed: {exc}")
        raise
