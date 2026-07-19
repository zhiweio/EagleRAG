"""UMLS entity expansion for QUERY_ASSEMBLE (biomed)."""

from __future__ import annotations

from eagle_rag.plugins.hookbus import HookContext
from plugins.biomed.umls import expand_query_with_entities

__all__ = ["biomed_query_assemble"]


def biomed_query_assemble(
    hook_ctx: HookContext,
    query: str,
    *,
    kb_name: str | None = None,
    **kwargs: object,
) -> str | None:
    """Append matched UMLS entity aliases to the query context (non-blocking)."""
    del hook_ctx, kb_name, kwargs
    return expand_query_with_entities(query)
