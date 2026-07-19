"""Repository package (G9)."""

from eagle_rag.db.repositories.base import instance_namespace
from eagle_rag.db.repositories.catalog import (
    clear_kb_collections,
    get_document_collections,
    get_kb_collections,
    merge_document_collections,
    merge_kb_collections,
    recompute_kb_collections,
)

__all__ = [
    "instance_namespace",
    "clear_kb_collections",
    "get_document_collections",
    "get_kb_collections",
    "merge_document_collections",
    "merge_kb_collections",
    "recompute_kb_collections",
]
