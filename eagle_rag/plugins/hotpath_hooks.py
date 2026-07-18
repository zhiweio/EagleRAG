"""Apply PARSE/CHUNK/QUERY_ASSEMBLE hooks on ingest and query hot paths."""

from __future__ import annotations

from typing import Any

from eagle_rag.config import get_settings
from eagle_rag.plugins import get_plugin_manager
from eagle_rag.plugins.hookbus import HookContext
from eagle_rag.plugins.hooks import Hook
from eagle_rag.telemetry import get_logger

__all__ = [
    "apply_chunk_hook",
    "apply_parse_hook",
    "apply_query_assemble",
]

logger = get_logger(__name__)


def _hook_context(
    *,
    plugin_namespace: str | None = None,
    kb_name: str | None = None,
    document_id: str | None = None,
) -> HookContext:
    settings = get_settings()
    return HookContext(
        plugin_namespace=plugin_namespace or settings.plugins.default_namespace,
        kb_name=kb_name,
        document_id=document_id,
    )


def apply_parse_hook(
    parse_result: Any,
    *,
    file_path: str | None = None,
    file_name: str | None = None,
    plugin_namespace: str | None = None,
    kb_name: str | None = None,
    document_id: str | None = None,
) -> Any:
    """Run ``PARSE`` transform hooks (fail-fast per G13)."""
    mgr = get_plugin_manager()
    ctx = _hook_context(
        plugin_namespace=plugin_namespace,
        kb_name=kb_name,
        document_id=document_id,
    )
    return mgr.bus.invoke_transform(
        Hook.PARSE,
        ctx,
        parse_result,
        file_path=file_path or "",
        file_name=file_name or "",
    )


def apply_chunk_hook(
    nodes: list[Any],
    *,
    file_path: str | None = None,
    file_name: str | None = None,
    plugin_namespace: str | None = None,
    kb_name: str | None = None,
    document_id: str | None = None,
) -> list[Any]:
    """Run ``CHUNK`` transform hooks (fail-fast per G13)."""
    mgr = get_plugin_manager()
    ctx = _hook_context(
        plugin_namespace=plugin_namespace,
        kb_name=kb_name,
        document_id=document_id,
    )
    result = mgr.bus.invoke_transform(
        Hook.CHUNK,
        ctx,
        nodes,
        file_path=file_path or "",
        file_name=file_name or "",
    )
    return list(result) if result is not None else nodes


def apply_query_assemble(
    query: str,
    *,
    plugin_namespace: str | None = None,
    kb_name: str | None = None,
) -> str:
    """Append ``QUERY_ASSEMBLE`` plugin hints to the retrieval query (G13 degrade)."""
    settings = get_settings()
    if not getattr(settings.plugins, "query_assemble_enabled", True):
        return query
    mgr = get_plugin_manager()
    ctx = _hook_context(plugin_namespace=plugin_namespace, kb_name=kb_name)
    pieces = mgr.bus.invoke_all(Hook.QUERY_ASSEMBLE, ctx, query, kb_name=kb_name)
    suffixes = [str(p).strip() for p in pieces if p]
    if not suffixes:
        return query
    assembled = query.rstrip() + "\n" + "\n".join(suffixes)
    logger.debug(
        "QUERY_ASSEMBLE applied",
        extra={"pieces": len(suffixes), "namespace": ctx.plugin_namespace},
    )
    return assembled
