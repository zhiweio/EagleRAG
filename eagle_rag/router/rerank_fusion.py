"""RRF merge and cross-collection deduplication (G8/G32)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from eagle_rag.telemetry import get_logger

if TYPE_CHECKING:
    from eagle_rag.plugins.context import PluginAudit
    from eagle_rag.plugins.hookbus import HookBus

from llama_index.core.schema import ImageNode, NodeWithScore

__all__ = ["dedupe_cross_collection", "inject_supplement_candidates", "merge_rrf", "rerank_merged"]

logger = get_logger(__name__)


def _cross_collection_key(nws: NodeWithScore) -> str:
    meta = nws.node.metadata or {}
    source_chunk_id = meta.get("source_chunk_id")
    if source_chunk_id:
        return f"sc:{source_chunk_id}"
    document_id = meta.get("document_id") or ""
    path = meta.get("path") or ""
    return f"dp:{document_id}:{path}"


def _rrf_item_key(nws: NodeWithScore) -> str:
    node_id = nws.node.node_id
    if node_id:
        return node_id
    return _cross_collection_key(nws)


def merge_rrf(
    plans_results: list[list[NodeWithScore]],
    *,
    k: int = 60,
) -> list[NodeWithScore]:
    """Reciprocal Rank Fusion across per-plan ranked result lists.

    Empty result lists are excluded from fusion (G8: zero-hit paths do not
    contribute phantom ranks).
    """
    non_empty = [lst for lst in plans_results if lst]
    if not non_empty:
        return []
    if len(non_empty) == 1:
        return list(non_empty[0])

    scores: dict[str, float] = {}
    nodes_by_key: dict[str, NodeWithScore] = {}
    for result_list in non_empty:
        for rank, nws in enumerate(result_list, start=1):
            key = _rrf_item_key(nws)
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
            nodes_by_key.setdefault(key, nws)

    ordered = sorted(scores.keys(), key=lambda item: scores[item], reverse=True)
    return [NodeWithScore(node=nodes_by_key[key].node, score=scores[key]) for key in ordered]


def dedupe_cross_collection(
    nodes: list[NodeWithScore],
    *,
    audit: PluginAudit | None = None,
) -> list[NodeWithScore]:
    """Collapse duplicate logical chunks across collections (G32).

    Dedupes by ``source_chunk_id`` when present, otherwise by
    ``(document_id, path)``. Keeps the higher-ranked (earlier) node.
    """
    seen: dict[str, NodeWithScore] = {}
    order: list[str] = []
    removed = 0
    for nws in nodes:
        key = _cross_collection_key(nws)
        if key in seen:
            removed += 1
            continue
        seen[key] = nws
        order.append(key)

    if removed and audit is not None:
        audit.log_decision(
            category="rrf_dedupe",
            reason="rrf_dedupe",
            extra={"removed": removed},
        )

    return [seen[key] for key in order]


def inject_supplement_candidates(
    merged: list[NodeWithScore],
    supplement: list[NodeWithScore],
    *,
    min_new: int = 2,
) -> list[NodeWithScore]:
    """Ensure top supplement hits enter the rerank candidate pool (generic fusion primitive)."""
    if not supplement or min_new <= 0:
        return merged
    seen = {_cross_collection_key(nws) for nws in merged}
    injected: list[NodeWithScore] = []
    for nws in supplement:
        key = _cross_collection_key(nws)
        if key in seen:
            continue
        injected.append(NodeWithScore(node=nws.node, score=float(nws.score or 0.0) + 100.0))
        seen.add(key)
        if len(injected) >= min_new:
            break
    if not injected:
        return merged
    return injected + merged


def _qwen3_rerank(
    text_nodes: list[NodeWithScore],
    query: str,
    *,
    top_n: int,
) -> list[NodeWithScore]:
    try:
        from eagle_rag.generation.multimodal_engine import _default_text_reranker

        reranker = _default_text_reranker()
        if reranker is None:
            return text_nodes[:top_n]
        reranked = reranker.postprocess_nodes(text_nodes, query_str=query)
    except Exception as exc:  # noqa: BLE001
        logger.warning("post-RRF qwen3 rerank failed; returning RRF order: %s", exc)
        return text_nodes[:top_n]

    if not reranked:
        return text_nodes[:top_n]
    reranked = sorted(reranked, key=lambda n: n.score or 0.0, reverse=True)[:top_n]
    return reranked


def rerank_merged(
    nodes: list[NodeWithScore],
    *,
    query: str,
    top_n: int,
    plugin_namespace: str | None = None,
    audit: PluginAudit | None = None,
    hook_bus: HookBus | None = None,
) -> list[NodeWithScore]:
    """Post-RRF rerank on text nodes; visual nodes pass through.

    Policy-driven: domain plugins use ``RERANK_MERGED`` hook; core uses
    DashScope ``qwen3-rerank`` when ``rerank_policy=general``.
    """
    from eagle_rag.plugins.hookbus import HookContext
    from eagle_rag.plugins.hooks import Hook
    from eagle_rag.plugins.rerank_policy import RerankPolicy, resolve_rerank_policy

    text_nodes = [n for n in nodes if not isinstance(n.node, ImageNode)]
    image_nodes = [n for n in nodes if isinstance(n.node, ImageNode)]
    if not text_nodes:
        return nodes

    policy = resolve_rerank_policy(plugin_namespace, hook_bus)

    if policy == RerankPolicy.DOMAIN and hook_bus is not None and plugin_namespace:
        hook_ctx = HookContext(plugin_namespace=plugin_namespace)
        reranked = hook_bus.invoke_first(
            Hook.RERANK_MERGED,
            hook_ctx,
            text_nodes,
            query=query,
            top_n=top_n,
        )
        if reranked is not None:
            if audit is not None:
                audit.log_decision(
                    category="rerank",
                    reason="rerank_t2_domain",
                    plugin_namespace=plugin_namespace,
                    extra={"text_in": len(text_nodes), "text_out": len(reranked)},
                )
            return list(reranked) + image_nodes
        trimmed = text_nodes[:top_n]
        if audit is not None:
            audit.log_decision(
                category="rerank",
                reason="rerank_t2_passthrough",
                plugin_namespace=plugin_namespace,
                extra={"text_in": len(text_nodes), "text_out": len(trimmed)},
            )
        return trimmed + image_nodes

    if policy == RerankPolicy.GENERAL:
        reranked = _qwen3_rerank(text_nodes, query, top_n=top_n)
        if audit is not None:
            audit.log_decision(
                category="rerank",
                reason="rerank_t2_general",
                plugin_namespace=plugin_namespace,
                extra={"text_in": len(text_nodes), "text_out": len(reranked)},
            )
        return reranked + image_nodes

    trimmed = text_nodes[:top_n]
    if audit is not None:
        audit.log_decision(
            category="rerank",
            reason="rerank_t2_passthrough",
            plugin_namespace=plugin_namespace,
            extra={"text_in": len(text_nodes), "text_out": len(trimmed)},
        )
    return trimmed + image_nodes
