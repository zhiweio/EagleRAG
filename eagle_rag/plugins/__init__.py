"""Plugin microkernel public API."""

from __future__ import annotations

from functools import lru_cache

from eagle_rag.plugins.manager import PluginManager

__all__ = ["get_plugin_manager", "reset_plugin_manager"]


@lru_cache(maxsize=1)
def get_plugin_manager() -> PluginManager:
    """Process-wide plugin manager singleton."""
    manager = PluginManager()
    manager.load_all()
    return manager


def reset_plugin_manager() -> None:
    """Clear the singleton (tests only)."""
    get_plugin_manager.cache_clear()
