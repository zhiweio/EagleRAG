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
) -> str:
    nid = str(uuid.uuid4())
    sync_execute(
        """
        INSERT INTO notifications (id, type, title, body, kb_name, job_id)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (nid, ntype, title, body, kb_name, job_id),
    )
    return nid


async def list_notifications(
    *,
    read: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    where = ""
    params: list[Any] = []
    if read is not None:
        where = "WHERE read = $1"
        params.append(read)
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


async def unread_count() -> int:
    row = await async_fetchrow("SELECT COUNT(*)::int AS cnt FROM notifications WHERE read = FALSE")
    return int(row["cnt"] or 0) if row else 0


async def mark_read(notification_id: str) -> bool:
    result = await async_execute(
        "UPDATE notifications SET read = TRUE WHERE id = $1",
        notification_id,
    )
    return result.endswith("1")


async def mark_all_read() -> int:
    result = await async_execute("UPDATE notifications SET read = TRUE WHERE read = FALSE")
    try:
        return int(result.split()[-1])
    except (ValueError, IndexError):
        return 0
