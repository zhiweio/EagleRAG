"""Document keyword (tag) catalog ORM model.

Aggregates Knowhere-extracted chunk ``keywords`` into a per-document,
per-keyword catalog so the Q&A scope filter can list tags with hit counts /
knowledge-base coverage and resolve a selected tag back to its documents at
query time. Populated during the ``knowhere_parse`` ingest task; rows are
removed automatically when the owning document is deleted (FK cascade).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, ForeignKey, Index, Integer, Text
from sqlmodel import Field, SQLModel

from eagle_rag.db.models.base import timestamptz


class DocumentKeyword(SQLModel, table=True):
    """``document_keywords`` table: per-document keyword occurrence catalog."""

    __tablename__ = "document_keywords"
    __table_args__ = (
        Index("idx_document_keywords_kb_keyword", "kb_name", "keyword"),
        Index("idx_document_keywords_keyword", "keyword"),
    )

    document_id: str = Field(
        sa_column=Column(
            Text(),
            ForeignKey("documents.document_id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
    )
    keyword: str = Field(primary_key=True, sa_type=Text())
    kb_name: str = Field(default="default", sa_type=Text())
    node_count: int = Field(default=0, sa_type=Integer())
    created_at: datetime = Field(sa_column=timestamptz())
