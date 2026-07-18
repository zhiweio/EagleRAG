"""Collection usage catalog (G28/G30/G31)."""

from __future__ import annotations

import json
from typing import Any

from eagle_rag.db import sync_execute, sync_fetchall, sync_fetchone
from eagle_rag.db.repositories.base import instance_namespace

__all__ = [
    "merge_document_collections",
    "merge_kb_collections",
    "clear_kb_collections",
    "get_document_collections",
    "get_kb_collections",
    "recompute_kb_collections",
]


def merge_document_collections(
    document_id: str,
    collections: list[str],
    *,
    plugin_namespace: str | None = None,
) -> None:
    """Merge ``collections`` into ``documents.extra.collections_used`` after ingest success."""
    ns = instance_namespace(plugin_namespace)
    row = sync_fetchone(
        "SELECT extra FROM documents WHERE document_id = %s AND plugin_namespace = %s",
        (document_id, ns),
    )
    if row is None:
        return
    extra: dict[str, Any] = dict(row[0] or {})
    existing = set(extra.get("collections_used") or [])
    existing.update(collections)
    extra["collections_used"] = sorted(existing)
    sync_execute(
        "UPDATE documents SET extra = %s::jsonb, updated_at = NOW() "
        "WHERE document_id = %s AND plugin_namespace = %s",
        (json.dumps(extra, ensure_ascii=False), document_id, ns),
    )


def merge_kb_collections(
    kb_name: str,
    collections: list[str],
    *,
    plugin_namespace: str | None = None,
) -> None:
    """Union ``collections`` into ``knowledge_bases.collections_used``."""
    if not collections:
        return
    ns = instance_namespace(plugin_namespace)
    sync_execute(
        """
        UPDATE knowledge_bases
        SET collections_used = (
            SELECT COALESCE(jsonb_agg(DISTINCT elem), '[]'::jsonb)
            FROM (
                SELECT jsonb_array_elements_text(COALESCE(collections_used, '[]'::jsonb)) AS elem
                UNION
                SELECT unnest(%s::text[])
            ) s
        ),
        updated_at = NOW()
        WHERE kb_name = %s AND plugin_namespace = %s
        """,
        (collections, kb_name, ns),
    )


def clear_kb_collections(kb_name: str, *, plugin_namespace: str | None = None) -> None:
    ns = instance_namespace(plugin_namespace)
    sync_execute(
        "UPDATE knowledge_bases SET collections_used = '[]'::jsonb, updated_at = NOW() "
        "WHERE kb_name = %s AND plugin_namespace = %s",
        (kb_name, ns),
    )


def get_document_collections(
    document_ids: list[str],
    *,
    plugin_namespace: str | None = None,
) -> set[str]:
    if not document_ids:
        return set()
    ns = instance_namespace(plugin_namespace)
    row = sync_fetchone(
        """
        SELECT COALESCE(
            jsonb_agg(DISTINCT elem),
            '[]'::jsonb
        )
        FROM documents d,
        LATERAL jsonb_array_elements_text(
            COALESCE(d.extra->'collections_used', '[]'::jsonb)
        ) AS elem
        WHERE d.document_id = ANY(%s) AND d.plugin_namespace = %s
        """,
        (document_ids, ns),
    )
    if row is None or row[0] is None:
        return set()
    return set(row[0])


def get_kb_collections(
    kb_names: list[str],
    *,
    plugin_namespace: str | None = None,
) -> set[str]:
    if not kb_names:
        return set()
    ns = instance_namespace(plugin_namespace)
    rows = sync_fetchall(
        """
        SELECT collections_used FROM knowledge_bases
        WHERE kb_name = ANY(%s) AND plugin_namespace = %s
        """,
        (kb_names, ns),
    )
    out: set[str] = set()
    for row in rows:
        for c in row[0] or []:
            out.add(c)
    return out


def recompute_kb_collections(kb_name: str, *, plugin_namespace: str | None = None) -> None:
    """Rebuild ``knowledge_bases.collections_used`` from surviving documents (G31)."""
    ns = instance_namespace(plugin_namespace)
    row = sync_fetchone(
        """
        SELECT COALESCE(
            jsonb_agg(DISTINCT elem ORDER BY elem),
            '[]'::jsonb
        )
        FROM documents d,
        LATERAL jsonb_array_elements_text(
            COALESCE(d.extra->'collections_used', '[]'::jsonb)
        ) AS elem
        WHERE d.kb_name = %s AND d.plugin_namespace = %s
        """,
        (kb_name, ns),
    )
    merged = row[0] if row is not None else []
    sync_execute(
        """
        UPDATE knowledge_bases
        SET collections_used = %s::jsonb, updated_at = NOW()
        WHERE kb_name = %s AND plugin_namespace = %s
        """,
        (json.dumps(merged, ensure_ascii=False), kb_name, ns),
    )
