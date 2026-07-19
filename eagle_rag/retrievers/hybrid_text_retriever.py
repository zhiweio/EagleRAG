"""In-process dense + sparse keyword fusion for text collections."""

from __future__ import annotations

import json
import re
from typing import Any

from llama_index.core.schema import NodeWithScore

from eagle_rag.router.rerank_fusion import merge_rrf

__all__ = [
    "entity_boost_score",
    "hybrid_fuse_dense_sparse",
    "sparse_rank_nodes",
    "tokenize_query_terms",
]

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)?", re.IGNORECASE)


def tokenize_query_terms(query: str) -> list[str]:
    """Lowercase alphanumeric tokens (hyphenated drug names preserved)."""
    return [t.lower() for t in _TOKEN_RE.findall(query or "") if t]


def _node_text(nws: NodeWithScore) -> str:
    node = nws.node
    if hasattr(node, "get_content"):
        text = node.get_content() or ""
        if text:
            return str(text)
    return str(getattr(node, "text", "") or "")


def sparse_score(
    query: str,
    text: str,
    *,
    extra_terms: list[str] | None = None,
) -> float:
    """Lexical overlap score in ``[0, 1]`` for BM25-style recall."""
    terms = tokenize_query_terms(query)
    if extra_terms:
        terms.extend(t.lower() for t in extra_terms if t)
    terms = list(dict.fromkeys(terms))
    if not terms:
        return 0.0
    text_l = text.lower()
    hits = sum(1 for term in terms if term in text_l)
    return hits / len(terms)


def sparse_rank_nodes(
    nodes: list[NodeWithScore],
    query: str,
    *,
    extra_terms: list[str] | None = None,
) -> list[NodeWithScore]:
    """Rank nodes by lexical overlap with the query."""
    if not nodes:
        return []
    scored: list[tuple[float, float, NodeWithScore]] = []
    for nws in nodes:
        text = _node_text(nws)
        lexical = sparse_score(query, text, extra_terms=extra_terms)
        scored.append((lexical, float(nws.score or 0.0), nws))
    scored.sort(key=lambda item: (-item[0], -item[1]))
    return [
        NodeWithScore(node=item[2].node, score=item[0] or item[1])
        for item in scored
        if item[0] > 0 or item[1] > 0
    ]


def _parse_primary_drugs(metadata: dict[str, Any]) -> list[str]:
    raw = metadata.get("primary_drugs")
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(item) for item in raw if item]
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, list):
                return [str(item) for item in parsed if item]
        return [text]
    return []


def entity_boost_score(metadata: dict[str, Any], drug_entities: list[str]) -> float:
    """Soft boost when chunk metadata or text aligns with query drug entities."""
    if not drug_entities:
        return 0.0
    drugs_l = {d.lower() for d in drug_entities if d}
    for drug in _parse_primary_drugs(metadata):
        if drug.lower() in drugs_l:
            return 1.0
    blob = " ".join(
        str(metadata.get(key) or "") for key in ("path", "file_name", "document_name", "source_uri")
    ).lower()
    if any(drug in blob for drug in drugs_l):
        return 0.5
    return 0.0


def hybrid_fuse_dense_sparse(
    dense_nodes: list[NodeWithScore],
    query: str,
    *,
    alpha: float = 0.6,
    extra_sparse_terms: list[str] | None = None,
    drug_entities: list[str] | None = None,
    rrf_k: int = 60,
) -> list[NodeWithScore]:
    """Fuse dense ANN ranking with sparse lexical ranking via RRF + entity boost."""
    if not dense_nodes:
        return []
    alpha = max(0.0, min(1.0, alpha))
    sparse_nodes = sparse_rank_nodes(dense_nodes, query, extra_terms=extra_sparse_terms)
    if alpha >= 1.0 or not sparse_nodes:
        fused = list(dense_nodes)
    elif alpha <= 0.0:
        fused = sparse_nodes
    else:
        sparse_weight = 1.0 - alpha
        sparse_by_id = {n.node.node_id: n for n in sparse_nodes if n.node.node_id}
        fused = []
        for nws in dense_nodes:
            node_id = nws.node.node_id
            dense_score = float(nws.score or 0.0)
            sparse_score = 0.0
            if node_id and node_id in sparse_by_id:
                sparse_score = float(sparse_by_id[node_id].score or 0.0)
            combined = alpha * dense_score + sparse_weight * sparse_score
            fused.append(NodeWithScore(node=nws.node, score=combined))
        fused.sort(key=lambda item: item.score or 0.0, reverse=True)

    if not drug_entities:
        return fused

    boosted: list[NodeWithScore] = []
    for nws in fused:
        meta = nws.node.metadata or {}
        boost = entity_boost_score(meta, drug_entities)
        score = (nws.score or 0.0) + boost * 0.5
        boosted.append(NodeWithScore(node=nws.node, score=score))
    boosted.sort(key=lambda item: item.score or 0.0, reverse=True)
    return boosted
