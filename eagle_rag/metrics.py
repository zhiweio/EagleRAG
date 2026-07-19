"""Prometheus metrics plus ``/metrics`` and ``/health`` endpoints.

Exposes Prometheus metrics for MCP tool invocations via the ``/metrics`` route for
scraping, and a ``/health`` route for Docker Swarm healthchecks and HAProxy
``option httpchk`` probes.

Metrics:

- ``mcp_tool_calls_total{tool,status}`` (Counter): tool invocation count, labeled by
  tool name and status (``success`` / ``cache_hit`` / ``circuit_open`` / ``timeout``
  / ``error``).
- ``mcp_tool_duration_seconds{tool}`` (Histogram): tool invocation duration in seconds.
- ``mcp_active_requests{tool}`` (Gauge): current in-flight requests (inc on enter,
  dec on exit).
- ``mcp_circuit_state{tool}`` (Gauge): circuit-breaker state, ``0=closed`` /
  ``1=half-open`` / ``2=open``. Updated automatically via the
  ``CircuitBreakerListener.state_change`` callback (SubTask 4.3).
- ``plugin_audit_decisions_total{category,plugin_namespace,outcome}`` (Counter):
  PluginAudit decision events (``outcome`` = ``ok`` / ``error``).
- ``plugin_audit_rrf_dedupe_total{plugin_namespace}`` (Counter): RRF cross-
  collection dedupe events (G32 double-write monitoring).

Instrumentation: decorate MCP tool functions with ``@with_metrics(tool_name)`` to
automatically inc/dec active requests, observe duration, and inc
tool_calls{status}. Status is inferred from the return value (``_infer_status``);
cache hits are flagged via the thread-local ``_cache_hit_local``.
"""

from __future__ import annotations

import functools
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from typing import Any, TypeVar

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

__all__ = [
    "MCP_TOOL_CALLS",
    "MCP_TOOL_DURATION",
    "MCP_ACTIVE_REQUESTS",
    "MCP_CIRCUIT_STATE",
    "PLUGIN_AUDIT_DECISIONS",
    "PLUGIN_AUDIT_RRF_DEDUPE",
    "metrics_handler",
    "health_handler",
    "metrics_app",
    "record_tool_call",
    "update_circuit_state",
    "track_active",
    "with_metrics",
]

F = TypeVar("F", bound=Callable[..., Any])

# ---------------------------------------------------------------------------
# Prometheus metric definitions
# ---------------------------------------------------------------------------

MCP_TOOL_CALLS = Counter(
    "mcp_tool_calls_total",
    "Number of MCP tool invocations",
    ["tool", "status"],
)

MCP_TOOL_DURATION = Histogram(
    "mcp_tool_duration_seconds",
    "MCP tool invocation duration in seconds",
    ["tool"],
)

MCP_ACTIVE_REQUESTS = Gauge(
    "mcp_active_requests",
    "Current in-flight MCP requests",
    ["tool"],
)

MCP_CIRCUIT_STATE = Gauge(
    "mcp_circuit_state",
    "MCP tool circuit-breaker state (0=closed, 1=half-open, 2=open)",
    ["tool"],
)

PLUGIN_AUDIT_DECISIONS = Counter(
    "plugin_audit_decisions_total",
    "Plugin classification/routing/hook decision count",
    ["category", "plugin_namespace", "outcome"],
)

PLUGIN_AUDIT_RRF_DEDUPE = Counter(
    "plugin_audit_rrf_dedupe_total",
    "Cross-collection RRF dedupe events (G32 double-write monitoring)",
    ["plugin_namespace"],
)

# State string -> gauge numeric value.
_STATE_VALUES: dict[str, int] = {
    "closed": 0,
    "half-open": 1,
    "open": 2,
}

# ---------------------------------------------------------------------------
# Thread-local cache-hit flag (FastMCP sync tools run in a thread pool, so thread-local is safe).
# ---------------------------------------------------------------------------

_cache_hit_local = threading.local()


def _set_cache_hit(value: bool) -> None:
    """Flag the current thread's call as a cache hit (read by ``with_metrics``)."""
    _cache_hit_local.value = value


