"""Ingest pipeline protocol and unified parse types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from llama_index.core.schema import TextNode

__all__ = [
    "IngestPipeline",
    "ParseContext",
    "ParseResult",
    "VisualChunk",
]


@dataclass(frozen=True)
class ParseContext:
    """Input to an ingest pipeline parse step."""

    job_id: str
    document_id: str
    file_path: str
    file_name: str
    kb_name: str
    source_type: str
    plugin_namespace: str
    source_uri: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class VisualChunk:
    """Visual chunk descriptor for ingest orchestration."""

    chunk_id: str
    image_bytes: bytes | None = None
    vector: list[float] | None = None
    image_path: str = ""
    chunk_type: str = "image"
    parent_section: str = ""
    content_summary: str = ""
    source_chunk_id: str = ""
    page: int | None = None
    position: str | None = None
    source_type: str | None = None
    year: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ParseResult:
    """Unified parse output (Knowhere SDK result or PixelRAG tile list)."""

    raw: Any
    pipeline: str
    chunk_count: int = 0


class IngestPipeline(Protocol):
    """Registered ingest pipeline (parse, normalize, Celery dispatch metadata)."""

    name: str

    def parse(self, ctx: ParseContext) -> ParseResult: ...

    def to_nodes(
        self, parse_result: ParseResult, ctx: ParseContext
    ) -> list[TextNode | dict[str, Any]]: ...

    def celery_task_name(self) -> str: ...

    def queue(self) -> str: ...
