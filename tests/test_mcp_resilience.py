"""MCP resilience wrapper (``eagle_rag.mcp_resilience``) tests.

Verifies retry, circuit breaking, timeout, and degraded error responses:

- **Retry**: ``resilient_call`` retries ``RETRYABLE_EXCEPTIONS``
  (ConnectionError / TimeoutError / OSError) and immediately re-raises non-retryable
  exceptions (ValueError).
- **Circuit breaking**: per-tool ``CircuitBreaker`` opens after ``fail_max`` consecutive
  failures and raises ``CircuitBreakerError`` (fast-fail); ``NON_BREAKING_EXCEPTIONS`` do
  not count toward the failure counter; ``get_breaker`` returns the same instance for the
  same tool_name.
- **Timeout**: ``resilient_call`` raises ``TimeoutError`` after ``timeout`` seconds; the
  worker thread is abandoned.
- **Degradation**: tool function except blocks detect ``CircuitBreakerError`` ->
  ``{"error": "circuit_open: <tool>"}`` and ``TimeoutError`` ->
  ``{"error": "timeout: <tool>"}``.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import patch

import pybreaker
import pytest

from eagle_rag.mcp_resilience import (
    NON_BREAKING_EXCEPTIONS,
    RETRYABLE_EXCEPTIONS,
    CircuitBreakerError,
    _breakers,
    get_breaker,
    resilient_call,
)

# ---------------------------------------------------------------------------
# Isolation: override conftest.py autouse fixtures (same as test_mcp_config.py)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_telemetry_state():
    yield


@pytest.fixture(autouse=True)
def _kb_registered():
    yield


# ---------------------------------------------------------------------------
# Isolation: mock settings + clear breaker cache
# ---------------------------------------------------------------------------


def _make_settings(*, tool_timeout=30.0, max_retries=3, circuit_fail_threshold=3):
    """Build a SimpleNamespace with an ``mcp`` sub-object to mimic ``get_settings()``."""
    mcp = SimpleNamespace(
        tool_timeout=tool_timeout,
        max_retries=max_retries,
        circuit_fail_threshold=circuit_fail_threshold,
    )
    return SimpleNamespace(mcp=mcp)


@pytest.fixture(autouse=True)
def _mock_settings():
    """Mock ``eagle_rag.mcp_resilience.get_settings`` to return minimal settings."""
    settings = _make_settings()
    with patch("eagle_rag.mcp_resilience.get_settings", return_value=settings):
        yield


@pytest.fixture(autouse=True)
def _reset_breakers():
    """Clear the breaker cache before and after each test to avoid cross-test state leakage."""
    _breakers.clear()
    yield
    _breakers.clear()


# ---------------------------------------------------------------------------
# 1. Constants and type exports
# ---------------------------------------------------------------------------


def test_circuit_breaker_error_is_pybreaker_type() -> None:
    """``CircuitBreakerError`` is a re-export of ``pybreaker.CircuitBreakerError``."""
    assert CircuitBreakerError is pybreaker.CircuitBreakerError


def test_retryable_exceptions_contents() -> None:
    """``RETRYABLE_EXCEPTIONS`` contains ConnectionError / TimeoutError / OSError."""
    assert ConnectionError in RETRYABLE_EXCEPTIONS
    assert TimeoutError in RETRYABLE_EXCEPTIONS
    assert OSError in RETRYABLE_EXCEPTIONS


def test_non_breaking_exceptions_contents() -> None:
    """``NON_BREAKING_EXCEPTIONS`` contains ValueError / KeyError / TypeError, etc."""
    assert ValueError in NON_BREAKING_EXCEPTIONS
    assert KeyError in NON_BREAKING_EXCEPTIONS
    assert TypeError in NON_BREAKING_EXCEPTIONS
    assert AttributeError in NON_BREAKING_EXCEPTIONS


# ---------------------------------------------------------------------------
# 2. get_breaker singleton
# ---------------------------------------------------------------------------


def test_get_breaker_returns_same_instance_for_same_tool() -> None:
    """Calling ``get_breaker`` multiple times with the same tool_name returns the same
    ``CircuitBreaker`` instance."""
    b1 = get_breaker("query")
    b2 = get_breaker("query")
    assert b1 is b2
    assert b1.name == "query"


def test_get_breaker_different_tools_different_instances() -> None:
    """Different tool_names return different breaker instances."""
    b1 = get_breaker("query")
    b2 = get_breaker("ingest")
    assert b1 is not b2
    assert b1.name == "query"
    assert b2.name == "ingest"


def test_get_breaker_uses_fail_threshold_from_settings() -> None:
    """When ``fail_threshold=None``, it reads from ``settings.mcp.circuit_fail_threshold``."""
    breaker = get_breaker("test_tool")
    assert breaker.fail_max == 3  # _make_settings defaults circuit_fail_threshold=3


def test_get_breaker_explicit_fail_threshold() -> None:
    """An explicit ``fail_threshold`` overrides the settings default."""
    breaker = get_breaker("test_explicit", fail_threshold=7)
    assert breaker.fail_max == 7


# ---------------------------------------------------------------------------
# 3. resilient_call — success path
# ---------------------------------------------------------------------------


def test_resilient_call_returns_func_result_on_success() -> None:
    """``resilient_call`` returns ``func``'s result on a normal call."""

    def func(x, y, *, z=0):
        return x + y + z

    result = resilient_call("test_ok", func, 1, 2, z=3)
    assert result == 6


