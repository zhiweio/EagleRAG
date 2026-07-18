"""KB lifecycle: cascading deletion and index rebuild."""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from eagle_rag.db import sync_execute
from eagle_rag.db.repositories.base import instance_namespace
from eagle_rag.db.repositories.catalog import clear_kb_collections
from eagle_rag.index.milvus_kb_ops import base_collection_names, delete_vectors_by_kb
from eagle_rag.tasks.celery_app import app as celery_app
from eagle_rag.tasks.state import TaskState, create_audit, update_state

logger = logging.getLogger(__name__)

__all__ = ["delete_kb_namespace", "start_rebuild", "reclassify_kb"]

_REBUILD_TASK = "eagle_rag.kb.lifecycle.kb_rebuild"


def _collections_for_instance(plugin_namespace: str | None = None) -> list[str]:
    from eagle_rag.plugins import get_plugin_manager

    text_coll, visual_coll = base_collection_names()
    mgr = get_plugin_manager()
    specialized = list(mgr.get_specialized_collections(plugin_namespace))
    return list(dict.fromkeys([text_coll, visual_coll, *specialized]))


def delete_kb_namespace(
    kb_name: str,
    *,
    plugin_namespace: str | None = None,
) -> dict[str, int]:
    """Cascade-delete all data under the KB namespace, then the registry row.

    Returns:
        Per-layer deletion counts.
    """
    ns = instance_namespace(plugin_namespace)
    counts: dict[str, int] = {
        "milvus_text": 0,
        "milvus_visual": 0,
        "milvus_specialized": 0,
        "documents": 0,
        "images": 0,
        "dedup": 0,
        "task_audit": 0,
    }

    text_coll, visual_coll = base_collection_names()
    for coll in _collections_for_instance(ns):
        try:
            deleted = delete_vectors_by_kb(coll, kb_name, plugin_namespace=ns)
            if coll == text_coll:
                counts["milvus_text"] = deleted
            elif coll == visual_coll:
                counts["milvus_visual"] = deleted
            else:
                counts["milvus_specialized"] += deleted
        except Exception as exc:  # noqa: BLE001
            logger.warning("Milvus delete failed kb=%s coll=%s: %s", kb_name, coll, exc)

    counts["documents"] = sync_execute(
        "DELETE FROM documents WHERE kb_name = %s AND plugin_namespace = %s",
        (kb_name, ns),
    )
    counts["images"] = sync_execute(
        "DELETE FROM images WHERE kb_name = %s AND plugin_namespace = %s",
        (kb_name, ns),
    )
    counts["dedup"] = sync_execute(
        "DELETE FROM document_dedup WHERE kb_name = %s AND plugin_namespace = %s",
        (kb_name, ns),
    )
    counts["task_audit"] = sync_execute(
        "DELETE FROM task_audit WHERE kb_name = %s AND plugin_namespace = %s",
        (kb_name, ns),
    )

    sync_execute(
        "DELETE FROM knowledge_bases WHERE kb_name = %s AND plugin_namespace = %s",
        (kb_name, ns),
    )
    return counts


def start_rebuild(
    kb_name: str,
    *,
    plugin_namespace: str | None = None,
) -> str:
    """Start an async rebuild task and return its job_id.

    The rebuild re-embeds existing text vectors without re-parsing documents,
    so no document count query is needed upfront — the task itself reads
    the actual vector count from Milvus.
    """
    ns = instance_namespace(plugin_namespace)
    job_id = str(uuid4())
    create_audit(
        job_id,
        document_id=f"rebuild:{kb_name}",
        pipeline="rebuild",
        kb_name=kb_name,
    )
    update_state(job_id, TaskState.PENDING, log_entry="Reindex (re-embed only)")
    clear_kb_collections(kb_name, plugin_namespace=ns)

    celery_app.send_task(
        _REBUILD_TASK,
        kwargs={"job_id": job_id, "kb_name": kb_name, "plugin_namespace": ns},
        queue="router_queue",
        routing_key="router_queue",
        task_id=job_id,
    )
    return job_id


@celery_app.task(name=_REBUILD_TASK, bind=True)  # type: ignore[misc]
def kb_rebuild(
    self,  # noqa: ARG001
    job_id: str,
    kb_name: str,
    plugin_namespace: str | None = None,
) -> dict[str, Any]:
    """Re-embed and re-index all text nodes for a KB without re-parsing.

    Lightweight rebuild: reads existing text + metadata from Milvus, deletes
    old vectors, re-embeds with the current embedding model, and writes back.
    No Knowhere re-parse, no file download, no visual chunk re-processing —
    just embedding + index write.

    Visual (pixelrag) index is not touched; re-embedding visual vectors
    requires the original images and is left for a separate operation.
    """
    ns = instance_namespace(plugin_namespace)
    try:
        update_state(job_id, TaskState.RENDERING, log_entry="Reindex started (re-embed only)")

        from eagle_rag.db.repositories.catalog import merge_kb_collections
        from eagle_rag.index.milvus_text_store import count_text, reindex_kb_text

        total = count_text(kb_name=kb_name, plugin_namespace=ns)
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
        text_coll, _ = base_collection_names()
        merge_kb_collections(kb_name, [text_coll], plugin_namespace=ns)

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


_RECLASSIFY_TASK = "eagle_rag.kb.lifecycle.reclassify_kb"


@celery_app.task(name=_RECLASSIFY_TASK, bind=True)  # type: ignore[misc]
def reclassify_kb(
    self,  # noqa: ARG001
    kb_name: str,
    *,
    plugin_namespace: str | None = None,
) -> dict[str, Any]:
    """Re-dispatch ingest for all documents in a KB (P1-24).

    Full re-parse is required to re-run per-chunk classifiers; this queues
    ``ingest_router`` for each registered document in the knowledge base.
    """
    from eagle_rag.db import sync_fetchall
    from eagle_rag.ingest.router import ingest_router

    ns = instance_namespace(plugin_namespace)
    rows = sync_fetchall(
        """
        SELECT document_id, source_uri, source_type, pipeline
        FROM documents
        WHERE kb_name = %s AND plugin_namespace = %s AND status = 'ready'
        """,
        (kb_name, ns),
    )
    dispatched = 0
    for row in rows:
        doc_id, source_uri, source_type, _pipeline = row
        if not source_uri:
            continue
        ingest_router.apply_async(
            kwargs={
                "job_id": str(uuid4()),
                "document_id": doc_id,
                "name": doc_id,
                "object_key": source_uri if source_uri.startswith("ingest/") else None,
                "local_path": None,
                "source_uri": source_uri,
                "source_type_hint": source_type,
                "kb_name": kb_name,
                "plugin_namespace": ns,
            },
            queue="router_queue",
            routing_key="router_queue",
        )
        dispatched += 1
    return {"kb_name": kb_name, "dispatched": dispatched, "plugin_namespace": ns}
