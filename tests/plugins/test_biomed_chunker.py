"""Biomed Knowhere-preserving section tagger tests."""

from __future__ import annotations

import pytest
from llama_index.core.schema import TextNode

from plugins.biomed.chunker import (
    biomed_chunk_transform,
    detect_doc_type,
    detect_section,
)


def _node(path: str = "", text: str = "", **extra: object) -> TextNode:
    node = TextNode(text=text or "body content")
    node.metadata = {"path": path, **extra}
    return node


def test_detect_section_from_path_leaf() -> None:
    assert detect_section("doc/3 Methods/3.1 Patient cohort", "") == "methods"
    assert detect_section("doc/2 Results", "") == "results"
    assert detect_section("doc/4 Discussion", "") == "discussion"
    assert detect_section("doc/1 Introduction", "") == "introduction"
    assert detect_section("doc/Abstract", "") == "abstract"
    assert detect_section("doc/5 Conclusion", "") == "conclusion"


def test_detect_section_materials_and_methods() -> None:
    assert detect_section("doc/Materials and Methods", "") == "methods"
    assert detect_section("doc/2.3 Materials and Methods", "") == "methods"


def test_detect_section_path_takes_precedence_over_text() -> None:
    # Path says methods, text starts with "Results" -> path wins.
    assert detect_section("doc/3 Methods", "Results\ncohort data") == "methods"


def test_detect_section_nonempty_path_ignores_text_heading() -> None:
    # Knowhere-first: unmatched path must not be overridden by body headings.
    assert detect_section("doc/Appendix A", "Methods\nWe used PCR.") == "body"


def test_detect_section_text_heading_fallback() -> None:
    assert detect_section("", "3. Methods\nWe used PCR.") == "methods"
    assert detect_section("", "Results\nThe cohort comprised...") == "results"
    assert detect_section("", "MATERIALS AND METHODS\nReagents") == "methods"
    assert detect_section("", "2.1 Patient cohort\nWe enrolled...") == "body"


def test_detect_section_patent_claims() -> None:
    assert detect_section("doc/Claims", "") == "claims"
    assert detect_section("", "1. A method for treating...") == "claims"
    assert detect_section("", "What is claimed is:\n1. A compound...") == "claims"


def test_detect_section_default_body() -> None:
    assert detect_section("", "Some generic paragraph without heading signals.") == "body"
    assert detect_section("doc/Appendix A", "Supplementary data") == "body"


def test_detect_doc_type_research() -> None:
    assert detect_doc_type("doc/Abstract", "Background and methods") == "research"
    assert detect_doc_type("", "Introduction\nWe studied HER2.") == "research"


def test_detect_doc_type_patent() -> None:
    assert detect_doc_type("doc/Claims", "What is claimed is: 1. A method") == "patent"
    assert detect_doc_type("", "Patent claim 1: A compound...") == "patent"


def test_detect_doc_type_other() -> None:
    assert detect_doc_type("", "Random business memo about quarterly results.") == "other"


def test_biomed_chunk_transform_annotates_metadata() -> None:
    from eagle_rag.plugins.hookbus import HookContext

    nodes = [
        _node("doc/3 Methods", "PCR protocol details " + " ".join(["gene"] * 50)),
        _node("doc/1 Introduction", "HER2 is a receptor tyrosine kinase."),
        _node("", "1. A method for treating cancer."),
    ]
    ctx = HookContext(plugin_namespace="biomed", kb_name="kb", document_id="d1")
    out = biomed_chunk_transform(ctx, nodes)
    assert out[0].metadata["biomed_section"] == "methods"
    assert out[0].metadata["biomed_doc_type"] == "research"
    assert out[1].metadata["biomed_section"] == "introduction"
    assert out[2].metadata["biomed_section"] == "claims"
    assert out[2].metadata["biomed_doc_type"] == "patent"


def test_biomed_chunk_transform_preserves_knowhere_structure() -> None:
    from eagle_rag.plugins.hookbus import HookContext

    body = "findings text unchanged"
    node = _node(
        "doc/2 Results",
        body,
        keywords=["her2", "egfr"],
        chunk_id="ck-1",
        type="text",
    )
    ctx = HookContext(plugin_namespace="biomed", kb_name="kb", document_id="d1")
    out = biomed_chunk_transform(ctx, [node])
    assert out[0].text == body
    assert out[0].metadata["path"] == "doc/2 Results"
    assert out[0].metadata["chunk_id"] == "ck-1"
    assert out[0].metadata["type"] == "text"
    assert out[0].metadata["keywords"] == ["her2", "egfr"]
    assert out[0].metadata["biomed_section"] == "results"
    assert len(out) == 1


def test_imrad_section_reaches_text_classifier() -> None:
    """TDR text_profile must route keywordless chunks to eagle_text_biomed."""
    from eagle_rag.plugins.classifier import ClassificationContext
    from plugins.biomed.classifiers import BiomedTextClassifier

    words = " ".join(["protocol"] * 45)
    text = f"We sequenced the cohort. {words}"
    ctx = ClassificationContext(
        content=text,
        modality="text",
        document_id="d1",
        kb_name="kb",
        plugin_namespace="biomed",
        parent_section="doc/3 Methods",
        extra={
            "section": "methods",
            "doc_type": "research",
            "text_profile": "biomedical",
            "text_profile_rule": "tier1_fusion_biomedical",
        },
    )
    decision = BiomedTextClassifier().classify(ctx)
    assert decision is not None
    assert decision.target_collection == "eagle_text_biomed"
    assert decision.metadata.get("text_profile") == "biomedical"


def test_ingest_helpers_forwards_biomed_section_to_classifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ingest_text_nodes must pass biomed_section into ClassificationContext.extra."""
    from eagle_rag.plugins import ingest_helpers as helpers
    from eagle_rag.plugins.classifier import ClassificationContext, ClassificationDecision

    captured: list[ClassificationContext] = []

    class _Orch:
        def classify(
            self,
            hook_ctx: object,
            class_ctx: ClassificationContext,
        ) -> ClassificationDecision:
            captured.append(class_ctx)
            return ClassificationDecision(
                category="biomed_term",
                target_collection="eagle_text_biomed",
                target_encoder="pubmedbert",
                chunk_type="biomed_text",
                confidence=0.6,
                metadata={"rule": "imrad_methods_results"},
            )

        def embed_and_upsert(self, *args: object, **kwargs: object) -> list[str]:
            return ["n1"]

    monkeypatch.setattr(helpers, "get_ingest_orchestrator", lambda: _Orch())
    words = " ".join(["protocol"] * 45)
    node = _node(
        "doc/3 Methods",
        f"We sequenced the cohort. {words}",
        biomed_section="methods",
        biomed_doc_type="research",
        chunk_id="ck-methods",
    )
    helpers.ingest_text_nodes(
        [node],
        document_id="d1",
        kb_name="kb",
        plugin_namespace="biomed",
    )
    assert len(captured) == 1
    assert captured[0].extra.get("section") == "methods"
    assert captured[0].extra.get("doc_type") == "research"
