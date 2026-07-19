"""Image tile ORM model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Index, Integer, Text
from sqlmodel import Field, SQLModel

from eagle_rag.db.models.base import timestamptz


class Image(SQLModel, table=True):
    """``images`` table: tile PNG metadata."""

    __tablename__ = "images"
    __table_args__ = (
        Index("idx_images_document", "document_id", "page"),
        Index("idx_images_kb", "kb_name"),
        Index("idx_images_namespace", "plugin_namespace"),
    )

    image_id: str = Field(primary_key=True, sa_type=Text())
    document_id: str = Field(sa_type=Text())
    page: int | None = Field(default=None, sa_type=Integer())
    position: str | None = Field(default=None, sa_type=Text())
    object_key: str | None = Field(default=None, sa_type=Text())
    local_path: str | None = Field(default=None, sa_type=Text())
    width: int | None = Field(default=None, sa_type=Integer())
    height: int | None = Field(default=None, sa_type=Integer())
    created_at: datetime = Field(sa_column=timestamptz())
    kb_name: str = Field(default="default", sa_type=Text())
    plugin_namespace: str = Field(default="core", sa_type=Text())
