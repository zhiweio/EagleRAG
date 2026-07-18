"""Document registry (PostgreSQL).

Registers per-document metadata for ingestion adapters and powers
`GET /documents` and `GET /documents/{id}`. Phase 2 adapters call the
synchronous write APIs; the Phase 6 API layer calls the asynchronous query APIs.

Schema:
    documents(
        document_id  TEXT PK,
        name         TEXT NOT NULL,
        source_type  TEXT NOT NULL,   -- policy | financial | business | bidding | tax | other
        source_uri   TEXT,            -- original path / URL / MinIO key
        pipeline     TEXT NOT NULL,   -- knowhere | pixelrag
        status       TEXT NOT NULL,   -- pending | indexing | ready | failed
        sha256       TEXT,            -- dedup fingerprint
        chunk_count  INT DEFAULT 0,
        extra        JSONB,           -- extra metadata (page_count, nav_tree_summary, etc.)
        created_at   TIMESTAMPTZ DEFAULT NOW(),
        updated_at   TIMESTAMPTZ DEFAULT NOW(),
        kb_name      TEXT NOT NULL DEFAULT 'default'  -- knowledge-base dimension (multi-tenant)
    )
"""

from __future__ import annotations

import json
from typing import Any

from eagle_rag.config import get_settings
from eagle_rag.db import (
    acquire_async,
    async_fetch,
    async_fetchrow,
    sync_execute,
    sync_fetchone,
)
from eagle_rag.db.repositories.base import instance_namespace

__all__ = [
    "register_document",
    "update_status",
    "update_chunk_count",
    "update_extra",
    "get_document_sync",
    "get_document",
    "list_documents",
    "count_documents",
    "delete_document",
]


def _resolve_kb(kb_name: str | None) -> str:
    """Fall back to global ``settings.kb_name`` when ``kb_name`` is None."""
    return kb_name if kb_name is not None else get_settings().kb_name


def _resolve_ns(plugin_namespace: str | None) -> str:
    return instance_namespace(plugin_namespace)


# ---------------------------------------------------------------------------
# Synchronous writes (called by Celery ingestion adapters)
# ---------------------------------------------------------------------------


def register_document(
    document_id: str,
    *,
    name: str,
    source_type: str,
    pipeline: str,
    kb_name: str | None = None,
    plugin_namespace: str | None = None,
    source_uri: str | None = None,
    sha256: str | None = None,
    status: str = "pending",
    chunk_count: int = 0,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Register a document (INSERT ON CONFLICT update). Returns the document dict."""
    kb = _resolve_kb(kb_name)
    ns = _resolve_ns(plugin_namespace)
    extra_json = json.dumps(extra or {}, ensure_ascii=False)
    sync_execute(
        """
        INSERT INTO documents (document_id, name, source_type, source_uri, pipeline,
                               status, sha256, chunk_count, extra, updated_at, kb_name,
                               plugin_namespace)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, NOW(), %s, %s)
        ON CONFLICT (document_id) DO UPDATE SET
            name = EXCLUDED.name,
            source_type = EXCLUDED.source_type,
            source_uri = COALESCE(EXCLUDED.source_uri, documents.source_uri),
            pipeline = EXCLUDED.pipeline,
            status = EXCLUDED.status,
            sha256 = COALESCE(EXCLUDED.sha256, documents.sha256),
            chunk_count = EXCLUDED.chunk_count,
            extra = EXCLUDED.extra,
            kb_name = EXCLUDED.kb_name,
            plugin_namespace = EXCLUDED.plugin_namespace,
            updated_at = NOW()
        """,
        (
            document_id,
            name,
            source_type,
            source_uri,
            pipeline,
            status,
            sha256,
            chunk_count,
            extra_json,
            kb,
            ns,
        ),
    )
    row = get_document_sync(document_id)
    assert row is not None  # Just inserted, must exist.
    return row


def update_status(document_id: str, status: str, *, error: str | None = None) -> bool:
    """Update document status (indexing/ready/failed).

    Writes ``extra.error`` when ``error`` is non-empty.
    """
    if error is not None:
        sync_execute(
            "UPDATE documents SET status=%s, extra = extra || %s::jsonb, "
            "updated_at=NOW() WHERE document_id=%s",
            (status, json.dumps({"error": error}, ensure_ascii=False), document_id),
        )
    else:
        sync_execute(
            "UPDATE documents SET status=%s, updated_at=NOW() WHERE document_id=%s",
            (status, document_id),
        )
    return True


def update_chunk_count(document_id: str, chunk_count: int) -> bool:
    """Update the chunk count for a document."""
    sync_execute(
        "UPDATE documents SET chunk_count=%s, updated_at=NOW() WHERE document_id=%s",
        (chunk_count, document_id),
    )
    return True


def update_extra(document_id: str, patch: dict[str, Any]) -> bool:
    """Shallow-merge ``patch`` into the document's ``extra`` JSONB column."""
    sync_execute(
        "UPDATE documents SET extra = extra || %s::jsonb, updated_at=NOW() WHERE document_id=%s",
        (json.dumps(patch, ensure_ascii=False), document_id),
    )
    return True


