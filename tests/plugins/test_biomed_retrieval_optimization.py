"""Tests for biomed retrieval optimization (entity-anchored recall + MedCPT rerank)."""

from __future__ import annotations

import pytest
from llama_index.core.schema import NodeWithScore, TextNode

from eagle_rag.plugins.hookbus import HookBus, HookContext
from eagle_rag.plugins.hooks import Hook
from eagle_rag.plugins.rerank_policy import RerankPolicy, resolve_rerank_policy
from eagle_rag.retrievers.hybrid_text_retriever import hybrid_fuse_dense_sparse, sparse_score
from eagle_rag.router.rerank_fusion import inject_supplement_candidates, rerank_merged
from plugins.biomed.chunker import detect_doc_type, detect_section
from plugins.biomed.query_intent import detect_retrieval_intent
from plugins.biomed.rerank import post_rrf_rerank, score_retrieval_signals
from plugins.biomed.retrieval_hooks import biomed_rrf_post_merge
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
        extra_sparse_terms=["lenvatinib"],
    )
    top_texts = [n.node.get_content() or "" for n in fused[:2]]
    assert any("lenvatinib" in text for text in top_texts)


def test_q_seed_007_not_regulatory() -> None:
    intent = detect_retrieval_intent(
        "cabozantinib sunitinib renal cell carcinoma VEGFR TKI landscape"
    )
    assert intent.workflow == "drug_entity"
    assert intent.require_entity_match is True


def test_label_intent_suppresses_chemical_plan() -> None:
    intent = detect_retrieval_intent(
        "sunitinib drug label indications and usage renal cell carcinoma"
    )
    assert intent.workflow == "regulatory"
    assert "eagle_chemical" in intent.suppress_collections
    assert "indications_and_usage" in intent.section_cues
    assert intent.require_entity_match is True


def test_section_aliases_detect_indications() -> None:
    section = detect_section("", "## Indications and usage\n\nRCC indication")
    assert section == "indications_and_usage"
    assert detect_doc_type("label_sunitinib/Indications and usage", "") == "drug_label"


def test_score_retrieval_signals_prefers_indications_section() -> None:
    intent = detect_retrieval_intent(
        "sunitinib drug label indications and usage renal cell carcinoma"
    )
    label_home = NodeWithScore(
        node=TextNode(
            text="Brand name sunitinib",
            metadata={
                "biomed_section": "body",
                "primary_drugs": ["sunitinib"],
            },
        ),
        score=0.5,
    )
    indications = NodeWithScore(
        node=TextNode(
            text="INDICATIONS AND USAGE for renal cell carcinoma",
            metadata={
                "biomed_section": "indications_and_usage",
                "primary_drugs": ["sunitinib"],
                "path": "Indications and usage",
            },
        ),
        score=0.4,
    )
    home_signal = score_retrieval_signals(label_home, "sunitinib label indications", intent)
    ind_signal = score_retrieval_signals(indications, "sunitinib label indications", intent)
    assert ind_signal > home_signal


def test_entity_rerank_penalizes_pmc_noise() -> None:
    intent = detect_retrieval_intent("lenvatinib FGFR VEGFR competitor profile")
    pmc = NodeWithScore(
        node=TextNode(
            text="Emerging approaches in renal cell carcinoma and HIF pathways",
            metadata={"path": "pmc13264436/Discussion"},
        ),
        score=0.9,
    )
    target = NodeWithScore(
        node=TextNode(
            text="lenvatinib is a multi-kinase inhibitor",
            metadata={"primary_drugs": ["lenvatinib"], "path": "Drug profile"},
        ),
        score=0.4,
    )
    assert score_retrieval_signals(target, "lenvatinib profile", intent) > score_retrieval_signals(
        pmc, "lenvatinib profile", intent
    )


