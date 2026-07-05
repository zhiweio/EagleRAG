"""Tag (keyword) catalog API models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TagOut(BaseModel):
    tag: str = Field(description="Tag (keyword)")
    node_count: int = Field(
        default=0, description="Matching node count (total chunks containing the keyword)"
    )
    kb_count: int = Field(default=0, description="Number of knowledge bases covered")
    doc_count: int = Field(default=0, description="Number of documents covered")


class TagListResponse(BaseModel):
    items: list[TagOut]
    total: int = Field(description="Number of tags returned")
