"""Plugin runtime context and audit telemetry."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from eagle_rag.config import Settings
    from eagle_rag.plugins.collection_registry import CollectionStoreRegistry
    from eagle_rag.plugins.encoder_registry import EncoderRegistry
    from eagle_rag.plugins.hookbus import HookBus

__all__ = ["PluginAudit", "PluginContext"]


@dataclass
class PluginAudit:
    """Classification and routing decision telemetry."""

    _entries: list[dict[str, Any]] = field(default_factory=list)

    def log_decision(
        self,
        *,
        category: str,
        target_collection: str | None = None,
        confidence: float | None = None,
        reason: str | None = None,
        plugin_namespace: str | None = None,
        error: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        entry: dict[str, Any] = {"category": category}
        if target_collection is not None:
            entry["target_collection"] = target_collection
        if confidence is not None:
            entry["confidence"] = confidence
        if reason is not None:
            entry["reason"] = reason
        if plugin_namespace is not None:
            entry["plugin_namespace"] = plugin_namespace
        if error is not None:
            entry["error"] = error
        if extra:
            entry.update(extra)
        self._entries.append(entry)

    def recent(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._entries[-limit:]

    def clear(self) -> None:
        self._entries.clear()


@dataclass(frozen=True)
class PluginContext:
    """Runtime context passed to plugin on_load / ensure_collections."""

    plugin_namespace: str
    default_namespace: str
    settings: Settings
    bus: HookBus
    encoder_registry: EncoderRegistry
    collection_registry: CollectionStoreRegistry
    audit: PluginAudit
    register_pipeline: Callable[[str, Any], None]
