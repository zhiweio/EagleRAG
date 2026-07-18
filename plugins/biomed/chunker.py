"""Biomed IMRaD / patent chunking hooks."""

from __future__ import annotations

from typing import Any

from eagle_rag.plugins.hookbus import HookContext

__all__ = ["biomed_chunk_transform"]


def biomed_chunk_transform(
    hook_ctx: HookContext,
    nodes: list[Any],
    **kwargs: object,
) -> list[Any]:
    """Annotate biomedical text nodes with IMRaD section hints when path is present."""
    del kwargs
    out: list[Any] = []
    for node in nodes:
        meta = getattr(node, "metadata", None) or {}
        path = str(meta.get("path") or "").lower()
        section = "body"
        for label in ("abstract", "introduction", "methods", "results", "discussion", "claims"):
            if label in path:
                section = label
                break
        if isinstance(meta, dict):
            meta = dict(meta)
            meta["biomed_section"] = section
            node.metadata = meta
        out.append(node)
    return out