def test_resilient_call_passes_args_and_kwargs() -> None:
    """``resilient_call`` forwards positional and keyword args correctly."""
    captured = {}

    def func(a, b, *, c, d):
        captured.update(a=a, b=b, c=c, d=d)
        return "ok"

    resilient_call("test_args", func, 1, 2, c=3, d=4)
    assert captured == {"a": 1, "b": 2, "c": 3, "d": 4}


# ---------------------------------------------------------------------------
# 4. resilient_call — retry
# ---------------------------------------------------------------------------


def test_resilient_call_retries_on_connection_error() -> None:
    """``ConnectionError`` is retryable; success on the 3rd attempt returns the result."""
    counter = {"n": 0}

    def flaky():
        counter["n"] += 1
        if counter["n"] < 3:
            raise ConnectionError("transient")
        return "success"

    # max_retries=3 (default), wait_exponential min=1 -> actual wait ~1s+2s = 3s.
    # Set timeout=10 to ensure no timeout fires.
    result = resilient_call("test_retry", flaky, timeout=10, max_retries=3)
    assert result == "success"
    assert counter["n"] == 3


def test_resilient_call_reraises_after_exhausting_retries() -> None:
    """After retries are exhausted, the last exception is re-raised (not wrapped in RetryError)."""
    counter = {"n": 0}

    def always_fail():
        counter["n"] += 1
        raise ConnectionError("persistent")

    with pytest.raises(ConnectionError, match="persistent"):
        resilient_call("test_exhaust", always_fail, timeout=10, max_retries=3)
    assert counter["n"] == 3


def test_resilient_call_no_retry_on_value_error() -> None:
    """``ValueError`` is not retryable; it is re-raised immediately without retry."""
    counter = {"n": 0}

    def raise_value():
        counter["n"] += 1
        raise ValueError("bad input")

    with pytest.raises(ValueError, match="bad input"):
        resilient_call("test_no_retry", raise_value, timeout=10, max_retries=3)
    assert counter["n"] == 1  # Called only once; no retry.


# ---------------------------------------------------------------------------
# 5. resilient_call — circuit breaking
# ---------------------------------------------------------------------------


def test_resilient_call_opens_circuit_after_fail_max() -> None:
    """After ``fail_max`` consecutive failures the breaker opens and subsequent calls fast-fail.

    ``throw_new_error_on_trip=True``: the call that trips the breaker raises
    ``CircuitBreakerError`` (not the original ``ConnectionError``).
    """
    counter = {"n": 0}

    def always_fail():
        counter["n"] += 1
        raise ConnectionError("down")

    # fail_max=2, max_retries=1 -> each resilient_call invokes func only once (no retry).
    # 1st call: func fails -> fail_counter=1 -> propagate ConnectionError.
    with pytest.raises(ConnectionError):
        resilient_call("test_circuit", always_fail, timeout=10, max_retries=1, fail_threshold=2)

    # 2nd call: func fails -> fail_counter=2 -> OPEN -> raise CircuitBreakerError (trip).
    with pytest.raises(CircuitBreakerError):
        resilient_call("test_circuit", always_fail, timeout=10, max_retries=1, fail_threshold=2)

    # 3rd call: breaker OPEN -> CircuitBreakerError (func not invoked).
    with pytest.raises(CircuitBreakerError):
        resilient_call("test_circuit", always_fail, timeout=10, max_retries=1, fail_threshold=2)
    # func was called only twice (3rd call fast-failed before reaching func).
    assert counter["n"] == 2


