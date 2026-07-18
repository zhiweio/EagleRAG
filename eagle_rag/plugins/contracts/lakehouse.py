"""Lakehouse metadata connector ABC for user-implemented lakehouse exporters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field

__all__ = [
    "ColumnDescriptor",
    "LakehouseMetadataConnector",
    "TableDescriptor",
    "ViewDescriptor",
]


@dataclass(frozen=True)
class ColumnDescriptor:
    """A single table column."""

    name: str
    type: str
    comment: str | None = None
    nullable: bool | None = None


@dataclass(frozen=True)
class TableDescriptor:
    """Structured table/column metadata."""

    table: str
    columns: list[ColumnDescriptor]
    database: str | None = None
    schema: str | None = None
    comment: str | None = None


@dataclass(frozen=True)
class ViewDescriptor:
    """A view definition and optional dependency list."""

    name: str
    sql: str
    database: str | None = None
    schema: str | None = None
    dependencies: list[str] = field(default_factory=list)
    comment: str | None = None


class LakehouseMetadataConnector(ABC):
    """User-implemented connector: pulls metadata from a lakehouse.

    EagleRAG never connects to the lakehouse directly. Connectors export DDL,
    schema descriptors, and views as files that are ingested via ``/ingest``.
    """

    @abstractmethod
    def extract_ddl(self) -> Iterator[str]:
        """Yield raw DDL statements (``CREATE TABLE`` / ``CREATE VIEW`` / ...)."""

    @abstractmethod
    def extract_schema(self) -> list[TableDescriptor]:
        """Return table/column descriptors (db/schema/table/columns/types/comments)."""

    @abstractmethod
    def extract_views(self) -> list[ViewDescriptor]:
        """Return view definitions (name, sql, dependencies)."""

    def extract_lineage(self) -> list[dict[str, object]]:
        """Optional lineage edges; override when the source exposes them."""
        return []

    def extract_partitions(self) -> list[dict[str, object]]:
        """Optional partition metadata; override when available."""
        return []

    def extract_stats(self) -> list[dict[str, object]]:
        """Optional table/column stats; override when available."""
        return []
