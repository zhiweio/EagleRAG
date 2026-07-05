"""Telemetry tracing tests: trace_span correlation / GenAI attribute truncation / Celery trace
propagation / context isolation.

Covers core behavior of ``eagle_rag.telemetry.tracing`` and ``eagle_rag.telemetry.context``:

- ``trace_span`` cooperates with ``add_open_telemetry_span`` to inject trace_id/span_id into AI
JSONL events.
- ``set_llm_span_attributes`` truncates prompt/completion per truncate config.
- ``send_task_with_trace`` injects the current span context into Celery headers (W3C traceparent),
  so the remote side can resume via ``opentelemetry.propagate.extract``.
- ``bind_context`` is backed by ContextVar and stays isolated across separate ``copy_context`` runs.
"""

from __future__ import annotations

import contextvars
from pathlib import Path
from typing import Any
from unittest.mock import patch

from eagle_rag.config import TelemetrySettings
from eagle_rag.telemetry import (
    bind_context,
    configure_telemetry,
    get_ai_logger,
    get_context,
    get_current_span,
    send_task_with_trace,
    set_llm_span_attributes,
    trace_span,
)
from eagle_rag.telemetry.context import set_enabled as set_context_enabled

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(tmp_path: Path, **overrides: Any) -> Any:
    """Build test settings with tmp log paths (tracing_enabled=False -> NoOp provider)."""

    tel = TelemetrySettings(
        enabled=True,
        ai_log_file=str(tmp_path / "ai_telemetry.jsonl"),
        op_log_file=str(tmp_path / "eagle_rag.log"),
        tracing_enabled=False,
        **overrides,
    )

    class _S:
        telemetry = tel
        celery = type("C", (), {"broker_url": "redis://localhost:6379/0"})()

    return _S()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_trace_span_correlates_ai_logger(tmp_path: Path):
    """AI events inside ``trace_span`` carry trace_id/span_id from ``get_current_span``."""

    import json

    settings = _make_settings(tmp_path)
    configure_telemetry(settings)
    ai_logger = get_ai_logger("router")

    with trace_span("route") as span:
        ai_logger.info("route", q="x")
        # When the span is recording, the active span is the one inside the with block.
        if span is not None and span.is_recording():
            current = get_current_span()
            assert current is span or current.get_span_context() == span.get_span_context()

    ai_log = tmp_path / "ai_telemetry.jsonl"
    assert ai_log.exists()
    lines = ai_log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 1
    data = json.loads(lines[-1])
    assert data["event"] == "route"
    assert data["q"] == "x"
    trace_id = data.get("trace_id")
    span_id = data.get("span_id")
    assert isinstance(trace_id, str) and trace_id
    assert isinstance(span_id, str) and span_id


def test_set_llm_span_attributes_truncates(tmp_path: Path):
    """``set_llm_span_attributes`` truncates prompt/completion per ``prompt_truncate``."""

    settings = _make_settings(tmp_path, prompt_truncate=10, completion_truncate=10)
    configure_telemetry(settings)

    # set_llm_span_attributes reads get_settings().telemetry internally; patch with this test's
    # settings.
    mock_settings = type(
        "S",
        (),
        {"telemetry": settings.telemetry},
    )()

    with trace_span("test") as span:
        assert span is not None and span.is_recording()
        with patch("eagle_rag.config.get_settings", return_value=mock_settings):
            set_llm_span_attributes(
                span,
                system="dashscope",
                model="qwen",
                prompt="a" * 100,
                completion="b" * 100,
            )
        # SDK span attributes are stored in _attributes (BoundedAttributes).
        attrs = getattr(span, "_attributes", None) or getattr(span, "attributes", {})
        prompt_val = attrs.get("gen_ai.prompt")
        completion_val = attrs.get("gen_ai.completion")
        suffix = "...<truncated>"
        assert isinstance(prompt_val, str)
        assert prompt_val.endswith(suffix)
        assert len(prompt_val) <= 10 + len(suffix)
        assert isinstance(completion_val, str)
        assert completion_val.endswith(suffix)
        assert len(completion_val) <= 10 + len(suffix)
        # system/model are not truncated.
        assert attrs.get("gen_ai.system") == "dashscope"
        assert attrs.get("gen_ai.request.model") == "qwen"


def test_celery_trace_propagation(tmp_path: Path):
    """``send_task_with_trace`` injects traceparent so the remote resumes the span context."""

    settings = _make_settings(tmp_path)
    configure_telemetry(settings)

    captured: dict[str, Any] = {}

    def _fake_send_task(*args: Any, **kwargs: Any) -> str:
        captured["headers"] = kwargs.get("headers", {})
        captured["task_name"] = args[0] if args else kwargs.get("name")
        return "task-id"

    with patch("eagle_rag.tasks.celery_app.app.send_task", side_effect=_fake_send_task):
        with trace_span("test"):
            send_task_with_trace("test.task", queue="q", kwargs={})

    headers = captured.get("headers", {})
    assert "traceparent" in headers, "未注入 W3C traceparent"

    # Simulate remote extract: recover span context from headers.
    from opentelemetry.propagate import extract
    from opentelemetry.trace import get_current_span

    ctx = extract(headers)
    span_ctx = get_current_span(ctx).get_span_context()
    assert span_ctx.is_valid, "extract 得到的 span context 无效"


def test_bind_context_isolation():
    """``bind_context`` is backed by ContextVar and isolated across ``copy_context`` runs."""

    set_context_enabled(True)
    results: dict[str, str] = {}

    def _run_in_ctx(session_id: str) -> None:
        bind_context(session_id=session_id)
        results[session_id] = get_context()["session_id"]

    ctx1 = contextvars.copy_context()
    ctx2 = contextvars.copy_context()
    ctx1.run(_run_in_ctx, "s1")
    ctx2.run(_run_in_ctx, "s2")

    assert results["s1"] == "s1"
    assert results["s2"] == "s2"
    # Main context is not polluted.
    assert "session_id" not in get_context()
