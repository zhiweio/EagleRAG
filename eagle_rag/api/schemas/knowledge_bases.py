"""Knowledge base API models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class KBCreate(BaseModel):
    kb_name: str = Field(description="Lowercase letters, digits, and underscores only")
    display_name: str
    description: str = ""
    theme: str = "blue"
    icon: str = "landmark"
    pdf_text_page_ratio: float = Field(default=0.2, ge=0.0, le=1.0)


class KBUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None
    theme: str | None = None
    icon: str | None = None
    pdf_text_page_ratio: float | None = Field(default=None, ge=0.0, le=1.0)


class KBItem(BaseModel):
    kb_name: str
    display_name: str
    description: str = ""
    theme: str = "blue"
    icon: str = "landmark"
    documents: int = 0
    graph_nodes: int = 0
    visual_slices: int = 0
    collections: list[str] = Field(default_factory=lambda: ["eagle_text", "eagle_visual"])
    active_ingestions: int = 0
    pdf_text_page_ratio: float = 0.2
    updated_at: str | None = None


class KBListResponse(BaseModel):
    items: list[KBItem]
    total: int


class KBKpi(BaseModel):
    documents: int
    graph_nodes: int
    visual_slices: int
    queries_7d: int


class KBDetailOut(KBItem):
    status: str = "online"
    kpi: KBKpi


class KBDeleteResponse(BaseModel):
    ok: bool = True
    kb_name: str
    deleted: dict[str, Any]


class RebuildResponse(BaseModel):
    job_id: str


class KBOverviewResponse(BaseModel):
    kb_count: int
    active_ingestions: int
    total_documents: int
    total_graph_nodes: int
    total_vectors: int


class FormatDistributionSegment(BaseModel):
    key: str
    label: str
    value: int
    color: str


class KBFormatDistributionResponse(BaseModel):
    segments: list[FormatDistributionSegment] = Field(default_factory=list)


class IngestionVolumePoint(BaseModel):
    date: str
    label: str
    value: int


class KBIngestionVolumeResponse(BaseModel):
    unit: str
    peak: int
    points: list[IngestionVolumePoint] = Field(default_factory=list)


class KBCollectionStats(BaseModel):
    name: str
    model: str
    dim: int
    index: str
    entities: int
    capacity_ratio: float


class KBCollectionsResponse(BaseModel):
    collections: list[KBCollectionStats] = Field(default_factory=list)


class KBFacetsResponse(BaseModel):
    source_type: list[str] = Field(default_factory=list)
    pipeline: list[str] = Field(default_factory=list)
    year: list[int] = Field(default_factory=list)
