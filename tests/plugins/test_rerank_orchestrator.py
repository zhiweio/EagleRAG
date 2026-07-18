"""Post-RRF rerank integration tests.

Verifies that ``rerank_merged`` applies the DashScope qwen3-rerank to text nodes
after RRF fusion, passes visual nodes through unchanged, and degrades gracefully
to the RRF order when the rerank service fails.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from llama_index.core.schema import ImageNode, NodeWithScore, TextNode

from eagle_rag.router.rerank_fusion import rerank_merged


def _make_text_node(node_id: str, text: str, score: float = 0.5) -> NodeWithScore:
    node = TextNode(id_=node_id, text=text)
    return NodeWithScore(node=node, score=score)


def _make_image_node(image_id: str, score: float = 0.4) -> NodeWithScore:
    node = ImageNode(image_path=f"s3://bucket/{image_id}.png")
    return NodeWithScore(node=node, score=score)


class _FakeReranker:
    """Fake reranker that reorders nodes by a provided score map."""

    def __init__(self, score_map: dict[str, float]) -> None:
        self._score_map = score_map
        self.calls: list[str] = []

    def postprocess_nodes(
        self, nodes: list[NodeWithScore], *, query_str: str
    ) -> list[NodeWithScore]:
        self.calls.append(query_str)
        scored = []
        for nws in nodes:
            text = nws.node.get_content() or ""
            new_score = self._score_map.get(text, 0.0)
            scored.append(NodeWithScore(node=nws.node, score=new_score))
        return sorted(scored, key=lambda n: n.score or 0.0, reverse=True)


def test_rerank_merged_reorders_text_nodes() -> None:
    """Rerank reorders text nodes by relevance score; visual passes through."""
    nodes = [
        _make_text_node("t1", "low relevance", score=0.9),
        _make_text_node("t2", "high relevance", score=0.1),
        _make_image_node("img1", score=0.4),
    ]
    reranker = _FakeReranker({"low relevance": 0.1, "high relevance": 0.95})
    with patch(
        "eagle_rag.generation.multimodal_engine._default_text_reranker",
        return_value=reranker,
    ):
        result = rerank_merged(nodes, query="query", top_n=5)

    text_contents = [n.node.get_content() for n in result if not isinstance(n.node, ImageNode)]
    assert text_contents[0] == "high relevance"
    assert text_contents[1] == "low relevance"
    # Image node appended at the end unchanged.
    image_nodes = [n for n in result if isinstance(n.node, ImageNode)]
    assert len(image_nodes) == 1


def test_rerank_merged_respects_top_n() -> None:
    nodes = [_make_text_node(f"t{i}", f"doc{i}") for i in range(5)]
    score_map = {f"doc{i}": float(5 - i) for i in range(5)}
    reranker = _FakeReranker(score_map)
    with patch(
        "eagle_rag.generation.multimodal_engine._default_text_reranker",
        return_value=reranker,
    ):
        result = rerank_merged(nodes, query="q", top_n=3)
    text_nodes = [n for n in result if not isinstance(n.node, ImageNode)]
    assert len(text_nodes) == 3


def test_rerank_merged_no_reranker_returns_original_order() -> None:
    """When no reranker is available, the original RRF order is preserved."""
    nodes = [
        _make_text_node("t1", "first", score=0.9),
        _make_text_node("t2", "second", score=0.8),
    ]
    with patch(
        "eagle_rag.generation.multimodal_engine._default_text_reranker",
        return_value=None,
    ):
        result = rerank_merged(nodes, query="q", top_n=5)
    assert [n.node.get_content() for n in result] == ["first", "second"]


def test_rerank_merged_reranker_exception_returns_original_order() -> None:
    """A reranker exception must not break retrieval; fall back to RRF order."""
    nodes = [_make_text_node("t1", "only")]

    class _ExplodingReranker:
        def postprocess_nodes(self, *args, **kwargs):
            raise RuntimeError("rerank service down")

    with patch(
        "eagle_rag.generation.multimodal_engine._default_text_reranker",
        return_value=_ExplodingReranker(),
    ):
        result = rerank_merged(nodes, query="q", top_n=5)
    assert len(result) == 1
    assert result[0].node.get_content() == "only"


def test_rerank_merged_empty_text_returns_original() -> None:
    """Only image nodes -> no rerank call, original list returned."""
    nodes = [_make_image_node("img1"), _make_image_node("img2")]
    with patch(
        "eagle_rag.generation.multimodal_engine._default_text_reranker",
        return_value=MagicMock(),
    ) as mock_reranker:
        result = rerank_merged(nodes, query="q", top_n=5)
    mock_reranker.assert_not_called()
    assert len(result) == 2
