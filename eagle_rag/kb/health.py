"""KB health probe: derive KB status from Milvus reachability and task failure rate."""

from __future__ import annotations

from eagle_rag.config import get_settings
from eagle_rag.telemetry import get_logger

logger = get_logger(__name__)

__all__ = ["compute_kb_status"]


def _milvus_reachable() -> bool:
    """Probe whether both Milvus collections are reachable (has_collection + describe)."""
    try:
        from pymilvus import MilvusClient
    except ImportError:
        logger.warning("pymilvus not installed; KB status degraded")
        return False
    cfg = get_settings().milvus
    client = MilvusClient(uri=f"http://{cfg.host}:{cfg.port}")
    try:
        for name in [cfg.text_collection, cfg.visual_collection]:
            try:
                if not client.has_collection(name):
                    logger.warning("Milvus collection does not exist: %s", name)
                    return False
                client.describe_collection(name)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Milvus describe_collection failed %s: %s", name, exc)
                return False
        return True
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass


async def _has_recent_failures(kb_name: str) -> bool:
    """Whether the KB has any failed tasks in the last hour."""
    from eagle_rag.db import async_fetchrow

    try:
        row = await async_fetchrow(
            """
            SELECT COUNT(*)::int AS cnt FROM task_audit
            WHERE kb_name = $1 AND status = 'failed'
              AND created_at >= NOW() - INTERVAL '1 hour'
            """,
            kb_name,
        )
        return bool(row and int(row["cnt"] or 0) > 0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("failed to query task_audit failures kb=%s: %s", kb_name, exc)
        return False


async def compute_kb_status(kb_name: str) -> str:
    """Derive KB runtime status: online / degraded / offline.

    - Both Milvus collections reachable and no failed tasks in the last hour → online
    - Milvus reachable but failed tasks in the last hour → degraded
    - Milvus unreachable → offline

    Each step is wrapped in try/except and never raises.
    """
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
