"""Attachment parser unit tests."""

from __future__ import annotations

import base64
from unittest.mock import MagicMock, patch

from llama_index.core.schema import NodeWithScore, TextNode

from eagle_rag.attachments.parser import parse_attachments
from eagle_rag.router.router_engine import EagleRouterQueryEngine


def test_parse_png_attachment():
    """PNG attachments are materialized as image docs with bytes."""
    aid = "att-1"
    png_bytes = b"\x89PNG\r\n\x1a\n"
    meta = {
        "attachment_id": aid,
        "file_name": "chart.png",
        "mime": "image/png",
        "size_bytes": len(png_bytes),
        "storage_path": "/tmp/chart.png",
    }
    with (
        patch("eagle_rag.attachments.parser.get_attachment_sync", return_value=meta),
        patch("eagle_rag.attachments.parser.get_attachment_bytes_sync", return_value=png_bytes),
        patch("eagle_rag.attachments.parser._load_cache", return_value=None),
        patch("eagle_rag.attachments.parser._save_cache"),
    ):
        result = parse_attachments([aid])
    assert result.has_image_attachment is True
    assert result.image_bytes == png_bytes
    assert len(result.image_docs) == 1


def test_parse_rejects_non_image_attachment():
    aid = "att-2"
    meta = {
        "attachment_id": aid,
        "file_name": "note.txt",
        "mime": "text/plain",
        "size_bytes": 5,
        "storage_path": "/tmp/note.txt",
    }
    with (
        patch("eagle_rag.attachments.parser.get_attachment_sync", return_value=meta),
        patch(
            "eagle_rag.attachments.parser.get_attachment_bytes_sync",
            return_value=b"hello",
        ),
    ):
        result = parse_attachments([aid])
    assert result.errors
    assert not result.image_docs


def test_parse_attachment_sidecar_cache():
    """A second parse hits the sidecar cache."""
    aid = "att-3"
    meta = {
        "attachment_id": aid,
        "file_name": "memo.png",
        "mime": "image/png",
        "size_bytes": 14,
        "storage_path": "/tmp/memo.png",
    }
    cached_payload = {
        "attachment_id": aid,
        "file_name": "memo.png",
        "pipeline": "image",
        "image_b64": base64.b64encode(b"\x89PNG").decode("ascii"),
        "chunks": [],
        "tiles": [],
    }
    with (
        patch("eagle_rag.attachments.parser.get_attachment_sync", return_value=meta),
        patch(
            "eagle_rag.attachments.parser.get_attachment_bytes_sync",
            return_value=b"\x89PNG",
        ),
        patch("eagle_rag.attachments.parser._load_cache", return_value=cached_payload),
        patch("eagle_rag.attachments.parser._save_cache") as save_mock,
    ):
        result = parse_attachments([aid])
    assert result.cached_count == 1
    assert result.parsed_count == 0
    assert result.has_image_attachment is True
    save_mock.assert_not_called()


def test_query_stream_yields_token_events():
    """query_stream yields token and done events under a mock VLM."""
    mock_text = MagicMock()
    mock_text.retrieve.return_value = [
        NodeWithScore(node=TextNode(text="policy", id_="c1"), score=0.9)
    ]
    mock_visual = MagicMock()
    mock_visual.retrieve.return_value = []

    vlm = MagicMock()
    vlm.stream_complete.return_value = [MagicMock(delta="Hello"), MagicMock(delta=" world")]

    with patch("eagle_rag.generation.multimodal_engine._default_multi_modal_llm", return_value=vlm):
        router = EagleRouterQueryEngine(text_retriever=mock_text, visual_retriever=mock_visual)
        events = list(
            router.query_stream(
                "test query",
                mode="text",
                session_id="sess-1",
                user_message_id="user-1",
            )
        )
    event_names = [e["event"] for e in events]
    assert "session" in event_names
    assert "step" in event_names
    assert "token" in event_names
    assert "done" in event_names
