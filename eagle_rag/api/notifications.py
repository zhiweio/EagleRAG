"""Notifications API."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from eagle_rag.api.schemas.notifications import (
    NotificationListResponse,
    NotificationOut,
    NotificationReadAllResponse,
    NotificationReadResponse,
)
from eagle_rag.notifications import store as notif_store

router = APIRouter(tags=["notifications"])


@router.get("/notifications", response_model=NotificationListResponse)
async def list_notifications_api(
    read: bool | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> NotificationListResponse:
    items = await notif_store.list_notifications(read=read, limit=limit, offset=offset)
    unread = await notif_store.unread_count()
    return NotificationListResponse(
        items=[NotificationOut.from_store(i) for i in items],
        unread_count=unread,
        limit=limit,
        offset=offset,
    )


@router.patch("/notifications/{notification_id}", response_model=NotificationReadResponse)
async def patch_notification(notification_id: str) -> NotificationReadResponse:
    ok = await notif_store.mark_read(notification_id)
    if not ok:
        raise HTTPException(status_code=404, detail="notification not found")
    return NotificationReadResponse()


@router.post("/notifications/read-all", response_model=NotificationReadAllResponse)
async def read_all_notifications() -> NotificationReadAllResponse:
    count = await notif_store.mark_all_read()
    return NotificationReadAllResponse(updated=count)
