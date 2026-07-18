"""Stub biomed plugin for G3 validation tests."""

from __future__ import annotations

from eagle_rag.plugins.context import PluginContext
from eagle_rag.plugins.contract import PluginManifest
from eagle_rag.plugins.hookbus import HookBus


class _StubBiomedPlugin:
    manifest = PluginManifest(namespace="biomed", version="0.0.0")

    def register_hooks(self, bus: HookBus) -> None:
        return None

    def on_load(self, ctx: PluginContext) -> None:
        return None

    def on_unload(self) -> None:
        return None

    def ensure_collections(self, ctx: PluginContext) -> None:
        return None


plugin = _StubBiomedPlugin()
