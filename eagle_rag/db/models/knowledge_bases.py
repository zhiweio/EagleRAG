"""Knowledge base metadata ORM model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Float, Index, Text
from sqlmodel import Field, SQLModel

from eagle_rag.db.models.base import jsonb_default, timestamptz


class KnowledgeBase(SQLModel, table=True):
    """``knowledge_bases`` table: multi-tenant knowledge base registry."""

    __tablename__ = "knowledge_bases"
    __table_args__ = (
        Index("idx_knowledge_bases_updated", "updated_at"),
        Index("idx_knowledge_bases_namespace", "plugin_namespace"),
    )

    kb_name: str = Field(primary_key=True, sa_type=Text())
    plugin_namespace: str = Field(primary_key=True, default="core", sa_type=Text())
    display_name: str = Field(sa_type=Text())
    description: str = Field(default="", sa_type=Text())
    theme: str = Field(default="blue", sa_type=Text())
    icon: str = Field(default="database", sa_type=Text())
    pdf_text_page_ratio: float = Field(default=0.2, sa_type=Float())
    collections_used: list = Field(default_factory=list, sa_column=jsonb_default("'[]'::jsonb"))
    created_at: datetime = Field(sa_column=timestamptz())
    updated_at: datetime = Field(sa_column=timestamptz())
