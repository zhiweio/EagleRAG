"""Plugin namespace integration smoke (ingest catalog + scope routing)."""

from __future__ import annotations

import pytest
from llama_index.core.schema import NodeWithScore, TextNode

from eagle_rag.plugins.ingest_catalog import commit_ingest_catalog
from eagle_rag.router.rerank_fusion import dedupe_cross_collection


def test_specialized_collections_declared_for_biomed_profile() -> None:
    from plugins.biomed import plugin

    collections = plugin.manifest.provides_specialized_collections
    assert "eagle_text_biomed" in collections
    assert "eagle_medical_radiology" in collections


def test_commit_ingest_catalog_merges_collections(monkeypatch: pytest.MonkeyPatch) -> None:
    merged: list[str] = []

    def _merge_doc(document_id: str, collections: list[str], **kwargs: object) -> None:
        merged.extend(collections)

    monkeypatch.setattr(
        "eagle_rag.plugins.ingest_catalog.merge_document_collections",
        _merge_doc,
    )
    monkeypatch.setattr(
        "eagle_rag.plugins.ingest_catalog.merge_kb_collections",
        lambda *_a, **_k: None,
    )
    commit_ingest_catalog("doc-xyz", "default", ["eagle_text", "eagle_visual"])
    assert merged == ["eagle_text", "eagle_visual"]


def test_dedupe_cross_collection_prefers_first_hit() -> None:
    node = TextNode(text="chunk", id_="n1", metadata={"document_id": "d1", "path": "1"})
    a = NodeWithScore(node=node, score=0.9)
    b = NodeWithScore(node=node, score=0.5)
    out = dedupe_cross_collection([a, b])
    assert len(out) == 1
    assert out[0].score == 0.9


def test_plugin_manager_health_lists_core_defaults() -> None:
    from eagle_rag.plugins import get_plugin_manager

    mgr = get_plugin_manager()
    payload = mgr.health_payload()
    namespaces = {m["namespace"] for m in payload["manifests"]}
    assert "core" in namespaces