def test_non_breaking_exception_does_not_trip_breaker() -> None:
    """``ValueError`` is in ``exclude`` and does not count toward the breaker failure counter."""
    breaker = get_breaker("test_non_breaking", fail_threshold=2)

    def raise_value():
        raise ValueError("bad input")

    # 5 consecutive ValueErrors; breaker stays CLOSED.
    for _ in range(5):
        with pytest.raises(ValueError):
            resilient_call(
                "test_non_breaking",
                raise_value,
                timeout=10,
                max_retries=1,
                fail_threshold=2,
            )
    assert breaker.current_state == "closed"
    assert breaker.fail_counter == 0


def test_breaker_excludes_key_error_and_type_error() -> None:
    """``KeyError`` / ``TypeError`` are in NON_BREAKING_EXCEPTIONS and don't count as failures."""
    breaker = get_breaker("test_exclude_types", fail_threshold=2)

    def raise_key():
        raise KeyError("missing")

    for _ in range(3):
        with pytest.raises(KeyError):
            resilient_call(
                "test_exclude_types",
                raise_key,
                timeout=10,
                max_retries=1,
                fail_threshold=2,
            )
    assert breaker.current_state == "closed"


# ---------------------------------------------------------------------------
# 6. resilient_call — timeout
# ---------------------------------------------------------------------------


def test_resilient_call_timeout_raises_timeout_error() -> None:
    """When ``func`` exceeds ``timeout`` seconds, ``TimeoutError`` is raised."""

    def slow():
        time.sleep(2)
        return "done"

    with pytest.raises(TimeoutError, match="exceeded"):
        resilient_call("test_timeout", slow, timeout=0.1, max_retries=1)


def test_resilient_call_timeout_does_not_block_indefinitely() -> None:
    """After timeout, ``resilient_call`` returns immediately (does not wait for func to finish)."""

    def slow():
        time.sleep(5)
        return "done"

    start = time.perf_counter()
    with pytest.raises(TimeoutError):
        resilient_call("test_fast_timeout", slow, timeout=0.1, max_retries=1)
    elapsed = time.perf_counter() - start
    # Should return within 1 second after timeout (allowing small scheduling overhead).
    assert elapsed < 1.0


# ---------------------------------------------------------------------------
# 7. Tool function degradation (CircuitBreakerError / TimeoutError)
# ---------------------------------------------------------------------------


@pytest.fixture
def _mock_record_mcp_call():
    """Mock ``record_mcp_call`` to avoid DB dependency (same as test_mcp_http_transport.py)."""
    with patch("eagle_rag.admin.mcp_log.record_mcp_call"):
        yield


def test_query_tool_returns_circuit_open_on_breaker_error(_mock_record_mcp_call) -> None:
    """``query`` returns ``{"error": "circuit_open: query"}`` on ``CircuitBreakerError``."""
    from eagle_rag.api.mcp_server import query

    with patch(
        "eagle_rag.api.mcp_server.resilient_call",
        side_effect=CircuitBreakerError("circuit open"),
    ):
        result = query("个税起征点")

    assert result == {"error": "circuit_open: core_query"}


def test_query_tool_returns_timeout_on_timeout_error(_mock_record_mcp_call) -> None:
    """The ``query`` tool returns ``{"error": "timeout: query"}`` on ``TimeoutError``."""
    from eagle_rag.api.mcp_server import query

    with patch(
        "eagle_rag.api.mcp_server.resilient_call",
        side_effect=TimeoutError("timed out"),
    ):
        result = query("个税起征点")

    assert result == {"error": "timeout: core_query"}


def test_retrieve_text_tool_returns_circuit_open(_mock_record_mcp_call) -> None:
    """The ``retrieve_text`` tool returns a list-wrapped error on ``CircuitBreakerError``."""
    from eagle_rag.api.mcp_server import retrieve_text

    with patch(
        "eagle_rag.api.mcp_server.resilient_call",
        side_effect=CircuitBreakerError("circuit open"),
    ):
        result = retrieve_text("查询")

    assert isinstance(result, list)
    assert result[0]["error"] == "circuit_open: core_retrieve_text"


