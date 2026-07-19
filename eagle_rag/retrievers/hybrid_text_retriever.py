"""In-process dense + sparse keyword fusion for text collections."""

from __future__ import annotations

import re

from llama_index.core.schema import NodeWithScore

__all__ = [
    "hybrid_fuse_dense_sparse",
    "sparse_rank_nodes",
    "sparse_score",
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


def hybrid_fuse_dense_sparse(
    dense_nodes: list[NodeWithScore],
    query: str,
    *,
    alpha: float = 0.6,
    extra_sparse_terms: list[str] | None = None,
    rrf_k: int = 60,
) -> list[NodeWithScore]:
    """Fuse dense ANN ranking with sparse lexical ranking (domain-agnostic)."""
    del rrf_k
    if not dense_nodes:
        return []
    alpha = max(0.0, min(1.0, alpha))
    sparse_query = " ".join(extra_sparse_terms) if extra_sparse_terms else query
    sparse_nodes = sparse_rank_nodes(dense_nodes, sparse_query, extra_terms=extra_sparse_terms)
    if alpha >= 1.0 or not sparse_nodes:
        return list(dense_nodes)
    if alpha <= 0.0:
        return sparse_nodes
    sparse_weight = 1.0 - alpha
    sparse_by_id = {n.node.node_id: n for n in sparse_nodes if n.node.node_id}
    fused: list[NodeWithScore] = []
    for nws in dense_nodes:
        node_id = nws.node.node_id
        dense_score = float(nws.score or 0.0)
        sparse_score_val = 0.0
        if node_id and node_id in sparse_by_id:
            sparse_score_val = float(sparse_by_id[node_id].score or 0.0)
        combined = alpha * dense_score + sparse_weight * sparse_score_val
        fused.append(NodeWithScore(node=nws.node, score=combined))
    fused.sort(key=lambda item: item.score or 0.0, reverse=True)
    return fused
