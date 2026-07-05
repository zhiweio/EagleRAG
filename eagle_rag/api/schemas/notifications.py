"""Notification API models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from eagle_rag.api.schemas._helpers import model_from_row
from eagle_rag.api.schemas.common import PaginatedMeta


class NotificationOut(BaseModel):
    id: str
    type: str
    title: str
    body: str = ""
    kb_name: str | None = None
    job_id: str | None = None
    read: bool = False
    created_at: str | None = None

    @classmethod
    def from_store(cls, row: dict[str, Any]) -> NotificationOut:
        return model_from_row(cls, row)


class NotificationListResponse(PaginatedMeta):
    items: list[NotificationOut]
    unread_count: int


class NotificationReadResponse(BaseModel):
    read: bool = True


class NotificationReadAllResponse(BaseModel):
    updated: int
