"""Notifications repository (G9/G11)."""

from __future__ import annotations

from typing import Any

from eagle_rag.notifications import store as notification_store

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
    return notification_store.create_notification_sync(
        ntype=ntype,
        title=title,
        body=body,
        kb_name=kb_name,
        job_id=job_id,
        plugin_namespace=plugin_namespace,
    )


async def list_notifications(
    *,
    read: bool | None = None,
    limit: int = 50,
    offset: int = 0,
    plugin_namespace: str | None = None,
) -> list[dict[str, Any]]:
    return await notification_store.list_notifications(
        read=read,
        limit=limit,
        offset=offset,
        plugin_namespace=plugin_namespace,
    )


async def unread_count(*, plugin_namespace: str | None = None) -> int:
    return await notification_store.unread_count(plugin_namespace=plugin_namespace)


async def mark_read(notification_id: str, *, plugin_namespace: str | None = None) -> bool:
    return await notification_store.mark_read(
        notification_id,
        plugin_namespace=plugin_namespace,
    )


async def mark_all_read(*, plugin_namespace: str | None = None) -> int:
    return await notification_store.mark_all_read(plugin_namespace=plugin_namespace)
