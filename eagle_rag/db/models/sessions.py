"""Session and message ORM models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from eagle_rag.db.models.base import timestamptz


class Session(SQLModel, table=True):
    """``sessions`` table: Q&A conversations."""

    __tablename__ = "sessions"
    __table_args__ = (Index("idx_sessions_kb", "kb_name"),)

    session_id: str = Field(primary_key=True, sa_type=Text())
    title: str | None = Field(default=None, sa_type=Text())
    created_at: datetime = Field(sa_column=timestamptz())
    updated_at: datetime = Field(sa_column=timestamptz())
    kb_name: str = Field(default="default", sa_type=Text())
    scope_filter: dict | None = Field(default=None, sa_column=Column(JSONB, nullable=True))


class Message(SQLModel, table=True):
    """``messages`` table: conversation messages."""

    __tablename__ = "messages"
    __table_args__ = (
        Index("idx_messages_session", "session_id", "created_at"),
        Index("idx_messages_kb", "kb_name"),
    )

    message_id: str = Field(primary_key=True, sa_type=Text())
    session_id: str = Field(
        sa_column=Column(
            Text(),
            ForeignKey("sessions.session_id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    role: str = Field(sa_type=Text())
    content: str = Field(sa_type=Text())
    sources: dict | list | None = Field(default=None, sa_column=Column(JSONB))
    steps: dict | list | None = Field(default=None, sa_column=Column(JSONB))
    attachments: dict | list | None = Field(default=None, sa_column=Column(JSONB))
    created_at: datetime = Field(sa_column=timestamptz())
    kb_name: str = Field(default="default", sa_type=Text())