def _consume_cache_hit() -> bool:
    """Read and reset the cache-hit flag."""
    val = getattr(_cache_hit_local, "value", False)
    _cache_hit_local.value = False
    return val


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def update_circuit_state(tool_name: str, state: str) -> None:
    """Update the circuit-breaker state metric.

    Args:
        tool_name: Tool name.
        state: State string (``"closed"`` / ``"half-open"`` / ``"open"``).
    """
    MCP_CIRCUIT_STATE.labels(tool=tool_name).set(_STATE_VALUES.get(state, 0))


def record_tool_call(tool_name: str, status: str, duration_seconds: float) -> None:
    """Record tool invocation count and duration.

    Args:
        tool_name: Tool name.
        status: Invocation status (``success`` / ``cache_hit`` / ``circuit_open``
            / ``timeout`` / ``error``).
        duration_seconds: Invocation duration in seconds.
    """
    MCP_TOOL_CALLS.labels(tool=tool_name, status=status).inc()
    MCP_TOOL_DURATION.labels(tool=tool_name).observe(duration_seconds)


@contextmanager
def track_active(tool_name: str):
    """Context manager: inc active requests on enter, dec on exit."""
    MCP_ACTIVE_REQUESTS.labels(tool=tool_name).inc()
    try:
        yield
    finally:
        MCP_ACTIVE_REQUESTS.labels(tool=tool_name).dec()


def _infer_status(result: Any) -> str:
    """Infer invocation status from the tool's return value.

    Tool degradation contract: when a dict (or the first element of a list) carries
    an ``error`` field, the prefix selects ``circuit_open`` / ``timeout`` / ``error``;
    otherwise the call is ``success``.
    """
    if isinstance(result, dict):
        err = str(result.get("error", ""))
        if err.startswith("circuit_open"):
            return "circuit_open"
        if err.startswith("timeout"):
            return "timeout"
        if err:
            return "error"
        return "success"
    if isinstance(result, list) and result:
        first = result[0]
        if isinstance(first, dict):
            err = str(first.get("error", ""))
            if err.startswith("circuit_open"):
                return "circuit_open"
            if err.startswith("timeout"):
                return "timeout"
            if err:
                return "error"
        return "success"
    return "success"


def with_metrics(tool_name: str) -> Callable[[F], F]:
    """Decorate an MCP tool function to record Prometheus metrics automatically.

    Instrumentation:

    1. On entry, ``MCP_ACTIVE_REQUESTS{tool}.inc()``.
    2. Call the wrapped function, timing it with ``time.perf_counter()``.
    3. On exit (normal or exceptional), ``MCP_ACTIVE_REQUESTS{tool}.dec()``.
    4. Infer status from the return value (``_infer_status``); if the thread-local
       ``_cache_hit_local`` flag is set, override to ``cache_hit``.
    5. ``MCP_TOOL_CALLS{tool,status}.inc()`` and ``MCP_TOOL_DURATION{tool}.observe()``.

    ``functools.wraps`` preserves the original signature and docstring so the
    FastMCP ``@mcp.tool()`` decorator registers the tool schema correctly (verified
    empirically).

    Usage::

        @mcp.tool()
        @with_metrics("query")
        def query(query: str, ...) -> dict[str, Any]:
            ...
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with track_active(tool_name):
                start = time.perf_counter()
                status = "success"
                try:
                    result = func(*args, **kwargs)
                    if _consume_cache_hit():
                        status = "cache_hit"
                    else:
                        status = _infer_status(result)
                    return result
                except Exception:
                    status = "error"
                    raise
                finally:
                    duration = time.perf_counter() - start
                    record_tool_call(tool_name, status, duration)

        return wrapper  # type: ignore[return-value]

    return decorator


# ---------------------------------------------------------------------------
# HTTP endpoints + Starlette app
# ---------------------------------------------------------------------------


async def metrics_handler(request: Request) -> Response:
    """Prometheus scrape endpoint (``GET /metrics``)."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


async def health_handler(request: Request) -> JSONResponse:
    """Health check endpoint (``GET /health``).

    Probed by Docker Swarm ``healthcheck`` and HAProxy ``option httpchk``.
    Returns ``{"status": "ok"}`` JSON with HTTP 200.
    """
    return JSONResponse({"status": "ok"})


# Standalone Starlette app (used by tests and standalone deployments).
metrics_app = Starlette(
    routes=[
        Route("/metrics", metrics_handler),
        Route("/health", health_handler),
    ]
)
