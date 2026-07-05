"""Document and image API models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from eagle_rag.api.schemas._helpers import model_from_row
from eagle_rag.api.schemas.common import PaginatedMeta


class DocumentOut(BaseModel):
    document_id: str
    name: str
    source_type: str
    source_uri: str | None = None
    pipeline: str
    status: str
    sha256: str | None = None
    chunk_count: int = 0
    extra: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None
    kb_name: str = "default"

    @classmethod
    def from_store(cls, row: dict[str, Any]) -> DocumentOut:
        return model_from_row(cls, row)


class DocumentListResponse(PaginatedMeta):
    items: list[DocumentOut]
    total: int = Field(description="Total number of matching documents")


class ImageMetaOut(BaseModel):
    image_id: str
    document_id: str
    page: int | None = None
    position: str | None = None
    object_key: str | None = None
    local_path: str | None = None
    width: int | None = None
    height: int | None = None
    created_at: str | None = None
    kb_name: str = "default"

    @classmethod
    def from_store(cls, row: dict[str, Any]) -> ImageMetaOut:
        return model_from_row(cls, row)


class DocumentStructureNode(BaseModel):
    """A node in a document's parsed semantic tree (Knowhere ``doc_nav`` section)."""

    path: str
    level: int | None = None
    title: str | None = None
    summary: str | None = None
    chunk_count: int | None = None
    children: list[DocumentStructureNode] = Field(default_factory=list)


class DocumentVisualRef(BaseModel):
    """A visual tile anchored to the document structure via ``parent_section``."""

    image_id: str | None = None
    page: int | None = None
    position: str | None = None
    chunk_type: str | None = None
    parent_section: str | None = None
    content_summary: str | None = None
    source_chunk_id: str | None = None


class DocumentStructureOut(BaseModel):
    """A document's parsed semantic structure (section tree + visual anchors)."""

    document_id: str
    name: str | None = None
    source_type: str | None = None
    pipeline: str | None = None
    kb_name: str = "default"
    status: str | None = None
    source: str = Field(default="empty", description="doc_nav | reconstructed | empty")
    sections: list[DocumentStructureNode] = Field(default_factory=list)
    visuals: list[DocumentVisualRef] = Field(default_factory=list)
    visual_count: int = 0
    has_source_file: bool = False


DocumentStructureNode.model_rebuild()
