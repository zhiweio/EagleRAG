"""Repository helpers: forced plugin_namespace injection (G9)."""

from __future__ import annotations

from eagle_rag.db.namespace import resolve_namespace

__all__ = ["instance_namespace"]


def instance_namespace(requested: str | None = None) -> str:
    """Namespace for PG reads/writes on this instance."""
    return resolve_namespace(requested)
