"""Query routing types and classifier protocol (single source of truth)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

__all__ = [
    "CollectionQueryPlan",
    "QueryRouteDecision",
    "QueryRouteClassifier",
]


@dataclass(frozen=True)
class CollectionQueryPlan:
    """One collection to query with a specific encoder."""

    collection: str
    encoder: str
    top_k: int = 5


@dataclass(frozen=True)
class QueryRouteDecision:
    """Multi-collection query plan."""

    plans: tuple[CollectionQueryPlan, ...]


class QueryRouteClassifier(Protocol):
    """Decide which collections a query should hit."""

    def route(
        self,
        query: str,
        plugin_namespace: str,
        *,
        has_image: bool = False,
        route_mode: str = "text",
        scope_document_ids: tuple[str, ...] | None = None,
        scope_kb_names: tuple[str, ...] | None = None,
        scope_tags: tuple[str, ...] | None = None,
    ) -> QueryRouteDecision | None: ...
