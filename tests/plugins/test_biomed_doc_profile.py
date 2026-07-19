"""TDR document profile classifier tests."""

from __future__ import annotations

import pytest
from llama_index.core.schema import TextNode

from plugins.biomed.chunker import biomed_chunk_transform
from plugins.biomed.classifiers import BiomedTextClassifier
from plugins.biomed.doc_profile import (
    build_document_sketch,
    classify_document_text_profile,
    clear_prototype_cache,
)
from eagle_rag.plugins.classifier import ClassificationContext
from eagle_rag.plugins.hookbus import HookContext


def _node(path: str = "", text: str = "", **extra: object) -> TextNode:
    node = TextNode(text=text or "body")
    node.metadata = {"path": path, **extra}
    return node


def setup_function() -> None:
    clear_prototype_cache()


def test_build_document_sketch_prefers_section_summary() -> None:
    nodes = [
        _node("", "generic body", type="text"),
        _node(
            "",
            "Trial of fruquintinib in colorectal cancer kinase inhibitor.",
            type="section_summary",
        ),
    ]
    sketch = build_document_sketch(nodes)
    assert "fruquintinib" in sketch
    assert "kinase" in sketch


def test_classify_biomedical_research_paper() -> None:
    words = " ".join(["patient"] * 30)
    nodes = [
        _node("doc/Abstract", f"VEGFR inhibitor trial abstract. {words}"),
        _node("doc/3 Methods", f"PCR sequencing protocol. {words}", biomed_section="methods"),
        _node("doc/2 Results", f"Cohort outcomes. {words}", biomed_section="results"),
    ]
    profile = classify_document_text_profile(nodes)
    assert profile.profile == "biomedical"


def test_classify_general_corporate_text(monkeypatch: pytest.MonkeyPatch) -> None:
    def _general_fusion(**kwargs: object) -> float:
        return -0.25

    monkeypatch.setattr("plugins.biomed.doc_profile._fusion_score", _general_fusion)
    nodes = [
        _node(
            "",
            "Quarterly earnings revenue growth shareholder return investor relations "
            "operating income guidance fiscal year.",
        ),
    ]
    profile = classify_document_text_profile(nodes)
    assert profile.profile == "general"


def test_chunk_transform_stamps_text_profile() -> None:
    words = " ".join(["protocol"] * 40)
    nodes = [
        _node("doc/3 Methods", f"Kinase inhibitor study methods. {words}"),
        _node("doc/2 Results", f"Patient outcomes. {words}"),
    ]
    ctx = HookContext(plugin_namespace="biomed", kb_name="kb", document_id="d1")
    out = biomed_chunk_transform(ctx, nodes)
    assert out[0].metadata.get("biomed_text_profile") in {"biomedical", "general"}
    assert out[0].metadata.get("biomed_text_profile_rule")


def test_classifier_uses_document_profile_for_keywordless_chunk() -> None:
    words = " ".join(["reference"] * 50)
    ctx = ClassificationContext(
        content=f"Bibliography entry without drug names. {words}",
        modality="text",
        document_id="d1",
        kb_name="kb",
        plugin_namespace="biomed",
        parent_section="doc/References",
        extra={
            "section": "body",
            "text_profile": "biomedical",
            "text_profile_rule": "tier1_fusion_biomedical",
            "text_profile_confidence": 0.8,
        },
    )
    decision = BiomedTextClassifier().classify(ctx)
    assert decision is not None
    assert decision.target_collection == "eagle_text_biomed"
    assert decision.target_encoder == "pubmedbert"
