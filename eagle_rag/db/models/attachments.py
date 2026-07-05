"""Attachment ORM model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Index, Integer, Text
from sqlmodel import Field, SQLModel

from eagle_rag.db.models.base import timestamptz


class Attachment(SQLModel, table=True):
    """``attachments`` table: session-scoped transient attachments."""

    __tablename__ = "attachments"
    __table_args__ = (Index("idx_attachments_expires", "expires_at"),)

    attachment_id: str = Field(primary_key=True, sa_type=Text())
    session_id: str | None = Field(default=None, sa_type=Text())
    file_name: str = Field(sa_type=Text())
    mime: str = Field(sa_type=Text())
    size_bytes: int = Field(default=0, sa_type=Integer())
    storage_path: str = Field(sa_type=Text())
    expires_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    created_at: datetime = Field(sa_column=timestamptz())
