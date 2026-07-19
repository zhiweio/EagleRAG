"""Tag (keyword) catalog store (PostgreSQL).

Backs the Q&A scope filter's *tag* dimension. Tags reuse the ``keywords`` that
Knowhere extracts per text chunk; this module aggregates them into the
``document_keywords`` table (per-document, per-keyword occurrence counts) so the
UI can list tags with hit counts / KB coverage and retrieval can resolve a
selected tag back to its documents.

- Sync writes (``upsert_document_keywords`` / ``delete_document_keywords``) are
  called from Celery ingest tasks (psycopg2).
- ``list_tags`` is async, called from the FastAPI ``/tags`` route (asyncpg).
- ``resolve_tags_to_document_ids`` is sync, called from the retrieval engine
  which itself runs in a worker thread (``asyncio.to_thread``).
"""

from __future__ import annotations

from typing import Any

from eagle_rag.db import async_fetch, get_sync_conn, sync_execute
from eagle_rag.db.repositories.base import instance_namespace

__all__ = [
    "upsert_document_keywords",
    "delete_document_keywords",
    "list_tags",
    "resolve_tags_to_document_ids",
]


def delete_document_keywords(
    document_id: str,
    *,
    plugin_namespace: str | None = None,
) -> int:
    """Remove all keyword rows for a document (idempotent re-ingest)."""
    ns = instance_namespace(plugin_namespace)
    return sync_execute(
        "DELETE FROM document_keywords WHERE document_id = %s AND plugin_namespace = %s",
        (document_id, ns),
    )


def upsert_document_keywords(
    document_id: str,
    kb_name: str,
    counts: dict[str, int],
    *,
    plugin_namespace: str | None = None,
) -> int:
    """Replace a document's keyword rows with ``{keyword: node_count}``.

    Deletes existing rows for the document first (so re-ingest stays
    idempotent), then bulk-inserts the new keyword occurrences. Empty keywords
    are skipped. Returns the number of inserted rows.
    """
    from psycopg2.extras import execute_values

    ns = instance_namespace(plugin_namespace)
    cleaned = {kw.strip(): int(n) for kw, n in counts.items() if kw and kw.strip() and n > 0}
    with get_sync_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM document_keywords WHERE document_id = %s AND plugin_namespace = %s",
                (document_id, ns),
            )
            if not cleaned:
                return 0
            execute_values(
                cur,
                "INSERT INTO document_keywords "
                "(document_id, keyword, kb_name, node_count, plugin_namespace) VALUES %s "
                "ON CONFLICT (document_id, keyword) DO UPDATE SET "
                "kb_name = EXCLUDED.kb_name, node_count = EXCLUDED.node_count, "
                "plugin_namespace = EXCLUDED.plugin_namespace",
                [(document_id, kw, kb_name, n, ns) for kw, n in cleaned.items()],
            )
            return len(cleaned)


async def list_tags(
    *,
    kb_names: list[str] | None = None,
    q: str | None = None,
    limit: int = 50,
    plugin_namespace: str | None = None,
) -> list[dict[str, Any]]:
    """Aggregate the catalog into tag suggestions ordered by hit count.

    Returns ``[{tag, node_count, kb_count, doc_count}]`` where ``node_count`` is
    the total chunk occurrences of the keyword, ``kb_count`` the number of
    distinct knowledge bases it appears in, and ``doc_count`` the number of
    distinct documents. ``kb_names`` narrows to the given knowledge bases; ``q``
    is a case-insensitive substring match on the keyword.
    """
    ns = instance_namespace(plugin_namespace)
    where: list[str] = ["plugin_namespace = $1"]
    params: list[Any] = [ns]
    idx = 2
    if kb_names:
        where.append(f"kb_name = ANY(${idx}::text[])")
        params.append(kb_names)
        idx += 1
    if q:
        where.append(f"keyword ILIKE ${idx}")
        params.append(f"%{q}%")
        idx += 1
    clause = "WHERE " + " AND ".join(where)
    params.append(limit)
    rows = await async_fetch(
        f"""
        SELECT keyword AS tag,
               SUM(node_count)::int AS node_count,
               COUNT(DISTINCT kb_name)::int AS kb_count,
               COUNT(DISTINCT document_id)::int AS doc_count
        FROM document_keywords
        {clause}
        GROUP BY keyword
        ORDER BY node_count DESC, doc_count DESC
        LIMIT ${idx}
        """,
        *params,
    )
    return [dict(r) for r in rows]


def resolve_tags_to_document_ids(
    tags: list[str],
    *,
    kb_names: list[str] | None = None,
    cap: int = 500,
    plugin_namespace: str | None = None,
) -> list[str]:
    """Resolve selected tags to the set of documents that contain them.

    Used at query time to fold the tag dimension into the union document scope.
    ``kb_names`` optionally narrows the resolution; ``cap`` bounds the returned
    list so the downstream Milvus ``document_id in [...]`` predicate stays sane.
    """
    if not tags:
        return []
    ns = instance_namespace(plugin_namespace)
    where = ["keyword = ANY(%s)", "plugin_namespace = %s"]
    params: list[Any] = [list(tags), ns]
    if kb_names:
        where.append("kb_name = ANY(%s)")
        params.append(list(kb_names))
    params.append(cap)
    with get_sync_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT DISTINCT document_id
                FROM document_keywords
                WHERE {" AND ".join(where)}
                LIMIT %s
                """,
                tuple(params),
            )
            return [row[0] for row in cur.fetchall()]
