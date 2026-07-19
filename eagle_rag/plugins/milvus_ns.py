"""Milvus database name mapping for plugin namespaces."""

from __future__ import annotations

__all__ = ["milvus_db_name"]


def milvus_db_name(plugin_namespace: str | None) -> str:
    """Map API plugin_namespace to a Milvus database name.

    ``core`` / ``None`` -> ``default`` (Milvus native default DB).
    Hyphenated namespaces map to underscores (e.g. ``lakehouse-bi`` -> ``lakehouse_bi``).
    """
    ns = plugin_namespace or "core"
    if ns == "core":
        return "default"
    return ns.replace("-", "_")
