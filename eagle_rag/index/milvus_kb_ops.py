"""KB-scoped Milvus operations across collections (G24/G25/P1-16)."""

from __future__ import annotations

from typing import Any

from eagle_rag.config import get_settings
from eagle_rag.db.repositories.base import instance_namespace
from eagle_rag.index.milvus_pool import get_milvus_pool
from eagle_rag.telemetry import get_logger

__all__ = [
    "count_entities_by_kb",
    "delete_vectors_by_kb",
    "list_present_collections",
]

logger = get_logger(__name__)


def _client(plugin_namespace: str | None = None) -> Any:
    return get_milvus_pool().get(plugin_namespace=instance_namespace(plugin_namespace))


def list_present_collections(*, plugin_namespace: str | None = None) -> list[str]:
    """List Milvus collections in the instance database."""
    try:
        return list(_client(plugin_namespace).list_collections())
    except Exception as exc:  # noqa: BLE001
        logger.warning("list_collections failed: %s", exc)
        return []


def count_entities_by_kb(
    collection: str,
    kb_name: str,
    *,
    plugin_namespace: str | None = None,
) -> int:
    """Count entities in ``collection`` filtered by ``kb_name``."""
    client = _client(plugin_namespace)
    if not client.has_collection(collection):
        return 0
    expr = f'kb_name == "{kb_name}"'
    try:
        rows = client.query(collection, filter=expr, output_fields=["count(*)"])
        if rows:
            return int(rows[0].get("count(*)", 0))
    except Exception:  # noqa: BLE001
        pass
    try:
        rows = client.query(collection, filter=expr, output_fields=["id"], limit=16384)
        return len(rows)
    except Exception as exc:  # noqa: BLE001
        logger.warning("count_entities_by_kb failed coll=%s kb=%s: %s", collection, kb_name, exc)
        return 0


def delete_vectors_by_kb(
    collection: str,
    kb_name: str,
    *,
    plugin_namespace: str | None = None,
) -> int:
    """Delete all vectors in ``collection`` for ``kb_name``."""
    client = _client(plugin_namespace)
    if not client.has_collection(collection):
        return 0
    expr = f'kb_name == "{kb_name}"'
    try:
        rows = client.query(collection, filter=expr, output_fields=["id"], limit=16384)
        if not rows:
            return 0
        client.delete(collection, filter=expr)
        return len(rows)
    except Exception as exc:  # noqa: BLE001
        logger.warning("delete_vectors_by_kb failed coll=%s kb=%s: %s", collection, kb_name, exc)
        return 0


def base_collection_names() -> tuple[str, str]:
    cfg = get_settings().milvus
    return cfg.text_collection, cfg.visual_collection
