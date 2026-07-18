"""Task audit ORM model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Index, Integer, Text
from sqlmodel import Field, SQLModel

from eagle_rag.db.models.base import jsonb_default, timestamptz


class TaskAudit(SQLModel, table=True):
    """``task_audit`` table: Celery ingestion task audit trail."""

    __tablename__ = "task_audit"
    __table_args__ = (
        Index("idx_task_audit_status", "status"),
        Index("idx_task_audit_document", "document_id"),
        Index("idx_task_audit_kb", "kb_name"),
        Index("idx_task_audit_namespace", "plugin_namespace"),
    )

    job_id: str = Field(primary_key=True, sa_type=Text())
    document_id: str | None = Field(default=None, sa_type=Text())
    name: str | None = Field(default=None, sa_type=Text())
    source_uri: str | None = Field(default=None, sa_type=Text())
    pipeline: str = Field(sa_type=Text())
    status: str = Field(sa_type=Text())
    progress: int = Field(default=0, sa_type=Integer())
    current: int | None = Field(default=None, sa_type=Integer())
    total: int | None = Field(default=None, sa_type=Integer())
    error: str | None = Field(default=None, sa_type=Text())
    logs: list = Field(default_factory=list, sa_column=jsonb_default("'[]'::jsonb"))
    created_at: datetime = Field(sa_column=timestamptz())
    updated_at: datetime = Field(sa_column=timestamptz())
    kb_name: str = Field(default="default", sa_type=Text())
    plugin_namespace: str = Field(default="core", sa_type=Text())
