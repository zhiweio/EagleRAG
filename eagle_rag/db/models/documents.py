"""Document registry ORM model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Index, Integer, Text
from sqlmodel import Field, SQLModel

from eagle_rag.db.models.base import jsonb_default, timestamptz


class Document(SQLModel, table=True):
    """``documents`` table: ingested document metadata."""

    __tablename__ = "documents"
    __table_args__ = (
        Index("idx_documents_source_type", "source_type"),
        Index("idx_documents_pipeline", "pipeline"),
        Index("idx_documents_status", "status"),
        Index("idx_documents_sha256", "sha256"),
        Index("idx_documents_kb", "kb_name"),
    )

    document_id: str = Field(primary_key=True, sa_type=Text())
    name: str = Field(sa_type=Text())
    source_type: str = Field(sa_type=Text())
    source_uri: str | None = Field(default=None, sa_type=Text())
    pipeline: str = Field(sa_type=Text())
    status: str = Field(default="pending", sa_type=Text())
    sha256: str | None = Field(default=None, sa_type=Text())
    chunk_count: int = Field(default=0, sa_type=Integer())
    extra: dict = Field(default_factory=dict, sa_column=jsonb_default())
    created_at: datetime = Field(sa_column=timestamptz())
    updated_at: datetime = Field(sa_column=timestamptz())
    kb_name: str = Field(default="default", sa_type=Text())
