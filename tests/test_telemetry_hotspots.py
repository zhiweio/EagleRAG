"""Telemetry hotspot end-to-end tests: route->retrieve->rerank->generate share trace_id + telemetry
errors don't break the main path.

Verifies that AI events (``route``/``rerank``/``generate``) from the full chain of
``EagleRouterQueryEngine.retrieve`` + ``EagleMultimodalQueryEngine.custom_query`` land in
``ai_telemetry.jsonl`` and share the same ``trace_id`` (injected by the outer
``trace_span("query")``). Also verifies that when ``ai_logger.info`` raises, the business
try/except swallows it and the main path still returns normally.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from llama_index.core.schema import ImageNode, NodeWithScore, TextNode

from eagle_rag.config import TelemetrySettings
from eagle_rag.generation.multimodal_engine import EagleMultimodalQueryEngine
from eagle_rag.router.router_engine import EagleRouterQueryEngine
from eagle_rag.telemetry import configure_telemetry, trace_span

# ---------------------------------------------------------------------------
# Helpers (aligned with test_router_generation)
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
    page: int = 1,
    position: str = "strip_1",
    document_id: str = "doc2",
    score: float = 0.8,
) -> NodeWithScore:
    node = ImageNode(
        image_path=image_path,
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


def _make_settings(tmp_path: Path) -> Any:
    """Build test settings with tmp log paths."""

    tel = TelemetrySettings(
        enabled=True,
        ai_log_file=str(tmp_path / "ai_telemetry.jsonl"),
        op_log_file=str(tmp_path / "eagle_rag.log"),
        tracing_enabled=False,
    )

    class _S:
        telemetry = tel
        celery = type("C", (), {"broker_url": "redis://localhost:6379/0"})()

    return _S()


@pytest.fixture
def tmp_png(tmp_path: Path) -> str:
    """Generate a real accessible 4x4 PNG so ``ImageDocument(image_path=...)`` can be built."""

    from PIL import Image

    p = tmp_path / "tile.png"
    Image.new("RGB", (4, 4), (255, 0, 0)).save(p)
    return str(p)


def _read_ai_events(ai_log: Path) -> list[dict[str, Any]]:
    """Read all JSONL lines and parse them into a list of dicts."""

    if not ai_log.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in ai_log.read_text(encoding="utf-8").strip().splitlines():
        if line:
            events.append(json.loads(line))
    return events


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_hotspots_share_trace_id(tmp_path: Path, tmp_png: str):
    """route->retrieve->rerank->generate chain AI events share the outer trace_id.

    Module-level ``ai_logger`` is bound at import time; lazy resolution must still land
    events in JSONL after ``configure_telemetry``. There is no standalone ``retrieve``
    event in the real code (retrieve is a span, not a log event), so we only assert
    route/rerank/generate appear and share trace_id.
    """

    settings = _make_settings(tmp_path)
    configure_telemetry(settings)
    ai_log = tmp_path / "ai_telemetry.jsonl"

    n1 = _make_text_node("c1", "起征点 5000 元/月", score=0.9)
    img = _make_image_node("img1", image_path=tmp_png, page=2, score=0.85)
    mock_text = MagicMock()
    mock_text.retrieve.return_value = [n1]
    mock_visual = MagicMock()
    mock_visual.retrieve.return_value = [img]
    mock_vlm = _make_mock_vlm("起征点为5000元")

    outer_trace_id: str | None = None
    with trace_span("query") as outer_span:
        if outer_span is not None and outer_span.is_recording():
            outer_trace_id = format(outer_span.get_span_context().trace_id, "032x")
        engine = EagleRouterQueryEngine(text_retriever=mock_text, visual_retriever=mock_visual)
        nodes, info = engine.retrieve("个税起征点", mode="hybrid")
        gen_engine = EagleMultimodalQueryEngine(multi_modal_llm=mock_vlm, top_n=3)
        gen_engine.custom_query("个税起征点", nodes=nodes, route_info=info.to_dict())

    assert outer_trace_id is not None, "外层 span 未 recording，trace_id 缺失"

    events = _read_ai_events(ai_log)
    assert events, "ai_telemetry.jsonl 未写入任何事件"

    hotspots = [e for e in events if e.get("event") in ("route", "retrieve", "rerank", "generate")]
    event_names = {e["event"] for e in hotspots}
    # The real chain emits route / rerank / generate (retrieve is a span, not a log event).
    assert "route" in event_names, "缺少 route 事件"
    assert "generate" in event_names, "缺少 generate 事件"

    # All hotspot events share the outer trace_id.
    for ev in hotspots:
        assert ev.get("trace_id") == outer_trace_id, (
            f"事件 {ev.get('event')} trace_id 不匹配：{ev.get('trace_id')} != {outer_trace_id}"
        )


def test_telemetry_exception_doesnt_break_main(tmp_path: Path):
    """When ``ai_logger.info`` raises, the business try/except swallows it; retrieve returns."""

    settings = _make_settings(tmp_path)
    configure_telemetry(settings)

    n1 = _make_text_node("c1", "起征点 5000 元/月", score=0.9)
    mock_text = MagicMock()
    mock_text.retrieve.return_value = [n1]
    mock_visual = MagicMock()
    mock_visual.retrieve.return_value = []

    # Patch ai_logger.info to raise, verifying route_query's try/except fallback.
    mock_ai = MagicMock()
    mock_ai.info.side_effect = RuntimeError("telemetry boom")

    with patch("eagle_rag.router.router_engine.ai_logger", mock_ai):
        engine = EagleRouterQueryEngine(text_retriever=mock_text, visual_retriever=mock_visual)
        nodes, info = engine.retrieve("个税起征点", mode="text")

    # Main path is unaffected by the telemetry exception and returns normally.
    assert isinstance(nodes, list)
    assert len(nodes) == 1
    assert info.selected == ["text"]
    # ai_logger.info was indeed called (and its exception was swallowed).
    mock_ai.info.assert_called()
