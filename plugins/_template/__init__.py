"""Industry RAG plugin template — copy and rename for a new vertical.

Deliverable = backend module + MCP tools + deployment profile.
No frontend is required or provided for domain plugins.
"""

from __future__ import annotations

from eagle_rag.plugins.classifier import ClassificationContext, ClassificationDecision
from eagle_rag.plugins.context import PluginContext
from eagle_rag.plugins.contract import PluginManifest
from eagle_rag.plugins.hookbus import HookBus, HookContext
from eagle_rag.plugins.hooks import Hook

__all__ = ["IndustryTemplatePlugin", "plugin"]

# Placeholder namespace — rename when copying (must match default_namespace / profile).
_NAMESPACE = "stub-template"


class IndustryTemplatePlugin:
    """Minimal RAG-only industry plugin (classify + PARSE/CHUNK/QUERY_ASSEMBLE + MCP)."""

    manifest = PluginManifest(
        namespace=_NAMESPACE,
        version="0.0.1",
        milvus_db_name=None,
        provides_mcp_tools=("retrieve_assets",),
        provides_specialized_collections=(),
    )

    def register_hooks(self, bus: HookBus) -> None:
        bus.subscribe(
            Hook.CLASSIFY_CHUNK,
            self._classify_chunk,
            priority=50,
            namespace=_NAMESPACE,
            plugin_name="industry_template",
        )
        bus.subscribe(
            Hook.PARSE,
            self._parse_transform,
            priority=50,
            namespace=_NAMESPACE,
            plugin_name="industry_template",
        )
        bus.subscribe(
            Hook.CHUNK,
            self._chunk_transform,
            priority=50,
            namespace=_NAMESPACE,
            plugin_name="industry_template",
        )
        bus.subscribe(
            Hook.QUERY_ASSEMBLE,
            self._query_assemble,
            priority=50,
            namespace=_NAMESPACE,
            plugin_name="industry_template",
        )

    def on_load(self, ctx: PluginContext) -> None:
        del ctx

    def register_mcp_tools(self) -> None:
        from plugins._template import mcp_tools as _mcp_tools

        _mcp_tools.register_mcp_tools()

    def on_unload(self) -> None:
        return None

    def ensure_collections(self, ctx: PluginContext) -> None:
        """Core ``eagle_text`` / ``eagle_visual`` are enough unless you add specialized dims."""
        del ctx

    def _classify_chunk(
        self,
        hook_ctx: HookContext,
        class_ctx: ClassificationContext,
    ) -> ClassificationDecision | None:
        del hook_ctx
        # Abstain (None) → Core default. Override with domain rules as needed.
        text = class_ctx.content if isinstance(class_ctx.content, str) else ""
        if "acme_domain_marker" in text.lower():
            from eagle_rag.config import get_settings

            settings = get_settings()
            return ClassificationDecision(
                category="template_marker",
                target_collection=settings.milvus.text_collection,
                target_encoder="text-embedding-v4",
                chunk_type="text",
                confidence=0.6,
            )
        return None

    def _parse_transform(
        self,
        hook_ctx: HookContext,
        parse_result: object,
        **kwargs: object,
    ) -> object:
        del hook_ctx, kwargs
        return parse_result

    def _chunk_transform(
        self,
        hook_ctx: HookContext,
        nodes: list[object],
        **kwargs: object,
    ) -> list[object]:
        del hook_ctx, kwargs
        return nodes

    def _query_assemble(
        self,
        hook_ctx: HookContext,
        query: str,
        *,
        kb_name: str | None = None,
        **kwargs: object,
    ) -> str | None:
        del hook_ctx, kb_name, kwargs
        # Return expanded query text, or None to leave the query unchanged.
        return None


plugin = IndustryTemplatePlugin()
