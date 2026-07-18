"""Ingest success catalog updates (G28/G30)."""

from __future__ import annotations

from eagle_rag.db.repositories.base import instance_namespace
from eagle_rag.db.repositories.catalog import merge_document_collections, merge_kb_collections
from eagle_rag.telemetry import get_logger

__all__ = ["commit_ingest_catalog"]

logger = get_logger(__name__)


def commit_ingest_catalog(
    document_id: str,
    kb_name: str,
    collections: list[str],
    *,
    plugin_namespace: str | None = None,
) -> None:
    """Record collections used after ingest reaches terminal success."""
    if not collections:
        return
    ns = instance_namespace(plugin_namespace)
    try:
        merge_document_collections(
            document_id,
            collections,
            plugin_namespace=ns,
        )
        merge_kb_collections(
            kb_name,
            collections,
            plugin_namespace=ns,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "ingest catalog update failed (non-blocking) doc=%s: %s",
            document_id,
            exc,
        )
