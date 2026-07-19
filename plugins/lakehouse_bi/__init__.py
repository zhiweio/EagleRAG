"""Lakehouse BI domain plugin: semantic-layer RAG retrieval (read-only)."""

from __future__ import annotations

from eagle_rag.plugins.context import PluginContext
from eagle_rag.plugins.contract import PluginManifest
from eagle_rag.plugins.hookbus import HookBus, HookContext
from eagle_rag.plugins.hooks import Hook
from plugins.lakehouse_bi.ingest_hooks import lakehouse_chunk_transform, lakehouse_parse_transform
from plugins.lakehouse_bi.query_assemble import lakehouse_query_assemble

__all__ = ["LakehouseBiPlugin", "plugin"]


class LakehouseBiPlugin:
    """In-process lakehouse-bi plugin (semantic context retrieval only)."""

    manifest = PluginManifest(
        namespace="lakehouse-bi",
        version="0.1.0",
        milvus_db_name="lakehouse_bi",
        provides_mcp_tools=("query_semantic_context", "retrieve_historical_analysis"),
    )

    def register_hooks(self, bus: HookBus) -> None:
        bus.subscribe(
            Hook.PARSE,
            self._parse_transform,
            priority=100,
            namespace="lakehouse-bi",
            plugin_name="lakehouse_bi",
        )
        bus.subscribe(
            Hook.CHUNK,
            self._chunk_transform,
            priority=100,
            namespace="lakehouse-bi",
            plugin_name="lakehouse_bi",
        )
        bus.subscribe(
            Hook.QUERY_ASSEMBLE,
            self._query_assemble,
            priority=100,
            namespace="lakehouse-bi",
            plugin_name="lakehouse_bi",
        )

    def on_load(self, ctx: PluginContext) -> None:
        del ctx

    def register_mcp_tools(self) -> None:
        """Import MCP tool module so ``@register_mcp_tool`` decorators run."""
        from plugins.lakehouse_bi import mcp_tools as _mcp_tools

        _mcp_tools.register_mcp_tools()

    def on_unload(self) -> None:
        return None

    def ensure_collections(self, ctx: PluginContext) -> None:
        """Uses base ``eagle_text`` / ``eagle_visual`` collections only."""
        del ctx
        return None

    def _parse_transform(self, hook_ctx: HookContext, parse_result: object, **kwargs: object):
        return lakehouse_parse_transform(hook_ctx, parse_result, **kwargs)

    def _chunk_transform(self, hook_ctx: HookContext, nodes: list[object], **kwargs: object):
        return lakehouse_chunk_transform(hook_ctx, nodes, **kwargs)

    def _query_assemble(
        self,
        hook_ctx: HookContext,
        query: str,
        *,
        kb_name: str | None = None,
        **kwargs: object,
    ) -> str | None:
        return lakehouse_query_assemble(hook_ctx, query, kb_name=kb_name, **kwargs)


plugin = LakehouseBiPlugin()
