"""Content classifier protocols and decision types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    pass

__all__ = [
    "ClassificationContext",
    "ClassificationDecision",
    "ContentClassifier",
]


@dataclass(frozen=True)
class ClassificationDecision:
    """Standard output of a content classifier."""

    category: str
    target_collection: str
    target_encoder: str
    chunk_type: str
    confidence: float = 1.0
    fallback_used: bool = False
    exclusive_group: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class ClassificationContext:
    """Input to chunk/asset-level classifiers."""

    content: str | bytes
    modality: str
    document_id: str
    kb_name: str
    plugin_namespace: str
    parent_section: str = ""
    source_chunk_id: str = ""
    file_ext: str = ""
    extra: dict = field(default_factory=dict)


class ContentClassifier(Protocol):
    """Chunk/asset-level classifier: decided or abstain (None)."""

    def classify(self, ctx: ClassificationContext) -> ClassificationDecision | None: ...
