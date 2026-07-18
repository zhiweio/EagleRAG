"""Plugin contract: manifest and lifecycle protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from eagle_rag.plugins.context import PluginContext
    from eagle_rag.plugins.hookbus import HookBus

__all__ = ["PluginManifest", "Plugin"]


@dataclass(frozen=True)
class PluginManifest:
    """Static metadata for a loaded plugin."""

    namespace: str
    version: str
    milvus_db_name: str | None = None
    depends_on: tuple[str, ...] = ()
    provides_pipelines: tuple[str, ...] = ()
    provides_retrievers: tuple[str, ...] = ()
    provides_mcp_tools: tuple[str, ...] = ()
    provides_specialized_collections: tuple[str, ...] = ()
    resource_hints: dict[str, Any] = field(default_factory=dict)


class Plugin(Protocol):
    """In-process plugin contract."""

    manifest: PluginManifest

    def register_hooks(self, bus: HookBus) -> None: ...

    def on_load(self, ctx: PluginContext) -> None: ...

    def on_unload(self) -> None: ...

    def ensure_collections(self, ctx: PluginContext) -> None: ...