def test_retrieve_visual_tool_returns_timeout(_mock_record_mcp_call) -> None:
    """The ``retrieve_visual`` tool returns a list-wrapped error on ``TimeoutError``."""
    from eagle_rag.api.mcp_server import retrieve_visual

    with patch(
        "eagle_rag.api.mcp_server.resilient_call",
        side_effect=TimeoutError("timed out"),
    ):
        result = retrieve_visual("图表")

    assert isinstance(result, list)
    assert result[0]["error"] == "timeout: core_retrieve_visual"


def test_query_requires_query_or_image_base64(_mock_record_mcp_call) -> None:
    """``query`` rejects empty text when no inline image is provided."""
    from eagle_rag.api.mcp_server import query

    assert query() == {"error": "query or image_base64 is required"}
    assert query(query="   ") == {"error": "query or image_base64 is required"}


def test_query_image_only_passes_bytes_to_router(_mock_record_mcp_call) -> None:
    """``query(image_base64=...)`` decodes bytes and forwards them to the router engine."""
    import base64

    from eagle_rag.api.mcp_server import query

    image_bytes = b"\x89PNG\r\n\x1a\n" + b"x" * 64
    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    engine_result = {
        "answer": "视觉回答",
        "sources": [],
        "route": "visual",
        "steps": [],
        "extra": "trimmed",
    }

    def _run_resilient(_tool: str, fn):
        return fn()

    with (
        patch("eagle_rag.api.mcp_server.resilient_call", side_effect=_run_resilient),
        patch("eagle_rag.router.router_engine.EagleRouterQueryEngine") as mock_engine_cls,
    ):
        mock_engine_cls.return_value.query.return_value = engine_result
        result = query(image_base64=image_b64, image_mime="image/png")

    mock_engine_cls.return_value.query.assert_called_once()
    assert mock_engine_cls.return_value.query.call_args.kwargs["query_image_bytes"] == image_bytes
    assert result == {
        "answer": "视觉回答",
        "sources": [],
        "route": "visual",
        "steps": [],
    }


def test_retrieve_visual_image_only_uses_embed_image_path(_mock_record_mcp_call) -> None:
    """``retrieve_visual(image_base64=...)`` calls retriever with image bytes only."""
    import base64
    from types import SimpleNamespace

    from eagle_rag.api.mcp_server import retrieve_visual

    image_bytes = b"\x89PNG\r\n\x1a\n" + b"y" * 64
    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    fake_node = SimpleNamespace(
        node=SimpleNamespace(
            metadata={"image_id": "img-1", "document_id": "doc-1", "page": 1, "position": 0}
        ),
        score=0.88,
    )

    def _run_resilient(_tool: str, fn):
        return fn()

    with (
        patch("eagle_rag.api.mcp_server.get_cached", return_value=None),
        patch("eagle_rag.api.mcp_server.set_cached"),
        patch("eagle_rag.api.mcp_server.resilient_call", side_effect=_run_resilient),
        patch("eagle_rag.retrievers.pixelrag_visual_retriever.PixelRAGVisualRetriever") as mock_cls,
    ):
        mock_cls.return_value.retrieve.return_value = [fake_node]
        result = retrieve_visual(image_base64=image_b64, image_mime="image/png", top_k=3)

    mock_cls.return_value.retrieve.assert_called_once_with("", query_image_bytes=image_bytes)
    assert result == [
        {
            "image_id": "img-1",
            "document_id": "doc-1",
            "page": 1,
            "position": 0,
            "score": 0.88,
        }
    ]


def test_ingest_tool_returns_circuit_open(_mock_record_mcp_call) -> None:
    """``ingest`` returns ``{"error": "circuit_open: ingest"}`` on ``CircuitBreakerError``."""
    from eagle_rag.api.mcp_server import ingest

    with patch(
        "eagle_rag.api.mcp_server.resilient_call",
        side_effect=CircuitBreakerError("circuit open"),
    ):
        result = ingest("/tmp/test.pdf")

    assert result == {"error": "circuit_open: core_ingest"}


def test_ingest_tool_returns_timeout(_mock_record_mcp_call) -> None:
    """The ``ingest`` tool returns ``{"error": "timeout: ingest"}`` on ``TimeoutError``."""
    from eagle_rag.api.mcp_server import ingest

    with patch(
        "eagle_rag.api.mcp_server.resilient_call",
        side_effect=TimeoutError("timed out"),
    ):
        result = ingest("/tmp/test.pdf")

    assert result == {"error": "timeout: core_ingest"}
