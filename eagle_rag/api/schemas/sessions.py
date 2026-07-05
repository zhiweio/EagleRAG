"""Session API models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from eagle_rag.api.schemas._helpers import iso_datetime, model_from_row
from eagle_rag.api.schemas.common import PaginatedMeta
from eagle_rag.api.schemas.query import QuerySources, QueryStep


class SessionCreate(BaseModel):
    title: str | None = None
    kb_name: str | None = Field(
        default=None, description="Knowledge base identifier (multi-tenant)"
    )


class SessionSummary(BaseModel):
    session_id: str
    title: str | None = None
    kb_name: str | None = None
    scope_filter: dict[str, Any] | None = Field(
        default=None,
        description="Most recent scope selection (knowledge bases / documents / tags)",
    )
    created_at: str | None = None
    updated_at: str | None = None

    @classmethod
    def from_store(cls, row: dict[str, Any]) -> SessionSummary:
        return cls(
            session_id=row["session_id"],
            title=row.get("title"),
            kb_name=row.get("kb_name"),
            scope_filter=row.get("scope_filter"),
            created_at=iso_datetime(row.get("created_at")),
            updated_at=iso_datetime(row.get("updated_at")),
        )


class MessageOut(BaseModel):
    message_id: str
    session_id: str
    role: str
    content: str
    sources: QuerySources | None = None
    steps: list[QueryStep] | None = None
    attachments: list[str] | None = None
    kb_name: str | None = None
    created_at: str | None = None

    @classmethod
    def from_store(cls, row: dict[str, Any]) -> MessageOut:
        return model_from_row(cls, row)


class SessionListResponse(PaginatedMeta):
    items: list[SessionSummary]


class MessageListResponse(PaginatedMeta):
    items: list[MessageOut]
