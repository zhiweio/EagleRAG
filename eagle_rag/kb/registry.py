"""KB metadata registry backed by PostgreSQL.

Tracks per-KB metadata such as display name, topic, icon, and PDF probe threshold.
``kb_name`` is immutable after creation and serves as the Milvus scalar filter key and
part of the dedup composite primary key.
"""

from __future__ import annotations

import re
from typing import Any

from eagle_rag.db import async_execute, async_fetch, async_fetchrow
from eagle_rag.db.repositories.base import instance_namespace

__all__ = [
    "KB_NAME_PATTERN",
    "create_kb",
    "get_kb",
    "get_kb_sync",
    "list_kbs",
    "update_kb",
    "delete_kb",
    "kb_exists",
    "kb_exists_sync",
    "ensure_kb_exists",
    "get_pdf_ratio_sync",
]

KB_NAME_PATTERN = re.compile(r"^[a-z0-9_]+$")

_SELECT = """
SELECT kb_name, display_name, description, theme, icon,
       pdf_text_page_ratio, created_at, updated_at, collections_used
FROM knowledge_bases
"""


def _ns(plugin_namespace: str | None = None) -> str:
    return instance_namespace(plugin_namespace)


def _row_to_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    if hasattr(row, "keys"):
        d = dict(row)
    else:
        cols = [
            "kb_name",
            "display_name",
            "description",
            "theme",
            "icon",
            "pdf_text_page_ratio",
            "created_at",
            "updated_at",
            "collections_used",
        ]
        d = dict(zip(cols, row, strict=False))
    if d.get("created_at") is not None and hasattr(d["created_at"], "isoformat"):
        d["created_at"] = d["created_at"].isoformat()
    if d.get("updated_at") is not None and hasattr(d["updated_at"], "isoformat"):
        d["updated_at"] = d["updated_at"].isoformat()
    return d


def _validate_kb_name(kb_name: str) -> None:
    if not KB_NAME_PATTERN.match(kb_name):
        raise ValueError(
            f"invalid kb_name format: {kb_name!r}; only lowercase letters, digits, and underscore"
        )


async def create_kb(
    *,
    kb_name: str,
    display_name: str,
    description: str = "",
    theme: str = "blue",
    icon: str = "database",
    pdf_text_page_ratio: float = 0.2,
    plugin_namespace: str | None = None,
) -> dict[str, Any]:
    """Create a KB metadata record."""
    _validate_kb_name(kb_name)
    ns = _ns(plugin_namespace)
    ratio = max(0.0, min(1.0, float(pdf_text_page_ratio)))
    await async_execute(
        """
        INSERT INTO knowledge_bases
          (kb_name, display_name, description, theme, icon, pdf_text_page_ratio, plugin_namespace)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        """,
        kb_name,
        display_name,
        description,
        theme,
        icon,
        ratio,
        ns,
    )
    row = await get_kb(kb_name, plugin_namespace=ns)
    assert row is not None
    return row


async def get_kb(kb_name: str, *, plugin_namespace: str | None = None) -> dict[str, Any] | None:
    """Fetch a single KB record by kb_name."""
    ns = _ns(plugin_namespace)
    row = await async_fetchrow(
        f"{_SELECT} WHERE kb_name = $1 AND plugin_namespace = $2",
        kb_name,
        ns,
    )
    return _row_to_dict(row)


def get_kb_sync(kb_name: str, *, plugin_namespace: str | None = None) -> dict[str, Any] | None:
    """Synchronous fetch (used by Celery / ingest validation)."""
    from eagle_rag.db import sync_fetchone

    ns = _ns(plugin_namespace)
    row = sync_fetchone(
        f"{_SELECT} WHERE kb_name = %s AND plugin_namespace = %s",
        (kb_name, ns),
    )
    return _row_to_dict(row)


