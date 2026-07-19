"""KB health probe: derive KB status from Milvus reachability and task failure rate."""

from __future__ import annotations

from eagle_rag.config import get_settings
from eagle_rag.db.repositories.base import instance_namespace
from eagle_rag.index.milvus_pool import get_milvus_pool
from eagle_rag.telemetry import get_logger

logger = get_logger(__name__)

__all__ = ["compute_kb_status"]


def _milvus_reachable() -> bool:
    """Probe whether base Milvus collections are reachable (G24 pooled client)."""
    cfg = get_settings().milvus
    try:
        client = get_milvus_pool().get()
        for name in [cfg.text_collection, cfg.visual_collection]:
            if not client.has_collection(name):
                logger.warning("Milvus collection does not exist: %s", name)
                return False
            client.describe_collection(name)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Milvus health probe failed: %s", exc)
        return False


async def _has_recent_failures(kb_name: str) -> bool:
    """Whether the KB has any failed tasks in the last hour."""
    from eagle_rag.db import async_fetchrow

    ns = instance_namespace()
    try:
        row = await async_fetchrow(
            """
            SELECT COUNT(*)::int AS cnt FROM task_audit
            WHERE kb_name = $1 AND plugin_namespace = $2 AND status = 'failed'
              AND created_at >= NOW() - INTERVAL '1 hour'
            """,
            kb_name,
            ns,
        )
        return bool(row and int(row["cnt"] or 0) > 0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("failed to query task_audit failures kb=%s: %s", kb_name, exc)
        return False


async def compute_kb_status(kb_name: str) -> str:
    """Derive KB runtime status: online / degraded / offline."""
    milvus_ok = False
    try:
        milvus_ok = _milvus_reachable()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Milvus health probe error kb=%s: %s", kb_name, exc)
        return "offline"
    if not milvus_ok:
        return "offline"
    if await _has_recent_failures(kb_name):
        return "degraded"
    return "online"
