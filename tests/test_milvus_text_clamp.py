"""Guards against Milvus VARCHAR(65535) overflow on text upserts."""

from __future__ import annotations

import hashlib
from unittest.mock import MagicMock, patch

from llama_index.core.schema import TextNode

from eagle_rag.index.milvus_text_store import (
    MILVUS_VARCHAR_TEXT_MAX,
    clamp_milvus_varchar,
    upsert_text_nodes,
)


def test_clamp_milvus_varchar_passthrough() -> None:
    text = "ok" * 100
    assert clamp_milvus_varchar(text) is text


def test_clamp_milvus_varchar_truncates_to_limit() -> None:
    text = "a" * (MILVUS_VARCHAR_TEXT_MAX + 8000)
    out = clamp_milvus_varchar(text)
    assert len(out) == MILVUS_VARCHAR_TEXT_MAX
    assert out.endswith("\n...[truncated]")
    assert out.startswith("a")


def test_clamp_milvus_varchar_custom_max() -> None:
    out = clamp_milvus_varchar("a" * 40, max_length=20)
    assert len(out) == 20
    assert out.endswith("\n...[truncated]")


def test_upsert_text_nodes_clamps_before_insert() -> None:
    huge = "中" * (MILVUS_VARCHAR_TEXT_MAX + 100)
    node = TextNode(
        text=huge,
        id_="node-overflow",
        metadata={
            "document_id": "doc-1",
            "kb_name": "biomed",
            "path": "paper/Methods",
            "type": "section_summary",
        },
    )
    index = MagicMock()
    mock_logger = MagicMock()

    with (
        patch("eagle_rag.index.milvus_text_store.get_settings") as gs,
        patch("eagle_rag.index.milvus_text_store.get_text_index", return_value=index),
        patch("eagle_rag.index.milvus_text_store.logger", mock_logger),
    ):
        gs.return_value.milvus.text_collection = "eagle_text"
        ids = upsert_text_nodes([node], collection="eagle_text")

    assert ids == ["node-overflow"]
    assert len(node.text) == MILVUS_VARCHAR_TEXT_MAX
    index.insert_nodes.assert_called_once()
    inserted = index.insert_nodes.call_args.args[0]
    assert len(inserted[0].get_content()) == MILVUS_VARCHAR_TEXT_MAX

    mock_logger.warning.assert_called_once()
    msg, *args = mock_logger.warning.call_args.args
    assert "truncating text node for Milvus VARCHAR limit" in msg
    assert args[0] == "node-overflow"
    assert args[1] == "doc-1"
    assert args[2] == "biomed"
    assert args[3] == "paper/Methods"
    assert args[4] == "section_summary"
    assert args[5] == len(huge)
    assert args[6] == MILVUS_VARCHAR_TEXT_MAX
    assert args[7] == 100 + len("\n...[truncated]")
    assert args[8] == hashlib.sha256(huge.encode("utf-8")).hexdigest()
    assert isinstance(args[9], str)
    assert args[9]  # dropped_preview non-empty
