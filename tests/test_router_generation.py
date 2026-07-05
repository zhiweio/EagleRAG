"""Router and multimodal generation integration tests.

With mock retrievers (``KnowhereGraphRetriever``/``PixelRAGVisualRetriever`` instance
``retrieve``) and an injected mock VLM (``complete``), verifies:

- ``route_query`` heuristics: policy -> text, financial -> visual, ``hybrid`` -> both.
- ``EagleRouterQueryEngine.retrieve`` calls the appropriate retriever per routing decision.
- ``EagleMultimodalQueryEngine.custom_query`` runs the split/rerank/VLM/steps flow;
  ``sources`` contains text path/type and image image_id/image_path, and ``steps`` has all four
  phases.
- Chinese/English queries get prompt constraints in the matching language.
- ``kb_name`` is passed through to ``route_query`` return value and default-constructed retrievers.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from llama_index.core.schema import ImageDocument, ImageNode, NodeWithScore, TextNode

from eagle_rag.generation.multimodal_engine import EagleMultimodalQueryEngine
from eagle_rag.router import RouteContext
from eagle_rag.router.router_engine import EagleRouterQueryEngine, route_query

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_text_node(
    node_id: str,
    text: str,
    *,
    path: str = "财政/个税",
    level: str = "section",
    document_id: str = "doc1",
    score: float = 0.9,
) -> NodeWithScore:
    node = TextNode(
        id_=node_id,
        text=text,
        metadata={
            "path": path,
            "level": level,
            "document_id": document_id,
            "source_type": "policy",
        },
    )
    return NodeWithScore(node=node, score=score)


def _make_image_node(
    image_id: str,
    *,
    image_path: str | None = None,
    image_url: str | None = None,
    page: int = 1,
    position: str = "strip_1",
    document_id: str = "doc2",
    score: float = 0.8,
) -> NodeWithScore:
    node = ImageNode(
        image_path=image_path,
        image_url=image_url,
        metadata={
            "image_id": image_id,
            "document_id": document_id,
            "page": page,
            "position": position,
        },
    )
    return NodeWithScore(node=node, score=score)


class _FakeCompletionResponse:
    """Fake ``CompletionResponse`` (only ``.text`` is needed)."""

    def __init__(self, text: str) -> None:
        self.text = text


def _make_mock_vlm(answer: str = "起征点为5000元") -> MagicMock:
    vlm = MagicMock()
    vlm.complete.return_value = _FakeCompletionResponse(answer)
    return vlm


@pytest.fixture
def tmp_png(tmp_path):
    """Generate a real accessible 4x4 PNG so ``ImageDocument(image_path=...)`` can be built."""
    from PIL import Image

    p = tmp_path / "tile.png"
    Image.new("RGB", (4, 4), (255, 0, 0)).save(p)
    return str(p)


# ---------------------------------------------------------------------------
# route_query heuristics + EagleRouterQueryEngine.retrieve
# ---------------------------------------------------------------------------


def test_route_policy_query_text():
    """Policy queries route to text; retrieve calls only the text retriever."""
    r = route_query(RouteContext(query="个税起征点是多少？"))
    assert "text" in r.selected
    assert "visual" not in r.selected

    n1 = _make_text_node("c1", "起征点 5000 元/月", score=0.9)
    n2 = _make_text_node("c2", "专项附加扣除", score=0.8)
    mock_text = MagicMock()
    mock_text.retrieve.return_value = [n1, n2]
    mock_visual = MagicMock()
    mock_visual.retrieve.return_value = []

    engine = EagleRouterQueryEngine(text_retriever=mock_text, visual_retriever=mock_visual)
    nodes, info = engine.retrieve("个税起征点是多少？")

    assert info.selected == ["text"]
    assert len(nodes) == 2
    # Only the text retriever is called; the visual retriever is not.
    mock_text.retrieve.assert_called_once_with("个税起征点是多少？")
    mock_visual.retrieve.assert_not_called()


def test_route_financial_query_visual():
    """Financial queries (containing '资产负债') route to visual; only visual retriever called."""
    r = route_query(RouteContext(query="看这张资产负债表，总资产是多少？"))
    assert "visual" in r.selected

    img = _make_image_node("img1", image_path="/data/img1.png", score=0.92)
    mock_text = MagicMock()
    mock_text.retrieve.return_value = []
    mock_visual = MagicMock()
    mock_visual.retrieve.return_value = [img]

    engine = EagleRouterQueryEngine(text_retriever=mock_text, visual_retriever=mock_visual)
    nodes, info = engine.retrieve("看这张资产负债表，总资产是多少？")

    assert info.selected == ["visual"]
    assert len(nodes) == 1
    mock_visual.retrieve.assert_called_once_with(
        "看这张资产负债表，总资产是多少？",
        query_image_bytes=None,
    )
    mock_text.retrieve.assert_not_called()


def test_route_diagram_query_hybrid():
    """Diagram + explanation queries route to hybrid (text + visual)."""
    r = route_query(RouteContext(query="展示 Transformer 架构图，并解释编码器和解码器的结构"))
    assert "text" in r.selected
    assert "visual" in r.selected


def test_llm_intent_selector_parses_hybrid_word():
    """LLM returning the single word ``hybrid`` must select both retrievers."""
    from eagle_rag.router.selectors import LLMIntentSelector

    llm = MagicMock()
    llm.complete.return_value = _FakeCompletionResponse("hybrid")
    sel = LLMIntentSelector(
        llm=llm,
        prompt_template="query: {query}",
        model_name="test",
        enabled=True,
    )
    decision = sel.select(RouteContext(query="show diagram and explain"))
    assert decision is not None
    assert decision.selected == ["text", "visual"]
    assert decision.selector == "llm"


def test_nodes_to_image_documents_minio_url_fallback():
    """Presigned MinIO URLs fall back to ``get_image_bytes`` via ``image_id``."""
    img = _make_image_node(
        "img-minio",
        image_path="http://minio:9000/eagle-rag/doc/img.png?signed=1",
        image_url="http://minio:9000/eagle-rag/doc/img.png?signed=1",
    )
    with patch(
        "eagle_rag.images.store.get_image_bytes",
        return_value=b"\x89PNG\r\n",
    ) as mock_bytes:
        docs = EagleMultimodalQueryEngine._nodes_to_image_documents([img])
    assert len(docs) == 1
    mock_bytes.assert_called_once_with("img-minio")


def test_image_message_payload_accepts_image_document_base64_string():
    """``ImageDocument(image=bytes)`` stores base64 text; must not re-encode as bytes."""
    from eagle_rag.generation.multimodal_engine import _DashScopeVLM, _image_message_payload

    doc = ImageDocument(image=b"\xff\xd8\xff\xe0fakejpeg")
    # LlamaIndex normalises bytes to a base64 string on the ``image`` field.
    assert isinstance(doc.image, str)
    payload = _image_message_payload(doc)
    assert payload is not None
    assert payload["image"].startswith("data:image/jpeg;base64,")

    msgs = _DashScopeVLM(model_name="test", api_key="k")._build_messages("hi", [doc])
    assert msgs[0]["content"][0]["image"].startswith("data:image/")


def test_extract_message_text_stream_and_complete_formats():
    """Streaming uses plain strings; non-streaming uses ``[{"text": ...}]``."""
    from eagle_rag.generation.multimodal_engine import _extract_message_text, _stream_text_delta

    assert _extract_message_text("增量文本") == "增量文本"
    assert _extract_message_text([{"text": "完整答案"}]) == "完整答案"
    assert _extract_message_text(None) == ""

    full, delta = _stream_text_delta("", "基于", incremental=True)
    assert full == "基于" and delta == "基于"
    full, delta = _stream_text_delta(full, "基于 Power Platform", incremental=True)
    assert full == "基于 Power Platform" and delta == " Power Platform"


def test_dashscope_vlm_stream_complete_parses_string_chunks():
    """``stream_complete`` must yield deltas from string ``message.content`` chunks."""
    from eagle_rag.generation.multimodal_engine import _DashScopeVLM

    class _Msg:
        def __init__(self, content):
            self.content = content

    class _Choice:
        def __init__(self, content):
            self.message = _Msg(content)

    class _Output:
        def __init__(self, content):
            self.choices = [_Choice(content)]

    class _Resp:
        def __init__(self, content):
            self.status_code = 200
            self.output = _Output(content)
            self.usage = None

    vlm = _DashScopeVLM(model_name="qwen-vl-max", api_key="k")
    with patch("dashscope.MultiModalConversation.call") as mock_call:
        mock_call.return_value = iter(
            [
                _Resp("基于"),
                _Resp("基于 Power Platform"),
            ]
        )
        chunks = list(vlm.stream_complete("hi", image_documents=[]))

    assert [c.delta for c in chunks] == ["基于", " Power Platform"]
    assert chunks[-1].text == "基于 Power Platform"


def test_invoke_vlm_stream_falls_back_when_stream_empty():
    """Empty ``stream_complete`` output falls back to ``complete()``."""
    vlm = MagicMock()
    vlm.stream_complete.return_value = iter([])
    vlm.complete.return_value = MagicMock(text="非流式答案")

    engine = EagleMultimodalQueryEngine(multi_modal_llm=vlm)
    parts = list(engine._invoke_vlm_stream("问题", []))

    assert parts == ["非流式答案"]
    vlm.complete.assert_called_once()


def test_route_hybrid():
    """hybrid mode calls both retrievers."""
    r = route_query(RouteContext(query="任意查询", mode="hybrid"))
    assert "text" in r.selected
    assert "visual" in r.selected

    n1 = _make_text_node("c1", "政策文本片段", score=0.7)
    img = _make_image_node("img1", image_path="/data/img1.png", score=0.6)
    mock_text = MagicMock()
    mock_text.retrieve.return_value = [n1]
    mock_visual = MagicMock()
    mock_visual.retrieve.return_value = [img]

    engine = EagleRouterQueryEngine(text_retriever=mock_text, visual_retriever=mock_visual)
    nodes, info = engine.retrieve("任意查询", mode="hybrid")

    assert info.selected == ["text", "visual"]
    # Both retrievers are called.
    mock_text.retrieve.assert_called_once_with("任意查询")
    mock_visual.retrieve.assert_called_once_with("任意查询", query_image_bytes=None)
    # After merge: 1 text + 1 image.
    assert len(nodes) == 2


def test_router_kb_name_passthrough():
    """``kb_name`` is passed through to ``route_query`` return value and default-constructed
    retrievers."""
    # route_query return dict contains kb_name.
    r = route_query(RouteContext(query="测试查询", kb_name="pharma"))
    assert r.kb_name == "pharma"

    # EagleRouterQueryEngine passes kb_name through when default-constructing retrievers.
    with (
        patch("eagle_rag.router.router_engine.KnowhereGraphRetriever") as mock_kr,
        patch("eagle_rag.router.router_engine.PixelRAGVisualRetriever") as mock_pr,
    ):
        mock_kr.return_value = MagicMock()
        mock_pr.return_value = MagicMock()
        EagleRouterQueryEngine(kb_name="pharma")
        mock_kr.assert_called_once_with(top_k=5, kb_name="pharma")
        mock_pr.assert_called_once_with(top_k=5, kb_name="pharma")


# ---------------------------------------------------------------------------
# EagleMultimodalQueryEngine.custom_query
# ---------------------------------------------------------------------------


def test_generation_with_mock_vlm(tmp_png):
    """Mock VLM generation: split/rerank/VLM/steps flow; sources and steps structure is correct."""
    t1 = _make_text_node("c1", "起征点 5000 元/月", path="财政/个税", score=0.9)
    t2 = _make_text_node("c2", "专项附加扣除", path="财政/个税", score=0.7)
    img = _make_image_node("img1", image_path=tmp_png, page=2, position="strip_1", score=0.85)
    nodes = [t1, t2, img]

    vlm = _make_mock_vlm("起征点为5000元")
    engine = EagleMultimodalQueryEngine(multi_modal_llm=vlm, top_n=3)

    route_info = {"mode": "auto", "selected": ["text", "visual"], "reason": "测试路由"}
    result = engine.custom_query("个税起征点是多少？", nodes=nodes, route_info=route_info)

    # answer comes from the mock VLM.
    assert result["answer"] == "起征点为5000元"
    vlm.complete.assert_called_once()
    # image_documents contains 1 accessible image.
    _, kwargs = vlm.complete.call_args
    assert kwargs.get("image_documents") is not None
    assert len(kwargs["image_documents"]) == 1

    # sources.text has path; sources.image has image_id.
    assert "sources" in result
    text_src = result["sources"]["text"]
    image_src = result["sources"]["image"]
    assert len(text_src) == 2
    assert all("path" in s for s in text_src)
    assert all(s["type"] == "text" for s in text_src)
    assert len(image_src) == 1
    assert image_src[0]["image_id"] == "img1"
    assert image_src[0]["type"] == "image"
    assert image_src[0]["image_path"] == tmp_png
    assert image_src[0]["page"] == 2

    # route is passed through.
    assert result["route"] == route_info

    # steps has all four phases in the correct order.
    steps = result["steps"]
    assert [s["name"] for s in steps] == ["route", "recall", "rerank", "generate"]
    # recall phase records the original recall counts.
    assert steps[1]["text_count"] == 2
    assert steps[1]["visual_count"] == 1
    # rerank phase records the top list and kept counts.
    assert steps[2]["text_kept"] == 2
    assert steps[2]["visual_kept"] == 1
    assert "财政/个税" in steps[2]["text_top"]
    assert "img1" in steps[2]["visual_top"]
    # generate phase records model/language/image doc count.
    assert steps[3]["language"] == "zh"
    assert steps[3]["image_docs_count"] == 1


def test_language_following():
    """Chinese queries produce prompts containing '中文'; English queries contain 'English'."""
    # _detect_language: CJK -> zh, otherwise -> en.
    assert EagleMultimodalQueryEngine._detect_language("个税起征点") == "zh"
    assert EagleMultimodalQueryEngine._detect_language("tax threshold") == "en"

    # _build_prompt: language constraint text.
    zh_prompt = EagleMultimodalQueryEngine._build_prompt("个税起征点", [], [], [], "zh")
    en_prompt = EagleMultimodalQueryEngine._build_prompt("tax threshold", [], [], [], "en")
    assert "中文" in zh_prompt
    assert "English" in en_prompt

    # End-to-end: custom_query infers language from the query and feeds it into the prompt.
    vlm_zh = _make_mock_vlm("中文回答")
    engine = EagleMultimodalQueryEngine(multi_modal_llm=vlm_zh)
    engine.custom_query("个税起征点是多少？", nodes=[], route_info=None)
    _, kwargs_zh = vlm_zh.complete.call_args
    assert "中文" in kwargs_zh["prompt"]

    vlm_en = _make_mock_vlm("english answer")
    engine_en = EagleMultimodalQueryEngine(multi_modal_llm=vlm_en)
    engine_en.custom_query("What is the tax threshold?", nodes=[], route_info=None)
    _, kwargs_en = vlm_en.complete.call_args
    assert "English" in kwargs_en["prompt"]


def test_search_classifies_image_nodes_as_visual(tmp_png):
    """``search()`` must not treat ``ImageNode`` (subclass of ``TextNode``) as text."""
    from eagle_rag.router.models import RouteDecision

    img1 = _make_image_node("img-a", image_path=tmp_png, document_id="doc-vis", score=0.32)
    img2 = _make_image_node("img-b", image_path=tmp_png, document_id="doc-vis", score=0.28)
    decision = RouteDecision(
        mode="auto",
        selected=["visual"],
        reason="LLM:visual",
        kb_name="test",
        selector="llm",
    )

    engine = EagleRouterQueryEngine()
    with patch.object(EagleRouterQueryEngine, "retrieve", return_value=([img1, img2], decision)):
        result = engine.search("Transformer architecture figure", kb_name="test")

    assert result["route"]["selected"] == ["visual"]
    assert result["sources"]["text"] == []
    assert len(result["sources"]["image"]) == 2
    assert result["sources"]["image"][0]["type"] == "image"
    assert result["sources"]["image"][0]["image_id"] == "img-a"
    assert result["sources"]["image"][0]["image_path"] == tmp_png
    assert result["steps"][1] == {"name": "recall", "text_count": 0, "visual_count": 2}


def test_search_stream_yields_step_sources_done(tmp_png):
    """``search_stream()`` emits route/recall steps, sources, and done (no tokens)."""
    from eagle_rag.router.models import RouteDecision

    img = _make_image_node("img-a", image_path=tmp_png, score=0.32)
    decision = RouteDecision(
        mode="auto",
        selected=["visual"],
        reason="LLM:visual",
        kb_name="test",
        selector="llm",
    )
    engine = EagleRouterQueryEngine()
    with (
        patch.object(EagleRouterQueryEngine, "_route_decision", return_value=decision),
        patch.object(EagleRouterQueryEngine, "_fetch_nodes", return_value=[img]),
    ):
        events = list(engine.search_stream("figure", kb_name="test"))

    assert [e["event"] for e in events] == ["step", "step", "sources", "done"]
    assert events[0]["data"]["name"] == "route"
    assert events[1]["data"]["name"] == "recall"
    assert events[2]["data"]["image"][0]["image_id"] == "img-a"
    assert events[3]["data"]["route"]["selected"] == ["visual"]
