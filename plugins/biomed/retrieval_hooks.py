"""Biomed retrieval hooks: query expand, supplement, merged rerank."""

from __future__ import annotations

from typing import Any

from llama_index.core.schema import NodeWithScore

from eagle_rag.plugins.hookbus import HookContext
from eagle_rag.plugins.routing import ExpandedQuery

__all__ = [
    "biomed_dense_expand",
    "biomed_rerank_merged",
    "biomed_retrieve_supplement",
    "biomed_rrf_post_merge",
]


def biomed_dense_expand(
    ctx: HookContext,
    query: str,
    *,
    encoder: str | None = None,
    **kwargs: object,
) -> ExpandedQuery | None:
    del kwargs
    from plugins.biomed.query_intent import detect_retrieval_intent
    from plugins.biomed.umls import expand_query_for_dense_retrieval, match_drug_entities

    intent = detect_retrieval_intent(query)
    dense_query = query
    if encoder == "pubmedbert":
        expanded = expand_query_for_dense_retrieval(query)
        if expanded:
            dense_query = expanded

    sparse_terms = list(match_drug_entities(query))
    for cue in intent.section_cues:
        normalized = cue.replace("_", " ")
        if normalized not in sparse_terms:
            sparse_terms.append(normalized)

    ctx.extra = dict(ctx.extra or {})
    ctx.extra["retrieval_intent"] = intent

    return ExpandedQuery(
        dense_query=dense_query,
        sparse_terms=tuple(sparse_terms),
        intent=intent,
    )


def biomed_retrieve_supplement(
    ctx: HookContext,
    query: str,
    *,
    kb_name: str | None = None,
    recall_top_k: int = 30,
    **kwargs: object,
) -> list[Any]:
    del kwargs
    from plugins.biomed.query_intent import detect_retrieval_intent
    from plugins.biomed.supplement import supplement_entity_anchored_hits

    raw_intent = (ctx.extra or {}).get("retrieval_intent")
    intent = raw_intent if raw_intent is not None else detect_retrieval_intent(query)

    return supplement_entity_anchored_hits(
        query,
        kb_name=kb_name,
        plugin_namespace=ctx.plugin_namespace,
        recall_top_k=recall_top_k,
        intent=intent,
    )


def biomed_rerank_merged(
    ctx: HookContext,
    nodes: list[Any],
    *,
    query: str,
    top_n: int = 5,
    **kwargs: object,
) -> list[Any] | None:
    del kwargs
    from plugins.biomed.query_intent import detect_retrieval_intent
    from plugins.biomed.rerank import post_rrf_rerank

    intent = None
    raw_intent = (ctx.extra or {}).get("retrieval_intent")
    if raw_intent is not None:
        intent = raw_intent
    else:
        intent = detect_retrieval_intent(query)

    return post_rrf_rerank(
        nodes,
        query,
        top_n=top_n,
        plugin_namespace=ctx.plugin_namespace,
        intent=intent,
    )


def biomed_rrf_post_merge(
    ctx: HookContext,
    merged: list[Any],
    *,
    query: str,
    supplement_nodes: list[Any] | None = None,
    **kwargs: object,
) -> list[Any] | None:
    """Inject entity-anchored supplement hits before merged rerank (biomed-only)."""
    del query, kwargs
    raw_intent = (ctx.extra or {}).get("retrieval_intent")
    if raw_intent is None or not getattr(raw_intent, "require_entity_match", False):
        return None
    if not supplement_nodes:
        return None
    from eagle_rag.router.rerank_fusion import inject_supplement_candidates

    nodes = [n for n in merged if isinstance(n, NodeWithScore)]
    extra = [n for n in (supplement_nodes or []) if isinstance(n, NodeWithScore)]
    if not nodes or not extra:
        return None
    return inject_supplement_candidates(nodes, extra, min_new=2)
