"""Task event notification store."""

from __future__ import annotations

import uuid
from typing import Any

from eagle_rag.db import async_execute, async_fetch, async_fetchrow, sync_execute

__all__ = [
    "create_notification_sync",
    "list_notifications",
    "mark_read",
    "mark_all_read",
    "unread_count",
]


def create_notification_sync(
    *,
    ntype: str,
    title: str,
    body: str = "",
    kb_name: str | None = None,
    job_id: str | None = None,
    plugin_namespace: str | None = None,
) -> str:
    from eagle_rag.db.repositories.base import instance_namespace

    ns = instance_namespace(plugin_namespace)
    nid = str(uuid.uuid4())
    sync_execute(
        """
        INSERT INTO notifications (id, type, title, body, kb_name, job_id, plugin_namespace)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (nid, ntype, title, body, kb_name, job_id, ns),
    )
    return nid


async def list_notifications(
    *,
    read: bool | None = None,
    limit: int = 50,
    offset: int = 0,
    plugin_namespace: str | None = None,
) -> list[dict[str, Any]]:
    from eagle_rag.db.repositories.base import instance_namespace

    ns = instance_namespace(plugin_namespace)
    where_parts = ["plugin_namespace = $1"]
    params: list[Any] = [ns]
    if read is not None:
        where_parts.append(f"read = ${len(params) + 1}")
        params.append(read)
    where = "WHERE " + " AND ".join(where_parts)
    params.extend([limit, offset])
    lim_idx = len(params) - 1
    rows = await async_fetch(
        f"""
        SELECT id, type, title, body, kb_name, job_id, read, created_at
        FROM notifications {where}
        ORDER BY created_at DESC
        LIMIT ${lim_idx} OFFSET ${lim_idx + 1}
        """,
        *params,
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        if d.get("created_at") is not None and hasattr(d["created_at"], "isoformat"):
            d["created_at"] = d["created_at"].isoformat()
        out.append(d)
    return out


async def unread_count(*, plugin_namespace: str | None = None) -> int:
    from eagle_rag.db.repositories.base import instance_namespace

    ns = instance_namespace(plugin_namespace)
    row = await async_fetchrow(
        """
        SELECT COUNT(*)::int AS cnt
        FROM notifications
        WHERE read = FALSE AND plugin_namespace = $1
        """,
        ns,
    )
    return int(row["cnt"] or 0) if row else 0


async def mark_read(notification_id: str, *, plugin_namespace: str | None = None) -> bool:
    from eagle_rag.db.repositories.base import instance_namespace

    ns = instance_namespace(plugin_namespace)
    result = await async_execute(
        "UPDATE notifications SET read = TRUE WHERE id = $1 AND plugin_namespace = $2",
        notification_id,
        ns,
    )
    return result.endswith("1")


async def mark_all_read(*, plugin_namespace: str | None = None) -> int:
    from eagle_rag.db.repositories.base import instance_namespace

    ns = instance_namespace(plugin_namespace)
    result = await async_execute(
        "UPDATE notifications SET read = TRUE WHERE read = FALSE AND plugin_namespace = $1",
        ns,
    )
    try:
        return int(result.split()[-1])
    except (ValueError, IndexError):
        return 0
