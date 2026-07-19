"""DashScope text embed batch size guard."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from llama_index.core.schema import TextNode

from eagle_rag.index.milvus_text_store import (
    DASHSCOPE_TEXT_EMBED_BATCH_MAX,
    upsert_text_nodes,
)


def test_upsert_text_nodes_chunks_dashscope_batches() -> None:
    nodes = [TextNode(text=f"chunk-{i}", id_=f"id-{i}") for i in range(23)]
    mock_index = MagicMock()
    with patch("eagle_rag.index.milvus_text_store.get_text_index", return_value=mock_index):
        with patch("eagle_rag.index.milvus_text_store.get_settings") as mock_settings:
            mock_settings.return_value.milvus.text_collection = "eagle_text"
            ids = upsert_text_nodes(nodes, plugin_namespace="biomed")

    assert len(ids) == 23
    assert mock_index.insert_nodes.call_count == 3
    batch_sizes = [len(call.args[0]) for call in mock_index.insert_nodes.call_args_list]
    assert batch_sizes == [
        DASHSCOPE_TEXT_EMBED_BATCH_MAX,
        DASHSCOPE_TEXT_EMBED_BATCH_MAX,
        3,
    ]
