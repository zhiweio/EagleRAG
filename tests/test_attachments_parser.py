"""Attachment parser unit tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from llama_index.core.schema import NodeWithScore, TextNode

from eagle_rag.attachments.parser import parse_attachments
from eagle_rag.router.router_engine import EagleRouterQueryEngine


def test_parse_inline_txt_attachment():
    """txt attachments go through inline slicing (with a mocked store)."""
    aid = "att-1"
    meta = {
        "attachment_id": aid,
        "file_name": "note.txt",
        "mime": "text/plain",
        "size_bytes": 21,
        "storage_path": "/tmp/note.txt",
    }
    with (
        patch("eagle_rag.attachments.parser.get_attachment_sync", return_value=meta),
        patch(
            "eagle_rag.attachments.parser.get_attachment_bytes_sync",
            return_value=b"hello attachment world",
        ),
        patch("eagle_rag.attachments.parser._load_cache", return_value=None),
        patch("eagle_rag.attachments.parser._save_cache"),
    ):
        result = parse_attachments([aid])
    assert len(result.text_nodes) >= 1
    assert result.text_nodes[0].metadata.get("source") == "attachment"
    assert "hello" in result.text_nodes[0].text


def test_parse_attachment_sidecar_cache():
    """A second parse hits the sidecar cache."""
    aid = "att-2"
    meta = {
        "attachment_id": aid,
        "file_name": "memo.md",
        "mime": "text/markdown",
        "size_bytes": 14,
        "storage_path": "/tmp/memo.md",
    }
    cached_payload = {
        "attachment_id": aid,
        "file_name": "memo.md",
        "pipeline": "inline",
        "chunks": [
            {
                "chunk_id": "c0",
                "content": "cached content",
                "path": "memo.md",
                "type": "text",
                "metadata": {"file_path": "memo.md", "page_nums": []},
            }
        ],
        "tiles": [],
    }
    with (
        patch("eagle_rag.attachments.parser.get_attachment_sync", return_value=meta),
        patch(
            "eagle_rag.attachments.parser.get_attachment_bytes_sync",
            return_value=b"cached content",
        ),
        patch("eagle_rag.attachments.parser._load_cache", return_value=cached_payload),
        patch("eagle_rag.attachments.parser._save_cache") as save_mock,
    ):
        result = parse_attachments([aid])
    assert result.cached_count == 1
    assert result.parsed_count == 0
    assert len(result.text_nodes) == 1
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