def test_inject_supplement_candidates() -> None:
    merged = [
        NodeWithScore(
            node=TextNode(text="noise", metadata={"document_id": "d1", "path": "a"}), score=1.0
        )
    ]
    supplement = [
        NodeWithScore(
            node=TextNode(
                text="sunitinib label",
                metadata={"document_id": "d2", "path": "Indications and usage"},
            ),
            score=0.5,
        )
    ]
    out = inject_supplement_candidates(merged, supplement, min_new=1)
    assert len(out) == 2
    assert "sunitinib" in (out[0].node.get_content() or "")


def test_biomed_rrf_post_merge_injects_when_entity_match_required() -> None:
    intent = detect_retrieval_intent(
        "sunitinib drug label indications and usage renal cell carcinoma"
    )
    merged = [
        NodeWithScore(
            node=TextNode(text="noise", metadata={"document_id": "d1", "path": "a"}), score=1.0
        )
    ]
    supplement = [
        NodeWithScore(
            node=TextNode(
                text="sunitinib label",
                metadata={"document_id": "d2", "path": "Indications and usage"},
            ),
            score=0.5,
        )
    ]
    ctx = HookContext(plugin_namespace="biomed", extra={"retrieval_intent": intent})
    out = biomed_rrf_post_merge(
        ctx,
        merged,
        query="sunitinib drug label",
        supplement_nodes=supplement,
    )
    assert out is not None
    assert len(out) == 2
    assert "sunitinib" in (out[0].node.get_content() or "")


def test_q_seed_018_label_section_ranks_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "plugins.biomed.rerank._medcpt_scores",
        lambda query, nodes: [
            0.2 if "INDICATIONS" not in (n.node.get_content() or "") else 0.95 for n in nodes
        ],
    )
    nodes = [
        NodeWithScore(
            node=TextNode(
                text="Emerging RCC review without target drug",
                metadata={"path": "pmc13264436/Discussion"},
            ),
            score=3.96,
        ),
        NodeWithScore(
            node=TextNode(
                text="Brand name sunitinib",
                metadata={"primary_drugs": ["sunitinib"]},
            ),
            score=3.95,
        ),
        NodeWithScore(
            node=TextNode(
                text="INDICATIONS AND USAGE renal cell carcinoma",
                metadata={
                    "biomed_section": "indications_and_usage",
                    "primary_drugs": ["sunitinib"],
                    "path": "Indications and usage",
                },
            ),
            score=3.94,
        ),
    ]
    query = "sunitinib drug label indications and usage renal cell carcinoma"
    out = post_rrf_rerank(nodes, query, top_n=3, plugin_namespace="biomed")
    assert "INDICATIONS" in (out[0].node.get_content() or "")


def test_rerank_merged_uses_hook(monkeypatch: pytest.MonkeyPatch) -> None:
    bus = HookBus()

    def _fake_merged(
        ctx: HookContext,
        nodes: list[NodeWithScore],
        *,
        query: str,
        top_n: int,
        **kwargs: object,
    ) -> list[NodeWithScore]:
        del ctx, query, kwargs
        return nodes[:top_n]

    bus.subscribe(
        Hook.RERANK_MERGED,
        _fake_merged,
        priority=100,
        namespace="biomed",
        plugin_name="test",
    )
    nodes = [
        NodeWithScore(node=TextNode(text="a"), score=1.0),
        NodeWithScore(node=TextNode(text="b"), score=0.5),
    ]
    out = rerank_merged(
        nodes,
        query="q",
        top_n=1,
        plugin_namespace="biomed",
        hook_bus=bus,
    )
    assert len(out) == 1
    assert out[0].node.get_content() == "a"


def test_resolve_rerank_policy_domain_when_hook_present() -> None:
    bus = HookBus()
    bus.subscribe(
        Hook.RERANK_MERGED,
        lambda ctx, nodes, **kw: nodes,
        namespace="biomed",
        plugin_name="test",
    )
    assert resolve_rerank_policy("biomed", bus) == RerankPolicy.DOMAIN
