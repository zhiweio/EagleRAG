"""Telemetry log routing tests: structlog JSONL / loguru operational / stdlib intercept / disabled
fallback.

Covers core behavior of ``eagle_rag.telemetry.logging_setup``:

- ``configure_logging`` is idempotent (repeated calls do not re-register loguru sinks).
- ``get_ai_logger`` writes to ``ai_telemetry.jsonl`` (structlog JSONRenderer + RotatingFileHandler).
- ``get_logger`` writes operational logs (loguru file sink) without polluting AI JSONL.
- When ``telemetry.enabled=false``, ``get_*_logger`` falls back to stdlib ``logging.Logger``.
- ``_InterceptHandler`` routes stdlib logging (e.g. uvicorn.error) into the loguru file sink.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from eagle_rag.config import TelemetrySettings
from eagle_rag.telemetry import configure_telemetry, get_ai_logger, get_logger
from eagle_rag.telemetry.logging_setup import configure_logging

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(tmp_path: Path, **overrides: Any) -> Any:
    """Build test settings with tmp log paths (telemetry.enabled=True by default)."""

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


def _make_disabled_settings(tmp_path: Path) -> Any:
    """Build test settings with telemetry.enabled=False."""

    tel = TelemetrySettings(
        enabled=False,
        ai_log_file=str(tmp_path / "ai_telemetry.jsonl"),
        op_log_file=str(tmp_path / "eagle_rag.log"),
    )

    class _S:
        telemetry = tel
        celery = type("C", (), {"broker_url": "redis://localhost:6379/0"})()

    return _S()


def _wait_for_content(path: Path, expected: str, timeout: float = 2.0) -> bool:
    """Poll file until it contains ``expected`` (loguru ``enqueue=True`` writes asynchronously)."""

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            try:
                if expected in path.read_text(encoding="utf-8"):
                    return True
            except OSError:
                pass
        time.sleep(0.05)
    return False


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_configure_logging_idempotent(tmp_path: Path):
    """``configure_logging`` does not re-register loguru sinks on repeat calls (handler count)."""

    from loguru import logger

    settings = _make_settings(tmp_path)
    configure_logging(settings)
    before = len(logger._core.handlers)
    # Second call: _configured=True returns early, handler count unchanged.
    configure_logging(settings)
    after = len(logger._core.handlers)
    assert before == after
    # stderr + rotating file + redis pubsub = three sinks.
    assert after >= 3


def test_ai_logger_writes_jsonl(tmp_path: Path):
    """``get_ai_logger`` writes JSONL with event/query fields and trace_id."""

    settings = _make_settings(tmp_path)
    configure_telemetry(settings)
    get_ai_logger("router").info("route", query="q")

    ai_log = tmp_path / "ai_telemetry.jsonl"
    assert ai_log.exists()
    lines = ai_log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) >= 1
    data = json.loads(lines[-1])
    assert data["event"] == "route"
    assert data["query"] == "q"
    # add_open_telemetry_span injects trace_id (NoOp also has a fallback).
    assert data.get("trace_id")


def test_operational_logger_not_in_jsonl(tmp_path: Path):
    """Operational logger writes to ``eagle_rag.log`` but not to ``ai_telemetry.jsonl``."""

    settings = _make_settings(tmp_path)
    configure_telemetry(settings)
    get_logger("ops").warning("op message marker")

    ai_log = tmp_path / "ai_telemetry.jsonl"
    op_log = tmp_path / "eagle_rag.log"
    # loguru file sink uses enqueue=True for async writes; poll until flushed.
    assert _wait_for_content(op_log, "op message marker"), "运维日志未落盘"
    # AI JSONL must not contain operational messages.
    if ai_log.exists():
        assert "op message marker" not in ai_log.read_text(encoding="utf-8")


def test_telemetry_disabled_fallback(tmp_path: Path):
    """With ``telemetry.enabled=False``, ``get_*_logger`` falls back to stdlib with no JSONL."""

    configure_telemetry(_make_disabled_settings(tmp_path))
    op_logger = get_logger("x")
    ai_logger = get_ai_logger("x")
    assert isinstance(op_logger, logging.Logger)
    assert isinstance(ai_logger._resolve(), logging.Logger)
    ai_logger.info("ignored")
    # Without structlog/loguru configured, no JSONL file should be created.
    assert not (tmp_path / "ai_telemetry.jsonl").exists()


def test_module_level_ai_logger_writes_after_configure(tmp_path: Path):
    """Import-time ``get_ai_logger`` binding still writes JSONL after ``configure_telemetry``."""

    early_logger = get_ai_logger("eagle_rag.router.router_engine")
    settings = _make_settings(tmp_path)
    configure_telemetry(settings)
    early_logger.info("route", query="q")

    ai_log = tmp_path / "ai_telemetry.jsonl"
    assert ai_log.exists()
    data = json.loads(ai_log.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert data["event"] == "route"
    assert data["query"] == "q"


def test_intercept_handler_captures_stdlib(tmp_path: Path):
    """stdlib logging is routed into the loguru file sink via ``_InterceptHandler``."""

    settings = _make_settings(tmp_path)
    configure_telemetry(settings)
    # Clear uvicorn.error's own handlers so propagation reaches root (which has InterceptHandler
    # installed).
    uv_logger = logging.getLogger("uvicorn.error")
    uv_logger.handlers = []
    uv_logger.info("test intercept marker")

    op_log = tmp_path / "eagle_rag.log"
    assert _wait_for_content(op_log, "test intercept marker"), "stdlib 日志未汇入 loguru"