async def list_kbs(
    *,
    query: str | None = None,
    sort: str = "recent",
    limit: int = 50,
    offset: int = 0,
    plugin_namespace: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """List KBs with pagination. sort: recent | name | size (size approximated by updated_at)."""
    ns = _ns(plugin_namespace)
    where: list[str] = [f"plugin_namespace = ${1}"]
    params: list[Any] = [ns]
    idx = 2
    if query:
        where.append(f"(kb_name ILIKE ${idx} OR display_name ILIKE ${idx})")
        params.append(f"%{query}%")
        idx += 1
    clause = "WHERE " + " AND ".join(where)

    if sort == "name":
        order = "display_name ASC"
    elif sort == "size":
        order = "updated_at DESC"
    else:
        order = "updated_at DESC"

    count_row = await async_fetchrow(
        f"SELECT COUNT(*) AS cnt FROM knowledge_bases {clause}",
        *params,
    )
    total = int(count_row["cnt"]) if count_row else 0

    params.extend([limit, offset])
    rows = await async_fetch(
        f"{_SELECT} {clause} ORDER BY {order} LIMIT ${idx} OFFSET ${idx + 1}",
        *params,
    )
    return [_row_to_dict(r) for r in rows if _row_to_dict(r)], total


async def update_kb(
    kb_name: str,
    *,
    display_name: str | None = None,
    description: str | None = None,
    theme: str | None = None,
    icon: str | None = None,
    pdf_text_page_ratio: float | None = None,
    plugin_namespace: str | None = None,
) -> dict[str, Any] | None:
    """Update mutable fields (kb_name is immutable)."""
    ns = _ns(plugin_namespace)
    sets: list[str] = ["updated_at = NOW()"]
    params: list[Any] = []
    idx = 1
    if display_name is not None:
        sets.append(f"display_name = ${idx}")
        params.append(display_name)
        idx += 1
    if description is not None:
        sets.append(f"description = ${idx}")
        params.append(description)
        idx += 1
    if theme is not None:
        sets.append(f"theme = ${idx}")
        params.append(theme)
        idx += 1
    if icon is not None:
        sets.append(f"icon = ${idx}")
        params.append(icon)
        idx += 1
    if pdf_text_page_ratio is not None:
        sets.append(f"pdf_text_page_ratio = ${idx}")
        params.append(max(0.0, min(1.0, float(pdf_text_page_ratio))))
        idx += 1
    if len(sets) == 1:
        return await get_kb(kb_name, plugin_namespace=ns)
    params.extend([kb_name, ns])
    await async_execute(
        f"UPDATE knowledge_bases SET {', '.join(sets)} "
        f"WHERE kb_name = ${idx} AND plugin_namespace = ${idx + 1}",
        *params,
    )
    return await get_kb(kb_name, plugin_namespace=ns)


async def delete_kb(kb_name: str, *, plugin_namespace: str | None = None) -> bool:
    """Delete the registry row (does not cascade data cleanup; see lifecycle)."""
    ns = _ns(plugin_namespace)
    result = await async_execute(
        "DELETE FROM knowledge_bases WHERE kb_name = $1 AND plugin_namespace = $2",
        kb_name,
        ns,
    )
    return result.endswith("1")


async def kb_exists(kb_name: str, *, plugin_namespace: str | None = None) -> bool:
    """Asynchronously check whether kb_name is registered."""
    ns = _ns(plugin_namespace)
    row = await async_fetchrow(
        "SELECT 1 FROM knowledge_bases WHERE kb_name = $1 AND plugin_namespace = $2",
        kb_name,
        ns,
    )
    return row is not None


def kb_exists_sync(kb_name: str, *, plugin_namespace: str | None = None) -> bool:
    """Synchronously check whether kb_name is registered."""
    from eagle_rag.db import sync_fetchone

    ns = _ns(plugin_namespace)
    row = sync_fetchone(
        "SELECT 1 FROM knowledge_bases WHERE kb_name = %s AND plugin_namespace = %s",
        (kb_name, ns),
    )
    return row is not None


def get_pdf_ratio_sync(kb_name: str | None) -> float | None:
    """Read the KB-level PDF probe threshold; returns None if unregistered."""
    if not kb_name:
        return None
    row = get_kb_sync(kb_name)
    if row is None:
        return None
    return float(row.get("pdf_text_page_ratio", 0.2))


async def ensure_kb_exists(kb_name: str, *, plugin_namespace: str | None = None) -> None:
    """Raise ValueError if unregistered (API layer maps to 404)."""
    if not await kb_exists(kb_name, plugin_namespace=plugin_namespace):
        raise ValueError(f"knowledge base not registered: {kb_name}")
