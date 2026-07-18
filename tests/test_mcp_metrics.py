"""MCP Prometheus metrics (``eagle_rag.metrics``) tests.

Verifies metric definitions, HTTP endpoints, helpers, decorators, and tool integration:

- **Metric definitions**: ``MCP_TOOL_CALLS`` / ``MCP_TOOL_DURATION`` / ``MCP_ACTIVE_REQUESTS`` /
  ``MCP_CIRCUIT_STATE`` have correct names and labels.
- **HTTP endpoints**: ``/metrics`` returns Prometheus text format (correct ``Content-Type``);
  ``/health`` returns ``{"status": "ok"}`` JSON with HTTP 200.
- **Helpers**: ``update_circuit_state`` / ``record_tool_call`` / ``track_active`` update the
  corresponding metrics correctly.
- **Decorator**: ``with_metrics`` records counter + histogram + gauge correctly across the
  success / error / circuit_open / cache_hit paths.
- **Circuit breaker listener**: ``CircuitStateMetricsListener`` updates the
  ``mcp_circuit_state{tool}`` gauge on breaker state changes.
- **Tool function integration**: invoking ``mcp_server`` tool functions increments metric counters.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from prometheus_client import REGISTRY
from starlette.testclient import TestClient

# ---------------------------------------------------------------------------
# Isolation: override conftest.py autouse fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_telemetry_state():
    yield


@pytest.fixture(autouse=True)
def _kb_registered():
    yield


# ---------------------------------------------------------------------------
# Helper: read current Prometheus metric value
# ---------------------------------------------------------------------------


def _get_sample_value(metric_name: str, labels: dict[str, str] | None = None) -> float | None:
    """Read the current value of the given metric from ``prometheus_client.REGISTRY``.

    Args:
        metric_name: Sample name (e.g. ``"mcp_tool_calls_total"``,
            ``"mcp_tool_duration_seconds_count"``).
        labels: Label key/value pairs that must match exactly
            (e.g. ``{"tool": "query", "status": "success"}``).

    Returns:
        The current metric value, or ``None`` if no matching sample is found.
    """
    for metric in REGISTRY.collect():
        for sample in metric.samples:
            if sample.name == metric_name:
                if labels is None or all(sample.labels.get(k) == v for k, v in labels.items()):
                    return sample.value
    return None


# ---------------------------------------------------------------------------
# 1. Metric definitions
# ---------------------------------------------------------------------------


def test_mcp_tool_calls_counter_defined() -> None:
    """``MCP_TOOL_CALLS`` is a Counter with ``tool`` / ``status`` labels."""
    from eagle_rag.metrics import MCP_TOOL_CALLS

    assert MCP_TOOL_CALLS._type == "counter"
    assert "tool" in MCP_TOOL_CALLS._labelnames
    assert "status" in MCP_TOOL_CALLS._labelnames


def test_mcp_tool_duration_histogram_defined() -> None:
    """``MCP_TOOL_DURATION`` is a Histogram with a ``tool`` label."""
    from eagle_rag.metrics import MCP_TOOL_DURATION

    assert MCP_TOOL_DURATION._type == "histogram"
    assert "tool" in MCP_TOOL_DURATION._labelnames


def test_mcp_active_requests_gauge_defined() -> None:
    """``MCP_ACTIVE_REQUESTS`` is a Gauge with a ``tool`` label."""
    from eagle_rag.metrics import MCP_ACTIVE_REQUESTS

    assert MCP_ACTIVE_REQUESTS._type == "gauge"
    assert "tool" in MCP_ACTIVE_REQUESTS._labelnames


def test_mcp_circuit_state_gauge_defined() -> None:
    """``MCP_CIRCUIT_STATE`` is a Gauge with a ``tool`` label."""
    from eagle_rag.metrics import MCP_CIRCUIT_STATE

    assert MCP_CIRCUIT_STATE._type == "gauge"
    assert "tool" in MCP_CIRCUIT_STATE._labelnames


# ---------------------------------------------------------------------------
# 2. HTTP endpoints
# ---------------------------------------------------------------------------


def test_metrics_handler_returns_prometheus_format() -> None:
    """``/metrics`` returns Prometheus text format with ``text/plain`` in ``Content-Type``."""
    from eagle_rag.metrics import metrics_app

    client = TestClient(metrics_app)
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
    # Output should contain registered metric names.
    body = resp.text
    assert "mcp_tool_calls_total" in body or "mcp_tool_duration_seconds" in body


def test_health_handler_returns_ok_json() -> None:
    """``/health`` returns ``{"status": "ok"}`` JSON with HTTP 200."""
    from eagle_rag.metrics import metrics_app

    client = TestClient(metrics_app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_metrics_app_serves_both_endpoints() -> None:
    """``metrics_app`` serves both ``/metrics`` and ``/health``."""
    from eagle_rag.metrics import metrics_app

    client = TestClient(metrics_app)
    assert client.get("/metrics").status_code == 200
    assert client.get("/health").status_code == 200


# ---------------------------------------------------------------------------
# 3. Helpers
# ---------------------------------------------------------------------------


def test_update_circuit_state_sets_gauge_value() -> None:
    """``update_circuit_state`` sets the gauge to closed=0 / half-open=1 / open=2."""
    from eagle_rag.metrics import update_circuit_state

    update_circuit_state("test_tool", "closed")
    assert _get_sample_value("mcp_circuit_state", {"tool": "test_tool"}) == 0.0

    update_circuit_state("test_tool", "half-open")
    assert _get_sample_value("mcp_circuit_state", {"tool": "test_tool"}) == 1.0

    update_circuit_state("test_tool", "open")
    assert _get_sample_value("mcp_circuit_state", {"tool": "test_tool"}) == 2.0


def test_record_tool_call_increments_counter() -> None:
    """``record_tool_call`` increments ``mcp_tool_calls_total{tool,status}``."""
    from eagle_rag.metrics import record_tool_call

    before = _get_sample_value("mcp_tool_calls_total", {"tool": "test_record", "status": "success"})
    before = before or 0.0
    record_tool_call("test_record", "success", 0.05)
    after = _get_sample_value("mcp_tool_calls_total", {"tool": "test_record", "status": "success"})
    assert after == before + 1.0


def test_record_tool_call_observes_histogram() -> None:
    """``record_tool_call`` observes the ``mcp_tool_duration_seconds{tool}`` histogram."""
    from eagle_rag.metrics import record_tool_call

    record_tool_call("test_hist", "success", 0.123)
    # The histogram _count sample reflects the number of observations.
    count = _get_sample_value("mcp_tool_duration_seconds_count", {"tool": "test_hist"})
    assert count is not None and count >= 1.0


def test_track_active_increments_and_decrements() -> None:
    """``track_active`` inc's the gauge on entry and dec's it back to 0 on exit."""
    from eagle_rag.metrics import track_active

    assert _get_sample_value("mcp_active_requests", {"tool": "test_track"}) in (None, 0.0)
    with track_active("test_track"):
        assert _get_sample_value("mcp_active_requests", {"tool": "test_track"}) == 1.0
    assert _get_sample_value("mcp_active_requests", {"tool": "test_track"}) == 0.0


# ---------------------------------------------------------------------------
# 4. _infer_status
# ---------------------------------------------------------------------------


def test_infer_status_success_dict() -> None:
    """A dict without an ``error`` field -> ``success``."""
    from eagle_rag.metrics import _infer_status

    assert _infer_status({"answer": "ok"}) == "success"


def test_infer_status_success_list() -> None:
    """A list without an ``error`` field -> ``success``."""
    from eagle_rag.metrics import _infer_status

    assert _infer_status([{"node_id": "n1"}, {"node_id": "n2"}]) == "success"


def test_infer_status_circuit_open() -> None:
    """An ``error`` starting with ``circuit_open`` -> ``circuit_open``."""
    from eagle_rag.metrics import _infer_status

    assert _infer_status({"error": "circuit_open: query"}) == "circuit_open"
    assert _infer_status([{"error": "circuit_open: retrieve_text"}]) == "circuit_open"


def test_infer_status_timeout() -> None:
    """An ``error`` starting with ``timeout`` -> ``timeout``."""
    from eagle_rag.metrics import _infer_status

    assert _infer_status({"error": "timeout: ingest"}) == "timeout"
    assert _infer_status([{"error": "timeout: retrieve_visual"}]) == "timeout"


def test_infer_status_error() -> None:
    """A non-empty ``error`` that is not circuit_open/timeout -> ``error``."""
    from eagle_rag.metrics import _infer_status

    assert _infer_status({"error": "ValueError: bad input"}) == "error"
    assert _infer_status([{"error": "ConnectionError: down"}]) == "error"


# ---------------------------------------------------------------------------
# 5. with_metrics decorator
# ---------------------------------------------------------------------------


def test_with_metrics_records_success() -> None:
    """A ``with_metrics``-decorated function increments the ``status=success`` counter."""
    from eagle_rag.metrics import with_metrics

    @with_metrics("test_deco_ok")
    def func(x):
        return {"result": x}

    before = _get_sample_value(
        "mcp_tool_calls_total", {"tool": "test_deco_ok", "status": "success"}
    )
    before = before or 0.0
    result = func(42)
    assert result == {"result": 42}
    after = _get_sample_value("mcp_tool_calls_total", {"tool": "test_deco_ok", "status": "success"})
    assert after == before + 1.0


def test_with_metrics_records_error_on_exception() -> None:
    """A ``with_metrics``-decorated function increments ``status=error`` and re-raises."""
    from eagle_rag.metrics import with_metrics

    @with_metrics("test_deco_err")
    def func():
        raise RuntimeError("boom")

    before = _get_sample_value("mcp_tool_calls_total", {"tool": "test_deco_err", "status": "error"})
    before = before or 0.0
    with pytest.raises(RuntimeError, match="boom"):
        func()
    after = _get_sample_value("mcp_tool_calls_total", {"tool": "test_deco_err", "status": "error"})
    assert after == before + 1.0


def test_with_metrics_records_circuit_open() -> None:
    """Returning ``{"error": "circuit_open: ..."}`` records ``status=circuit_open``."""
    from eagle_rag.metrics import with_metrics

    @with_metrics("test_deco_co")
    def func():
        return {"error": "circuit_open: test_deco_co"}

    before = _get_sample_value(
        "mcp_tool_calls_total", {"tool": "test_deco_co", "status": "circuit_open"}
    )
    before = before or 0.0
    func()
    after = _get_sample_value(
        "mcp_tool_calls_total", {"tool": "test_deco_co", "status": "circuit_open"}
    )
    assert after == before + 1.0


def test_with_metrics_records_cache_hit() -> None:
    """Setting thread-local ``_set_cache_hit(True)`` records ``status=cache_hit``."""
    from eagle_rag.metrics import _set_cache_hit, with_metrics

    @with_metrics("test_deco_ch")
    def func():
        _set_cache_hit(True)
        return [{"node_id": "n1"}]

    before = _get_sample_value(
        "mcp_tool_calls_total", {"tool": "test_deco_ch", "status": "cache_hit"}
    )
    before = before or 0.0
    func()
    after = _get_sample_value(
        "mcp_tool_calls_total", {"tool": "test_deco_ch", "status": "cache_hit"}
    )
    assert after == before + 1.0


def test_with_metrics_preserves_function_signature() -> None:
    """``with_metrics`` preserves the original function signature via ``functools.wraps``."""
    import inspect

    from eagle_rag.metrics import with_metrics

    @with_metrics("test_sig")
    def func(a: int, b: str = "hi") -> dict:
        """docstring."""
        return {"a": a, "b": b}

    assert func.__name__ == "func"
    assert func.__doc__ == "docstring."
    sig = inspect.signature(func)
    assert list(sig.parameters.keys()) == ["a", "b"]
    # ``from __future__ import annotations`` makes annotations strings; check the strings.
    assert sig.parameters["a"].annotation == "int"
    assert sig.parameters["b"].default == "hi"


# ---------------------------------------------------------------------------
# 6. Circuit breaker state listener integration
# ---------------------------------------------------------------------------


@pytest.fixture
def _mock_resilience_settings():
    """Mock ``eagle_rag.mcp_resilience.get_settings`` to return minimal settings."""
    mcp = SimpleNamespace(
        tool_timeout=30.0,
        max_retries=3,
        circuit_fail_threshold=3,
    )
    settings = SimpleNamespace(mcp=mcp)
    with patch("eagle_rag.mcp_resilience.get_settings", return_value=settings):
        yield


def test_circuit_breaker_listener_updates_gauge_on_open(_mock_resilience_settings) -> None:
    """When the breaker goes OPEN, the ``mcp_circuit_state{tool}`` gauge is updated to 2."""
    from eagle_rag.mcp_resilience import _breakers, get_breaker

    _breakers.clear()
    breaker = get_breaker("test_listener", fail_threshold=2)

    # Initial state: closed (0).
    assert _get_sample_value("mcp_circuit_state", {"tool": "test_listener"}) == 0.0

    # 2 failures trigger OPEN.
    def fail():
        raise ConnectionError("down")

    for _ in range(2):
        try:
            breaker.call(fail)
        except Exception:
            pass

    assert breaker.current_state == "open"
    assert _get_sample_value("mcp_circuit_state", {"tool": "test_listener"}) == 2.0
    _breakers.clear()


def test_circuit_breaker_listener_initial_state_closed(_mock_resilience_settings) -> None:
    """``get_breaker`` initializes the gauge to closed (0) when creating a breaker."""
    from eagle_rag.mcp_resilience import _breakers, get_breaker

    _breakers.clear()
    get_breaker("test_init_state")
    assert _get_sample_value("mcp_circuit_state", {"tool": "test_init_state"}) == 0.0
    _breakers.clear()


# ---------------------------------------------------------------------------
# 7. Tool function integration tests
#
# These tests import ``eagle_rag.api.mcp_server``, which triggers
# ``eagle_rag.api.__init__`` -> ``eagle_rag.api.app`` -> ``from fastapi import FastAPI``.
# Skip if fastapi is not installed (pure MCP standalone deployment scenario).
# ---------------------------------------------------------------------------

try:
    import fastapi as _fastapi  # noqa: F401

    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False

_fastapi_required = pytest.mark.skipif(
    not _HAS_FASTAPI, reason="fastapi not installed (MCP standalone env)"
)


@pytest.fixture
def _mock_record_mcp_call():
    """Mock ``record_mcp_call`` to avoid DB dependency."""
    with patch("eagle_rag.admin.mcp_log.record_mcp_call"):
        yield


@_fastapi_required
def test_query_tool_increments_metrics(_mock_record_mcp_call) -> None:
    """The ``query`` tool increments ``status=circuit_open`` on ``CircuitBreakerError``."""
    from eagle_rag.api.mcp_server import query
    from eagle_rag.mcp_resilience import CircuitBreakerError

    before = _get_sample_value(
        "mcp_tool_calls_total", {"tool": "core_query", "status": "circuit_open"}
    )
    before = before or 0.0

    with patch(
        "eagle_rag.api.mcp_server.resilient_call",
        side_effect=CircuitBreakerError("circuit open"),
    ):
        result = query("个税起征点")

    assert result == {"error": "circuit_open: core_query"}
    after = _get_sample_value(
        "mcp_tool_calls_total", {"tool": "core_query", "status": "circuit_open"}
    )
    assert after == before + 1.0


@_fastapi_required
def test_ingest_tool_increments_timeout_metrics(_mock_record_mcp_call) -> None:
    """The ``ingest`` tool increments the ``status=timeout`` counter on ``TimeoutError``."""
    from eagle_rag.api.mcp_server import ingest

    before = _get_sample_value("mcp_tool_calls_total", {"tool": "core_ingest", "status": "timeout"})
    before = before or 0.0

    with patch(
        "eagle_rag.api.mcp_server.resilient_call",
        side_effect=TimeoutError("timed out"),
    ):
        result = ingest("/tmp/test.pdf")

    assert result == {"error": "timeout: core_ingest"}
    after = _get_sample_value("mcp_tool_calls_total", {"tool": "core_ingest", "status": "timeout"})
    assert after == before + 1.0


@_fastapi_required
def test_retrieve_text_cache_hit_increments_cache_hit_counter(_mock_record_mcp_call) -> None:
    """The ``retrieve_text`` tool increments the ``status=cache_hit`` counter on a cache hit."""
    from eagle_rag.api.mcp_server import retrieve_text
    from eagle_rag.mcp_cache import reset_redis_pool

    reset_redis_pool()
    cached_data = [{"node_id": "n1", "text": "cached", "score": 0.9, "metadata": {}}]
    before = _get_sample_value(
        "mcp_tool_calls_total", {"tool": "core_retrieve_text", "status": "cache_hit"}
    )
    before = before or 0.0

    with patch("eagle_rag.api.mcp_server.get_cached", return_value=cached_data):
        result = retrieve_text("查询")

    assert result == cached_data
    after = _get_sample_value(
        "mcp_tool_calls_total", {"tool": "core_retrieve_text", "status": "cache_hit"}
    )
    assert after == before + 1.0


# ---------------------------------------------------------------------------
# 8. FastMCP integration: decorator compatibility with @mcp.tool()
# ---------------------------------------------------------------------------


def test_with_metrics_compatible_with_fastmcp_tool_decorator() -> None:
    """The ``@mcp.tool()`` + ``@with_metrics`` decorator combo registers the tool correctly."""
    from fastmcp import FastMCP

    from eagle_rag.metrics import with_metrics

    mcp = FastMCP("test-compat")

    @mcp.tool()
    @with_metrics("compat_tool")
    def compat_tool(x: int, y: str = "hi") -> dict:
        """Compat test tool."""
        return {"x": x, "y": y}

    tools = asyncio.run(mcp.get_tools())
    if isinstance(tools, dict):
        tool_names = list(tools.keys())
    else:
        tool_names = [t.name for t in tools]
    assert "compat_tool" in tool_names

    if isinstance(tools, dict):
        tool = tools["compat_tool"]
    else:
        tool = next(t for t in tools if t.name == "compat_tool")
    props = tool.parameters.get("properties", {})
    assert set(props.keys()) == {"x", "y"}
