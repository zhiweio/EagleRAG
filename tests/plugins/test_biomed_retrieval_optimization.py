"""Tests for biomed retrieval optimization (P0-P2)."""

from __future__ import annotations

import pytest
from llama_index.core.schema import NodeWithScore, TextNode

from eagle_rag.retrievers.hybrid_text_retriever import hybrid_fuse_dense_sparse, sparse_score
from eagle_rag.router.rerank_fusion import rerank_merged
from plugins.biomed.umls import expand_query_for_dense_retrieval, match_drug_entities


def test_match_drug_entities_detects_lenvatinib() -> None:
    hits = match_drug_entities("lenvatinib dosing in HCC")
    assert "lenvatinib" in hits
    assert "EGFR" not in hits


def test_expand_query_for_dense_retrieval_appends_entities() -> None:
    expanded = expand_query_for_dense_retrieval("HER2 positive breast cancer")
    assert expanded is not None
    assert expanded.startswith("HER2 positive breast cancer")
    assert "biomed entities" in expanded


def test_sparse_score_prefers_exact_terms() -> None:
    assert sparse_score(
        "lenvatinib label", "This is the lenvatinib prescribing label"
    ) > sparse_score("lenvatinib label", "VEGFR pipeline overview")


def test_hybrid_fuse_promotes_lexical_match() -> None:
    dense = [
        NodeWithScore(node=TextNode(text="VEGFR pipeline overview"), score=0.9),
        NodeWithScore(node=TextNode(text="lenvatinib prescribing information"), score=0.4),
    ]
    fused = hybrid_fuse_dense_sparse(
        dense,
        "lenvatinib label",
        alpha=0.3,
        drug_entities=["lenvatinib"],
    )
    top_texts = [n.node.get_content() or "" for n in fused[:2]]
    assert any("lenvatinib" in text for text in top_texts)


def test_rerank_merged_skips_general_for_biomed(monkeypatch: pytest.MonkeyPatch) -> None:
    from eagle_rag.router import biomed_post_rerank

    def _fake_post_rrf(
        nodes: list[NodeWithScore],
        query: str,
        *,
        top_n: int,
        plugin_namespace: str = "biomed",
    ) -> list[NodeWithScore]:
        del query, plugin_namespace
        return nodes[:top_n]

    monkeypatch.setattr(biomed_post_rerank, "biomed_post_rrf_rerank", _fake_post_rrf)
    nodes = [
        NodeWithScore(node=TextNode(text="a"), score=1.0),
        NodeWithScore(node=TextNode(text="b"), score=0.5),
    ]
    out = rerank_merged(nodes, query="q", top_n=1, plugin_namespace="biomed")
    assert len(out) == 1
    assert out[0].node.get_content() == "a"
