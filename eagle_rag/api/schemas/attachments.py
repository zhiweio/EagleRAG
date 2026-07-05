"""Attachment API models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from eagle_rag.api.schemas._helpers import model_from_row
from eagle_rag.api.schemas.common import DeletedResponse


class AttachmentOut(BaseModel):
    attachment_id: str
    session_id: str | None = None
    file_name: str
    mime: str
    size_bytes: int = 0
    storage_path: str | None = Field(default=None, exclude=True)
    expires_at: str | None = None
    created_at: str | None = None

    @classmethod
    def from_store(cls, row: dict[str, Any]) -> AttachmentOut:
        return model_from_row(cls, row)


class AttachmentUploadResponse(BaseModel):
    attachment_id: str
    file_name: str
    mime: str
    size_bytes: int
    expires_at: str | None = None

    @classmethod
    def from_store(cls, row: dict[str, Any]) -> AttachmentUploadResponse:
        return model_from_row(cls, row)


__all__ = ["AttachmentOut", "AttachmentUploadResponse", "DeletedResponse"]
