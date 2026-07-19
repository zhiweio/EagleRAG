"""RRF merge and cross-collection deduplication (G8/G32)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from eagle_rag.telemetry import get_logger

if TYPE_CHECKING:
    from eagle_rag.plugins.context import PluginAudit

from llama_index.core.schema import ImageNode, NodeWithScore

__all__ = ["dedupe_cross_collection", "merge_rrf", "rerank_merged"]

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


def rerank_merged(
    nodes: list[NodeWithScore],
    *,
    query: str,
    top_n: int,
    plugin_namespace: str | None = None,
    audit: PluginAudit | None = None,
) -> list[NodeWithScore]:
    """Post-RRF cross-encoder rerank on text nodes; visual nodes pass through.

      Applies DashScope ``qwen3-rerank`` to the fused text hits so that noise
      injected by weakly-related collections (e.g. deterministic-embedding
      fallbacks) is filtered after RRF. ``ImageNode`` hits are appended unchanged
      (no visual reranker is wired). On any failure the RRF order is returned so
      retrieval never breaks due to the rerank service.

    Biomed deployments may disable the general reranker via
    ``settings.plugins.options.biomed.use_general_rerank`` (default ``false``) so
    domain PubMedBERT rerank from the ``RERANK`` hook is preserved.
    """
    text_nodes = [n for n in nodes if not isinstance(n.node, ImageNode)]
    image_nodes = [n for n in nodes if isinstance(n.node, ImageNode)]
    if not text_nodes:
        return nodes

    if not _use_general_rerank(plugin_namespace):
        if plugin_namespace == "biomed":
            from eagle_rag.router.biomed_post_rerank import biomed_post_rrf_rerank

            reranked = biomed_post_rrf_rerank(
                text_nodes,
                query,
                top_n=top_n,
                plugin_namespace=plugin_namespace or "biomed",
            )
            if audit is not None:
                audit.log_decision(
                    category="rerank",
                    reason="post_rrf_biomed",
                    plugin_namespace=plugin_namespace,
                    extra={"text_in": len(text_nodes), "text_out": len(reranked)},
                )
            return reranked + image_nodes
        trimmed = text_nodes[:top_n] + image_nodes
        if audit is not None:
            audit.log_decision(
                category="rerank",
                reason="post_rrf_domain_only",
                plugin_namespace=plugin_namespace,
                extra={"text_in": len(text_nodes), "text_out": len(trimmed)},
            )
        return trimmed

    try:
        from eagle_rag.generation.multimodal_engine import _default_text_reranker

        reranker = _default_text_reranker()
        if reranker is None:
            return nodes
        reranked = reranker.postprocess_nodes(text_nodes, query_str=query)
    except Exception as exc:  # noqa: BLE001
        logger.warning("post-RRF rerank failed; returning RRF order: %s", exc)
        return nodes

    if not reranked:
        return nodes
    reranked = sorted(reranked, key=lambda n: n.score or 0.0, reverse=True)[:top_n]
    if audit is not None:
        audit.log_decision(
            category="rerank",
            reason="post_rrf_qwen3",
            plugin_namespace=plugin_namespace,
            extra={"text_in": len(text_nodes), "text_out": len(reranked)},
        )
    return reranked + image_nodes


def _use_general_rerank(plugin_namespace: str | None) -> bool:
    if plugin_namespace != "biomed":
        return True
    try:
        from eagle_rag.config import get_settings, plugin_options

        biomed_cfg = plugin_options("biomed", get_settings())
        return bool(biomed_cfg.get("use_general_rerank", False))
    except Exception:  # noqa: BLE001
        return False
