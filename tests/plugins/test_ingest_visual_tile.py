"""PixelRAG tile records must classify/upsert as visual, not text."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from eagle_rag.plugins import reset_plugin_manager
from eagle_rag.plugins.classifier import ClassificationContext
from eagle_rag.plugins.hookbus import HookContext
from eagle_rag.plugins.ingest_helpers import ingest_visual_record
from eagle_rag.plugins.ingest_orchestrator import IngestOrchestrator, _looks_like_visual_record


def test_tile_modality_uses_classify_visual() -> None:
    reset_plugin_manager()
    from eagle_rag.plugins import get_plugin_manager

    mgr = get_plugin_manager()
    orch = IngestOrchestrator(mgr.bus, mgr.encoder_registry)
    ctx = HookContext(plugin_namespace="core", kb_name="default", document_id="doc1")
    decision = orch.classify(
        ctx,
        ClassificationContext(
            content=b"",
            modality="tile",
            document_id="doc1",
            kb_name="default",
            plugin_namespace="core",
        ),
    )
    assert decision.target_collection == "eagle_visual"
    assert decision.target_encoder == "qwen3-vl"


def test_looks_like_visual_record() -> None:
    assert _looks_like_visual_record({"image_id": "a", "vector": [0.1, 0.2]})
    assert _looks_like_visual_record({"image_bytes": b"png", "vector": []}) is True
    assert _looks_like_visual_record({"text": "hello"}) is False
    assert _looks_like_visual_record("not-a-dict") is False


def test_ingest_visual_record_tile_upserts_visual_not_text() -> None:
    reset_plugin_manager()
    record = {
        "image_id": "doc1_0",
        "vector": [0.01] * 8,
        "image_path": "minio://x.png",
        "document_id": "doc1",
        "page": 0,
        "position": "strip_0",
        "kb_name": "hutchmed",
        "source_type": "other",
        "chunk_type": "tile",
    }
    with patch(
        "eagle_rag.index.milvus_visual_store.upsert_visual",
        MagicMock(return_value=None),
    ) as upsert_visual:
        with patch(
            "eagle_rag.index.milvus_text_store.upsert_text_nodes",
            MagicMock(side_effect=AssertionError("must not upsert text")),
        ):
            node_id = ingest_visual_record(
                record,
                plugin_namespace="core",
                kb_name="hutchmed",
                document_id="doc1",
            )
    assert node_id == "doc1_0"
    upsert_visual.assert_called_once()
    kwargs = upsert_visual.call_args.kwargs
    assert kwargs["image_id"] == "doc1_0"
    assert kwargs["chunk_type"] == "tile"
    assert kwargs["kb_name"] == "hutchmed"
