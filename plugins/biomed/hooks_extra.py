"""Biomed ingest-route selector and PubMedBERT rerank hooks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from llama_index.core.schema import NodeWithScore

from eagle_rag.plugins.hookbus import HookContext

__all__ = ["biomed_format_selector", "biomed_rerank"]

_BIOMED_EXTS = {
    ".pdb",
    ".sdf",
    ".mol",
    ".mol2",
    ".cif",
    ".dcm",
    ".nii",
    ".nii.gz",
}


def biomed_format_selector(
    ctx: HookContext,
    *,
    file_path: str | None = None,
    file_name: str | None = None,
    source_type: str | None = None,
    **kwargs: object,
) -> str | None:
    """Route biomed-specific formats to the Core ``knowhere`` pipeline (G7)."""
    del kwargs, source_type, ctx
    name = file_name or file_path or ""
    suffix = Path(name).suffix.lower()
    if name.lower().endswith(".nii.gz"):
        suffix = ".nii.gz"
    if suffix in _BIOMED_EXTS:
        return "knowhere"
    return None


def biomed_rerank(
    ctx: HookContext,
    nodes: list[Any],
    *,
    query: str,
    collection: str | None = None,
    encoder: str | None = None,
    **kwargs: object,
) -> list[Any] | None:
    """Tier-1 rerank: domain bi-encoder cosine per collection + entity signals."""
    del kwargs
    from plugins.biomed.rerank import cosine_rerank
    from plugins.biomed.scoring import entity_boost_score

    coll = collection or (ctx.extra or {}).get("collection")
    enc = encoder or (ctx.extra or {}).get("encoder")
    encoder_name: str | None = None
    if coll == "eagle_text_biomed" or enc == "pubmedbert":
        encoder_name = "pubmedbert"
    elif coll == "eagle_chemical" or enc == "molformer":
        encoder_name = "molformer"
    if encoder_name is None:
        return None
    if not nodes:
        return nodes

    intent = (ctx.extra or {}).get("retrieval_intent")
    sparse_terms = list((ctx.extra or {}).get("sparse_terms") or [])
    working = list(nodes)
    if intent is not None and getattr(intent, "require_entity_match", False) and sparse_terms:
        filtered: list[Any] = []
        for nws in working:
            if not isinstance(nws, NodeWithScore):
                continue
            meta = nws.node.metadata or {}
            text = nws.node.get_content() if hasattr(nws.node, "get_content") else ""
            if entity_boost_score(meta, sparse_terms) > 0:
                filtered.append(nws)
                continue
            blob = f"{text[:512]} {meta.get('path') or ''}".lower()
            if any(term.lower() in blob for term in sparse_terms if term):
                filtered.append(nws)
        if filtered:
            working = filtered

    return cosine_rerank(working, query, encoder=encoder_name)
