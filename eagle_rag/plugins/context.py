"""Plugin runtime context and audit telemetry re-exports."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from eagle_rag.plugins.audit import PluginAudit, PluginAuditEvent

if TYPE_CHECKING:
    from eagle_rag.config import Settings
    from eagle_rag.plugins.collection_registry import CollectionStoreRegistry
    from eagle_rag.plugins.encoder_registry import EncoderRegistry
    from eagle_rag.plugins.hookbus import HookBus

__all__ = ["PluginAudit", "PluginAuditEvent", "PluginContext"]


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
