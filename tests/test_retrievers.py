"""Retriever unit tests.

Mocks all underlying dependencies (``get_text_index`` / ``embed_query`` /
``search_visual``) and verifies the retrieval paths of ``KnowhereGraphRetriever``
and ``PixelRAGVisualRetriever``, the ``kb_name`` multi-tenant filter pushdown,
the returned node types, metadata fields, and error-degradation behavior.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from llama_index.core.schema import ImageNode, NodeWithScore, TextNode
from llama_index.core.vector_stores import (
    FilterOperator,
    MetadataFilter,
    MetadataFilters,
)

from eagle_rag.retrievers.knowhere_graph_retriever import KnowhereGraphRetriever
from eagle_rag.retrievers.pixelrag_visual_retriever import PixelRAGVisualRetriever

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_text_node(
    node_id: str,
    text: str,
    *,
    connect_to: list[str] | None = None,
    document_id: str = "doc1",
    path: str = "财政/个税",
    level: str = "section",
    summary: str = "个税相关章节",
    source_type: str = "financial",
) -> TextNode:
    return TextNode(
        id_=node_id,
        text=text,
        metadata={
            "path": path,
            "level": level,
            "summary": summary,
            "connect_to": connect_to or [],
            "document_id": document_id,
            "source_type": source_type,
        },
    )


def _visual_result(
    image_id: str,
    *,
    score: float = 0.8,
    document_id: str = "doc1",
    kb_name: str | None = "finance",
    year: int | None = 2025,
    source_type: str | None = "financial",
    chunk_type: str | None = "image",
    parent_section: str | None = "3 Model Architecture",
    content_summary: str | None = "Transformer architecture diagram",
    source_chunk_id: str | None = "chunk_img_1",
) -> dict:
    return {
        "image_id": image_id,
        "image_path": f"/data/{image_id}.png",
        "url": f"http://minio/{image_id}.png",
        "document_id": document_id,
        "page": 1,
        "position": f"strip_{image_id}",
        "score": score,
        "kb_name": kb_name,
        "year": year,
        "source_type": source_type,
        "chunk_type": chunk_type,
        "parent_section": parent_section,
        "content_summary": content_summary,
        "source_chunk_id": source_chunk_id,
    }


# ---------------------------------------------------------------------------
# KnowhereGraphRetriever
# ---------------------------------------------------------------------------


def test_knowhere_graph_retriever():
    """Text vector retrieval + connect_to graph expansion."""
    # 2 raw nodes: n1.connect_to points to c3; n2 has no connect_to.
    n1 = _make_text_node("c1", "起征点 5000 元/月", connect_to=["c3"])
    n2 = _make_text_node("c2", "专项附加扣除", connect_to=[])
    # Graph-related node c3 (lives in the docstore).
    n3_related = _make_text_node("c3", "居民个人综合所得", connect_to=[])

    inner_retriever = MagicMock()
    inner_retriever.retrieve.return_value = [
        NodeWithScore(node=n1, score=0.9),
        NodeWithScore(node=n2, score=0.85),
    ]

    mock_docstore = MagicMock()
    mock_docstore.get_node.side_effect = lambda nid, raise_error=False: {
        "c3": n3_related,
    }.get(nid)

    mock_index = MagicMock()
    mock_index.as_retriever.return_value = inner_retriever
    mock_index.docstore = mock_docstore

    with (
        patch(
            "eagle_rag.retrievers.knowhere_graph_retriever.get_text_index",
            return_value=mock_index,
        ),
        patch("eagle_rag.retrievers.knowhere_graph_retriever.get_settings") as mock_settings,
    ):
        mock_settings.return_value.router.parent_doc_retrieval = False
        retriever = KnowhereGraphRetriever(top_k=5)
        results = retriever.retrieve("个税起征点")

    # Return type is list[NodeWithScore].
    assert isinstance(results, list)
    assert all(isinstance(r, NodeWithScore) for r in results)
    # 2 raw + 1 graph-expanded (c3) = 3.
    assert len(results) == 3

    # Raw nodes carry path/level in metadata.
    for r in results[:2]:
        assert "path" in r.node.metadata
        assert "level" in r.node.metadata

    # Graph expansion: c3 is pulled in; c1/c2 each appear once (deduped).
    ids = [r.node.node_id for r in results]
    assert "c3" in ids
    assert ids.count("c1") == 1
    assert ids.count("c2") == 1

    # Without kb_name, as_retriever only receives similarity_top_k.
    mock_index.as_retriever.assert_called_once_with(similarity_top_k=5)
    # Inner retrieve receives the query string.
    inner_retriever.retrieve.assert_called_once_with("个税起征点")


def test_knowhere_graph_retriever_with_kb_name():
    """A non-empty kb_name builds MetadataFilters to push scalar filtering to the vector store."""
    inner_retriever = MagicMock()
    inner_retriever.retrieve.return_value = []

    mock_index = MagicMock()
    mock_index.as_retriever.return_value = inner_retriever
    mock_index.docstore = MagicMock()

    with (
        patch(
            "eagle_rag.retrievers.knowhere_graph_retriever.get_text_index",
            return_value=mock_index,
        ),
        patch("eagle_rag.retrievers.knowhere_graph_retriever.get_settings") as mock_settings,
    ):
        mock_settings.return_value.router.parent_doc_retrieval = False
        retriever = KnowhereGraphRetriever(top_k=5, kb_name="pharma")
        retriever.retrieve("药品增值税")

    # as_retriever receives similarity_top_k + filters (MetadataFilters).
    assert mock_index.as_retriever.call_count == 1
    call_kwargs = mock_index.as_retriever.call_args.kwargs
    assert call_kwargs.get("similarity_top_k") == 5
    assert "filters" in call_kwargs

    filters = call_kwargs["filters"]
    assert isinstance(filters, MetadataFilters)
    assert len(filters.filters) == 1
    f = filters.filters[0]
    assert isinstance(f, MetadataFilter)
    assert f.key == "kb_name"
    assert f.value == "pharma"
    assert f.operator == FilterOperator.EQ


def test_knowhere_graph_retriever_parent_doc_two_stage():
    """parent_doc_retrieval=True recalls section_summary then drills down by path prefix."""
    section_node = _make_text_node(
        "sec1",
        "Model architecture overview",
        path="doc/3 Model Architecture",
        summary="Architecture section",
    )
    section_node.metadata["type"] = "section_summary"
    drill_node = _make_text_node(
        "chunk1",
        "Attention block details",
        path="doc/3 Model Architecture/3.2 Attention",
    )

    stage1_retriever = MagicMock()
    stage1_retriever.retrieve.return_value = [NodeWithScore(node=section_node, score=0.9)]

    stage2_retriever = MagicMock()
    stage2_retriever.retrieve.return_value = [NodeWithScore(node=drill_node, score=0.8)]

    mock_index = MagicMock()
    mock_index.as_retriever.side_effect = [stage1_retriever, stage2_retriever]
    mock_index.docstore = MagicMock()

    with (
        patch(
            "eagle_rag.retrievers.knowhere_graph_retriever.get_text_index",
            return_value=mock_index,
        ),
        patch("eagle_rag.retrievers.knowhere_graph_retriever.get_settings") as mock_settings,
    ):
        mock_settings.return_value.router.parent_doc_retrieval = True
        retriever = KnowhereGraphRetriever(top_k=5)
        results = retriever.retrieve("attention mechanism")

    assert len(results) == 2
    ids = {r.node.node_id for r in results}
    assert ids == {"sec1", "chunk1"}
    assert mock_index.as_retriever.call_count == 2
    stage2_kwargs = mock_index.as_retriever.call_args_list[1].kwargs
    path_filter = stage2_kwargs["filters"].filters[0]
    assert path_filter.key == "path"
    assert path_filter.value == "doc/3 Model Architecture"
    assert path_filter.operator == FilterOperator.TEXT_MATCH


# ---------------------------------------------------------------------------
# PixelRAGVisualRetriever — embed_query + search_visual direct Milvus query
# ---------------------------------------------------------------------------


def test_pixelrag_visual_retriever():
    """embed_query encodes the query + search_visual queries Milvus directly; returns a list of
    ImageNode."""
    query_vector = [0.1] * 2048
    milvus_results = [
        _visual_result("img_a", score=0.7),
        _visual_result("img_b", score=0.6),
    ]

    with (
        patch(
            "eagle_rag.retrievers.pixelrag_visual_retriever.embed_query",
            return_value=query_vector,
        ) as mock_embed,
        patch(
            "eagle_rag.retrievers.pixelrag_visual_retriever.search_visual",
            return_value=milvus_results,
        ) as mock_milvus,
    ):
        retriever = PixelRAGVisualRetriever(top_k=2)
        results = retriever.retrieve("契税税率表")

    # 2 NodeWithScore; node is ImageNode.
    assert isinstance(results, list)
    assert len(results) == 2
    assert all(isinstance(r, NodeWithScore) for r in results)
    for r in results:
        assert isinstance(r.node, ImageNode)
        assert r.node.metadata.get("image_id") in {"img_a", "img_b"}
    # score comes from the result.
    assert results[0].score == 0.7
    assert results[1].score == 0.6

    # embed_query receives the query string.
    mock_embed.assert_called_once_with("契税税率表")
    # search_visual receives query_vector + top_k + document_id=None (other filters are None).
    mock_milvus.assert_called_once_with(
        query_vector,
        top_k=4,
        document_id=None,
        kb_name=None,
        kb_names=None,
        document_ids=None,
        year=None,
        source_type=None,
        parent_section=None,
        chunk_type=None,
    )


def test_pixelrag_visual_retriever_with_filters():
    """kb_name/year/source_type are forwarded to search_visual."""
    query_vector = [0.2] * 2048

    with (
        patch(
            "eagle_rag.retrievers.pixelrag_visual_retriever.embed_query",
            return_value=query_vector,
        ) as mock_embed,
        patch(
            "eagle_rag.retrievers.pixelrag_visual_retriever.search_visual",
            return_value=[],
        ) as mock_milvus,
    ):
        retriever = PixelRAGVisualRetriever(
            top_k=3, kb_name="finance", year=2025, source_type="financial"
        )
        retriever.retrieve("query")

    mock_embed.assert_called_once_with("query")
    mock_milvus.assert_called_once_with(
        query_vector,
        top_k=6,
        document_id=None,
        kb_name="finance",
        kb_names=None,
        document_ids=None,
        year=2025,
        source_type="financial",
        parent_section=None,
        chunk_type=None,
    )


def test_pixelrag_visual_retriever_with_context_filters():
    """parent_section/chunk_type forwarded to search_visual; metadata propagates to ImageNode."""
    query_vector = [0.3] * 2048
    milvus_results = [
        _visual_result(
            "img_ctx",
            score=0.9,
            chunk_type="table",
            parent_section="3 Model Architecture",
        ),
    ]
    with (
        patch(
            "eagle_rag.retrievers.pixelrag_visual_retriever.embed_query",
            return_value=query_vector,
        ),
        patch(
            "eagle_rag.retrievers.pixelrag_visual_retriever.search_visual",
            return_value=milvus_results,
        ) as mock_milvus,
    ):
        retriever = PixelRAGVisualRetriever(
            top_k=3,
            parent_section="3 Model Architecture",
            chunk_type="table",
        )
        results = retriever.retrieve("对比卷积层和自注意力层复杂度")

    # parent_section/chunk_type forwarded to search_visual.
    mock_milvus.assert_called_once_with(
        query_vector,
        top_k=6,
        document_id=None,
        kb_name=None,
        kb_names=None,
        document_ids=None,
        year=None,
        source_type=None,
        parent_section="3 Model Architecture",
        chunk_type="table",
    )
    # Returned ImageNode metadata carries the new fields.
    assert len(results) == 1
    node = results[0].node
    assert isinstance(node, ImageNode)
    assert node.metadata.get("chunk_type") == "table"
    assert node.metadata.get("parent_section") == "3 Model Architecture"
    assert node.metadata.get("content_summary") == "Transformer architecture diagram"
    assert node.metadata.get("source_chunk_id") == "chunk_img_1"


# ---------------------------------------------------------------------------
# Error degradation — return [] on underlying exception, do not raise
# ---------------------------------------------------------------------------


def test_retriever_empty_on_error():
    """When the underlying layer raises, both retrievers return [] without propagating."""

    # Knowhere: get_text_index raises.
    with patch(
        "eagle_rag.retrievers.knowhere_graph_retriever.get_text_index",
        side_effect=RuntimeError("milvus down"),
    ):
        k_retriever = KnowhereGraphRetriever(top_k=5)
        k_results = k_retriever.retrieve("任意查询")
    assert k_results == []

    # PixelRAG: embed_query raises -> return [].
    with patch(
        "eagle_rag.retrievers.pixelrag_visual_retriever.embed_query",
        side_effect=RuntimeError("embed down"),
    ):
        p_retriever = PixelRAGVisualRetriever(top_k=5)
        p_results = p_retriever.retrieve("任意查询")
    assert p_results == []
