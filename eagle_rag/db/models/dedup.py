"""Document deduplication ORM model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Index, Text
from sqlmodel import Field, SQLModel

from eagle_rag.db.models.base import timestamptz


class DocumentDedup(SQLModel, table=True):
    """``document_dedup`` table: deduplicates on ``(sha256, kb_name, plugin_namespace)``."""

    __tablename__ = "document_dedup"
    __table_args__ = (
        Index("idx_dedup_document", "document_id"),
        Index("idx_document_dedup_kb", "kb_name"),
        Index("idx_document_dedup_namespace", "plugin_namespace"),
    )

    sha256: str = Field(primary_key=True, sa_type=Text())
    kb_name: str = Field(primary_key=True, default="default", sa_type=Text())
    plugin_namespace: str = Field(primary_key=True, default="core", sa_type=Text())
    document_id: str = Field(sa_type=Text())
    object_key: str | None = Field(default=None, sa_type=Text())
    source_name: str | None = Field(default=None, sa_type=Text())
    created_at: datetime = Field(sa_column=timestamptz())
