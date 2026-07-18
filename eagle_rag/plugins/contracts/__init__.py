"""Lakehouse metadata connector contracts (user-implemented)."""

from eagle_rag.plugins.contracts.lakehouse import (
    ColumnDescriptor,
    LakehouseMetadataConnector,
    TableDescriptor,
    ViewDescriptor,
)

__all__ = [
    "ColumnDescriptor",
    "LakehouseMetadataConnector",
    "TableDescriptor",
    "ViewDescriptor",
]