def get_document_sync(
    document_id: str,
    *,
    plugin_namespace: str | None = None,
) -> dict[str, Any] | None:
    """Synchronously fetch a single document."""
    ns = _resolve_ns(plugin_namespace)
    row = sync_fetchone(
        """SELECT document_id, name, source_type, source_uri, pipeline, status,
                  sha256, chunk_count, extra, created_at, updated_at, kb_name
           FROM documents WHERE document_id=%s AND plugin_namespace=%s""",
        (document_id, ns),
    )
    return _row_to_dict(row)


# ---------------------------------------------------------------------------
# Asynchronous queries (called by FastAPI /documents endpoints)
# ---------------------------------------------------------------------------


async def get_document(
    document_id: str,
    *,
    plugin_namespace: str | None = None,
) -> dict[str, Any] | None:
    """Asynchronously fetch a single document."""
    ns = _resolve_ns(plugin_namespace)
    row = await async_fetchrow(
        """SELECT document_id, name, source_type, source_uri, pipeline, status,
                  sha256, chunk_count, extra, created_at, updated_at, kb_name
           FROM documents WHERE document_id=$1 AND plugin_namespace=$2""",
        document_id,
        ns,
    )
    return _row_to_dict(row)


def _document_filter_clause(
    *,
    q: str | None = None,
    source_type: str | None = None,
    pipeline: str | None = None,
    status: str | None = None,
    kb_name: str | None = None,
    plugin_namespace: str | None = None,
) -> tuple[str, list[Any]]:
    """Build the shared WHERE clause and params for document list/count queries."""
    where: list[str] = ["plugin_namespace = $1"]
    params: list[Any] = [_resolve_ns(plugin_namespace)]
    idx = 2
    if q:
        where.append(f"name ILIKE ${idx}")
        params.append(f"%{q}%")
        idx += 1
    if source_type:
        where.append(f"source_type=${idx}")
        params.append(source_type)
        idx += 1
    if pipeline:
        where.append(f"pipeline=${idx}")
        params.append(pipeline)
        idx += 1
    if status:
        where.append(f"status=${idx}")
        params.append(status)
        idx += 1
    if kb_name is not None:
        where.append(f"kb_name=${idx}")
        params.append(kb_name)
    clause = "WHERE " + " AND ".join(where)
    return clause, params


async def list_documents(
    *,
    q: str | None = None,
    source_type: str | None = None,
    pipeline: str | None = None,
    status: str | None = None,
    kb_name: str | None = None,
    plugin_namespace: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Asynchronously list documents with filtering and pagination."""
    clause, params = _document_filter_clause(
        q=q,
        source_type=source_type,
        pipeline=pipeline,
        status=status,
        kb_name=kb_name,
        plugin_namespace=plugin_namespace,
    )
    idx = len(params) + 1
    params.extend([limit, offset])
    rows = await async_fetch(
        f"""SELECT document_id, name, source_type, source_uri, pipeline, status,
                  sha256, chunk_count, extra, created_at, updated_at, kb_name
            FROM documents {clause}
            ORDER BY updated_at DESC LIMIT ${idx} OFFSET ${idx + 1}""",
        *params,
    )
    return [_row_to_dict(r) for r in rows]


async def count_documents(
    *,
    q: str | None = None,
    source_type: str | None = None,
    pipeline: str | None = None,
    status: str | None = None,
    kb_name: str | None = None,
    plugin_namespace: str | None = None,
) -> int:
    """Count documents matching the filters (used as pagination total)."""
    clause, params = _document_filter_clause(
        q=q,
        source_type=source_type,
        pipeline=pipeline,
        status=status,
        kb_name=kb_name,
        plugin_namespace=plugin_namespace,
    )
    row = await async_fetchrow(f"SELECT COUNT(*)::int AS cnt FROM documents {clause}", *params)
    return int(row["cnt"] or 0) if row else 0


async def delete_document(
    document_id: str,
    *,
    plugin_namespace: str | None = None,
) -> bool:
    """Delete a document registry row and recompute KB catalog (G31)."""
    ns = _resolve_ns(plugin_namespace)
    row = await async_fetchrow(
        "SELECT kb_name FROM documents WHERE document_id=$1 AND plugin_namespace=$2",
        document_id,
        ns,
    )
    if row is None:
        return False
    kb_name = row["kb_name"]
    async with acquire_async() as conn:
        result = await conn.execute(
            "DELETE FROM documents WHERE document_id=$1 AND plugin_namespace=$2",
            document_id,
            ns,
        )
    deleted = result.startswith("DELETE") and result != "DELETE 0"
    if deleted and kb_name:
        from eagle_rag.db.repositories.catalog import recompute_kb_collections

        recompute_kb_collections(kb_name, plugin_namespace=ns)
    return deleted


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    # asyncpg.Record supports items(); psycopg2 tuples need column-name mapping.
    if hasattr(row, "keys"):
        d = dict(row)
    else:
        cols = [
            "document_id",
            "name",
            "source_type",
            "source_uri",
            "pipeline",
            "status",
            "sha256",
            "chunk_count",
            "extra",
            "created_at",
            "updated_at",
            "kb_name",
        ]
        d = dict(zip(cols, row, strict=False))
    extra = d.get("extra")
    if isinstance(extra, str):
        try:
            d["extra"] = json.loads(extra)
        except (json.JSONDecodeError, TypeError):
            pass
    return d
