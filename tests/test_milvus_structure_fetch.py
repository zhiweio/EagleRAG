"""Tests for Milvus document-scoped text node fetch (structure reconstruction)."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from eagle_rag.index.document_structure import _reconstruct_tree, build_document_structure
from eagle_rag.index.milvus_text_store import (
    _row_to_node_dict,
    fetch_text_nodes_by_document_id,
)


def _node_content_row(
    *,
    node_id: str,
    document_id: str,
    path: str,
    chunk_type: str = "section_summary",
    summary: str = "Section body",
    chunk_count: int = 2,
) -> dict:
    payload = {
        "id_": node_id,
        "metadata": {
            "path": path,
            "level": path.count("/") + 1,
            "summary": summary,
            "type": chunk_type,
            "document_id": document_id,
            "kb_name": "test",
            "chunk_count": chunk_count,
        },
    }
    return {
        "id": node_id,
        "text": summary,
        "_node_content": json.dumps(payload),
        "path": path,
        "type": chunk_type,
        "document_id": "None",
    }


def test_row_to_node_dict_reads_document_id_from_node_content():
    row = _node_content_row(
        node_id="sec_a",
        document_id="doc-1",
        path="paper/Intro",
    )
    node = _row_to_node_dict(row)
    assert node is not None
    assert node["metadata"]["document_id"] == "doc-1"
    assert node["metadata"]["path"] == "paper/Intro"


@patch("eagle_rag.index.milvus_text_store._get_text_milvus_client")
def test_fetch_text_nodes_by_document_id_falls_back_to_node_content(mock_client):
    doc_id = "3d6e3de4-2360-4f4f-b444-ee73a871c832"
    row = _node_content_row(
        node_id="sec_a",
        document_id=doc_id,
        path="170603762v7.pdf/Attention Is All You Need/2 Background",
    )
    client = MagicMock()
    client.query.side_effect = [
        [],  # document_id scalar
        [],  # doc_id scalar
        [row],  # kb_name scoped scan
    ]
    mock_client.return_value = (client, "eagle_text")

    nodes = fetch_text_nodes_by_document_id(
        doc_id,
        types=["section_summary"],
        kb_name="test",
        path_prefix="170603762v7.pdf",
    )
    assert len(nodes) == 1
    assert nodes[0]["metadata"]["type"] == "section_summary"
    assert client.query.call_count == 3
    assert 'kb_name == "test"' in client.query.call_args_list[2].kwargs["filter"]


def test_reconstruct_tree_builds_nested_sections():
    nodes = [
        {
            "id": "sec_a",
            "text": "Background summary",
            "metadata": {
                "path": "paper/Attention/2 Background",
                "level": 2,
                "summary": "Background summary",
                "type": "section_summary",
                "chunk_count": 3,
            },
        }
    ]
    tree = _reconstruct_tree(nodes)
    assert len(tree) == 1
    assert tree[0]["path"] == "paper"
    assert tree[0]["children"][0]["path"] == "paper/Attention"
    assert tree[0]["children"][0]["children"][0]["path"] == "paper/Attention/2 Background"
    assert tree[0]["children"][0]["children"][0]["chunk_count"] == 3


@patch("eagle_rag.index.document_structure.fetch_visual_by_document", return_value=[])
@patch("eagle_rag.index.document_structure.fetch_text_nodes_by_document_id")
def test_build_document_structure_reconstructs_when_doc_nav_missing(mock_fetch, _mock_visual):
    doc_id = "doc-1"
    mock_fetch.side_effect = [
        [
            {
                "id": "sec_a",
                "text": "Intro",
                "metadata": {
                    "path": "paper/Intro",
                    "level": 1,
                    "summary": "Intro",
                    "type": "section_summary",
                    "chunk_count": 1,
                },
            }
        ],
    ]
    doc = {
        "document_id": doc_id,
        "name": "paper.pdf",
        "kb_name": "test",
        "pipeline": "knowhere",
        "extra": {},
    }
    out = build_document_structure(doc_id, doc)
    assert out["source"] == "reconstructed"
    assert len(out["sections"]) == 1
    assert out["sections"][0]["path"] == "paper"
    mock_fetch.assert_called_with(
        doc_id,
        types=["section_summary"],
        kb_name="test",
        path_prefix="paper.pdf",
    )
