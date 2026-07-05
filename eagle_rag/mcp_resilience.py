"""Resilience wrapper for MCP tool calls: retry + circuit breaker + timeout + degradation.

Combines tenacity (retry), pybreaker (circuit breaker), and a daemon-thread
timeout to provide uniform resilience for the service-layer calls
(``ingest`` / ``query`` / ``retrieve_text`` / ``retrieve_visual``) invoked by MCP tools.

Layering (outer to inner):

1. **Timeout** (outermost, daemon thread): the whole ``resilient_call`` must
   complete within ``timeout`` seconds, otherwise a ``TimeoutError`` is raised
   (caught by the tool's except block and degraded to
   ``{"error": "timeout: <tool>"}``). On timeout the daemon thread is abandoned
   (``daemon=True``; reclaimed when the process exits). **Timeouts do not count
   toward the breaker's failure count** — the breaker only sees service-layer
   exceptions, and an abandoned thread leaves breaker state unchanged.
2. **Circuit breaker** (middle, pybreaker ``CircuitBreaker``): each tool has its
   own breaker. After ``fail_max`` consecutive failures it OPENs; after
   ``reset_timeout`` seconds it goes HALF-OPEN and allows one trial call. In the
   OPEN state it raises ``CircuitBreakerError`` directly (fast-fail, no load on
   downstream dependencies). ``NON_BREAKING_EXCEPTIONS`` (input/programming
   errors) are excluded from the failure count via the ``exclude`` parameter.
3. **Retry** (innermost, tenacity ``Retrying``): retries only
   ``RETRYABLE_EXCEPTIONS`` (network/transient errors) with exponential backoff;
   ``reraise=True`` re-raises the last exception when retries are exhausted. All
   retries within one ``resilient_call`` count as a **single** breaker failure
   (the breaker wraps the retry loop).

Usage:

.. code-block:: python

    from eagle_rag.mcp_resilience import resilient_call
    result = resilient_call("query", engine.query, query, mode=mode)

Tool except blocks must detect two special exception types (already handled in
``mcp_server.py``):

- ``CircuitBreakerError`` → ``{"error": f"circuit_open: {tool_name}"}``
- ``TimeoutError`` → ``{"error": f"timeout: {tool_name}"}``
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

import pybreaker
from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from eagle_rag.config import get_settings
from eagle_rag.telemetry import get_logger

logger = get_logger(__name__)

__all__ = [
    "resilient_call",
    "get_breaker",
    "CircuitBreakerError",
    "RETRYABLE_EXCEPTIONS",
    "NON_BREAKING_EXCEPTIONS",
    "CircuitStateMetricsListener",
]


class CircuitStateMetricsListener(pybreaker.CircuitBreakerListener):
    """Circuit-breaker state listener.

    Mirrors state to the Prometheus ``mcp_circuit_state`` gauge. Implements the
    pybreaker ``CircuitBreakerListener.state_change`` callback to update
    ``metrics.MCP_CIRCUIT_STATE{tool}`` (0=closed, 1=half-open, 2=open) whenever
    the breaker transitions (closed → open / open → half-open / half-open →
    closed). The ``before_call`` / ``success`` / ``failure`` callbacks are
    no-ops (only ``state_change`` drives the metric).

    Registered via ``add_listener`` when ``get_breaker()`` creates a new breaker.
    """

    def state_change(
        self,
        cb: pybreaker.CircuitBreaker,
        old_state: Any,
        new_state: Any,
    ) -> None:
        """Update the Prometheus gauge when the breaker state changes."""
        try:
            from eagle_rag.metrics import update_circuit_state

            # ``new_state`` is a ``CircuitBreakerState``; ``.name`` returns
            # "closed" / "open" / "half-open".
            update_circuit_state(cb.name, new_state.name)
        except Exception as exc:  # noqa: BLE001
            logger.debug("circuit breaker state metric update failed (%s): %s", cb.name, exc)


# Re-export so tool except blocks can `from eagle_rag.mcp_resilience import CircuitBreakerError`.
CircuitBreakerError = pybreaker.CircuitBreakerError

# Retryable exceptions: network/transient errors (tenacity only retries these;
# others reraise immediately). ``TimeoutError`` is a subclass of ``OSError``;
# httpx/socket timeouts in the service layer raise it.
RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    ConnectionError,
    TimeoutError,
    OSError,
)

# Non-breaking exceptions: input/programming errors excluded from the breaker
# failure count (pybreaker ``exclude``). These are caller logic errors and should
# not trip the breaker. ``KeyError`` / ``IndexError`` are subclasses of
# ``LookupError``; listed explicitly for readability.
NON_BREAKING_EXCEPTIONS: tuple[type[BaseException], ...] = (
    ValueError,
    KeyError,
    TypeError,
    AttributeError,
    LookupError,
    IndexError,
)

# Default reset_timeout (seconds): how long the breaker stays OPEN before going
# HALF-OPEN for a trial call.
_DEFAULT_RESET_TIMEOUT = 60

# Per-tool CircuitBreaker cache (module-level singletons, shared across requests).
_breakers: dict[str, pybreaker.CircuitBreaker] = {}
_breakers_lock = threading.Lock()


def get_breaker(
    tool_name: str,
    fail_threshold: int | None = None,
    reset_timeout: int = _DEFAULT_RESET_TIMEOUT,
) -> pybreaker.CircuitBreaker:
    """Get or create the per-tool CircuitBreaker (module-level singleton).

    Args:
        tool_name: Tool name (``ingest`` / ``query`` / ``retrieve_text`` /
            ``retrieve_visual``); used as the breaker name and cache key.
        fail_threshold: Consecutive failures required to OPEN. ``None`` reads
            ``settings.mcp.circuit_fail_threshold``.
        reset_timeout: Seconds OPEN before transitioning to HALF-OPEN (default 60).

    Returns:
        A ``pybreaker.CircuitBreaker`` instance. Repeated calls with the same
        ``tool_name`` return the same instance (``fail_threshold`` /
        ``reset_timeout`` apply only on first creation and are ignored later).
    """
    with _breakers_lock:
        if tool_name not in _breakers:
            if fail_threshold is None:
                fail_threshold = get_settings().mcp.circuit_fail_threshold
            breaker = pybreaker.CircuitBreaker(
                fail_max=fail_threshold,
                reset_timeout=reset_timeout,
                exclude=list(NON_BREAKING_EXCEPTIONS),
                name=tool_name,
                throw_new_error_on_trip=True,
            )
            # Register the state listener → Prometheus ``mcp_circuit_state{tool}`` gauge
            # (SubTask 4.3). Initialize to closed (0).
            breaker.add_listener(CircuitStateMetricsListener())
            try:
                from eagle_rag.metrics import update_circuit_state

                update_circuit_state(tool_name, "closed")
            except Exception:  # noqa: BLE001
                pass
            _breakers[tool_name] = breaker
        return _breakers[tool_name]


def resilient_call(
    tool_name: str,
    func: Callable[..., Any],
    *args: Any,
    timeout: float | None = None,
    max_retries: int | None = None,
    fail_threshold: int | None = None,
    **kwargs: Any,
) -> Any:
    """Service-call wrapper with retry / circuit-breaker / timeout.

    Args:
        tool_name: Tool name (used for the per-tool breaker and logging).
        func: Synchronous service-layer function (e.g. ``engine.query`` /
            ``retriever.retrieve``).
        *args: Positional arguments forwarded to ``func``.
        timeout: Total timeout in seconds (including retry waits). ``None`` reads
            ``settings.mcp.tool_timeout``.
        max_retries: Maximum retry attempts. ``None`` reads ``settings.mcp.max_retries``.
        fail_threshold: Breaker consecutive-failure threshold. ``None`` reads
            ``settings.mcp.circuit_fail_threshold`` (effective only on first
            breaker creation).
        **kwargs: Keyword arguments forwarded to ``func``.

    Returns:
        The return value of ``func``.

    Raises:
        CircuitBreakerError: Breaker is OPEN (fast-fail; ``func`` is not called).
        TimeoutError: Timed out (the daemon thread keeps running; its result is discarded).
        Exception: The final exception raised by ``func`` (reraised after retries are exhausted).
    """
    settings = get_settings().mcp
    if timeout is None:
        timeout = settings.tool_timeout
    if max_retries is None:
        max_retries = settings.max_retries

    breaker = get_breaker(tool_name, fail_threshold=fail_threshold)

    def _call_with_retry() -> Any:
        """Tenacity retry loop (wrapped by ``breaker.call``).

        Uses the ``Retrying.__call__`` imperative API (not the iterator form) and
        returns ``func``'s result directly. ``reraise=True`` ensures that, once
        retries are exhausted, the last exception is raised (counted by the
        breaker as a failure) rather than wrapped in ``RetryError``.
        """
        retrying = Retrying(
            stop=stop_after_attempt(max_retries),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            reraise=True,
        )
        return retrying(func, *args, **kwargs)

    # Daemon-thread timeout: run ``breaker.call`` in a separate thread and
    # ``join(timeout)`` from the main thread. On timeout the thread is abandoned
    # (``daemon=True``; reclaimed when the process exits) and a ``TimeoutError``
    # is raised. Python cannot forcibly terminate a thread; the abandoned thread
    # exits naturally once its I/O completes.
    container: dict[str, Any] = {"result": None, "exception": None}

    def _runner() -> None:
        try:
            container["result"] = breaker.call(_call_with_retry)
        except Exception as exc:  # noqa: BLE001
            container["exception"] = exc

    thread = threading.Thread(target=_runner, daemon=True, name=f"mcp-{tool_name}")
    thread.start()
    thread.join(timeout=timeout)

    if thread.is_alive():
        # Timed out: the thread is still running (likely blocked on I/O) and
        # cannot be forcibly terminated. ``daemon=True`` ensures it is reaped on
        # process exit; a single timeout will not bring down the process.
        # Note: timeouts do not count toward the breaker failure count (the
        # breaker lives inside the thread; its state is unchanged).
        logger.warning(
            "MCP tool %s timed out (%.1fs), abandoning thread",
            tool_name,
            timeout,
        )
        raise TimeoutError(f"{tool_name} call exceeded {timeout}s timeout")

    exc = container["exception"]
    if exc is not None:
        raise exc
    return container["result"]
