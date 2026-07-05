"""Notification ORM model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Column, Index, Text, text
from sqlmodel import Field, SQLModel

from eagle_rag.db.models.base import timestamptz


class Notification(SQLModel, table=True):
    """``notifications`` table: task event notifications."""

    __tablename__ = "notifications"
    __table_args__ = (Index("idx_notifications_read", "read", "created_at"),)

    id: str = Field(primary_key=True, sa_type=Text())
    type: str = Field(sa_column=Column("type", Text(), nullable=False))
    title: str = Field(sa_type=Text())
    body: str = Field(default="", sa_type=Text())
    kb_name: str | None = Field(default=None, sa_type=Text())
    job_id: str | None = Field(default=None, sa_type=Text())
    read: bool = Field(
        default=False,
        sa_column=Column("read", Boolean(), nullable=False, server_default=text("false")),
    )
    created_at: datetime = Field(sa_column=timestamptz())
