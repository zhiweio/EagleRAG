"""RRF merge and cross-collection deduplication (G8/G32)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from eagle_rag.plugins.context import PluginAudit

from llama_index.core.schema import NodeWithScore

__all__ = ["dedupe_cross_collection", "merge_rrf"]


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
