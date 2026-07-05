"""Eagle-RAG telemetry package: unified entry for dual-logger routing + OpenTelemetry tracing.

- ``configure_telemetry(settings)``: idempotent init. When ``telemetry.enabled=true``
  runs ``configure_logging`` then ``configure_tracing``; when false only
  ``logging.basicConfig`` as a fallback, and ``get_logger``/``get_ai_logger``
  fall back to stdlib.
- ``get_ai_logger(name)``: AI evaluation events logger (structlog JSONL, includes trace_id/span_id).
- ``get_logger(name)``: ops logger (loguru, stderr + rotating file + Redis pubsub).
- ``bind_context(**kv)`` / ``clear_context()``: shared context for both loggers.
- ``trace_span(name, kind=...)``: OTel span contextmanager/decorator.
- ``set_llm_span_attributes(...)``: GenAI semantic convention attributes.
- ``TelemetryMiddleware``: FastAPI request root span.
- ``register_celery_signals(app)`` / ``send_task_with_trace(...)``: Celery trace continuation.
"""

from __future__ import annotations

from typing import Any

from eagle_rag.telemetry.context import (
    bind_context,
    bind_context_scope,
    clear_context,
    get_context,
)
from eagle_rag.telemetry.context import (
    set_enabled as _set_ctx_enabled,
)
from eagle_rag.telemetry.logging_setup import (
    configure_logging,
    get_ai_logger,
    get_logger,
    truncate,
)
from eagle_rag.telemetry.tracing import (
    TelemetryMiddleware,
    configure_tracing,
    get_current_span,
    register_celery_signals,
    send_task_with_trace,
    set_llm_span_attributes,
    trace_span,
)

__all__ = [
    "configure_telemetry",
    "get_ai_logger",
    "get_logger",
    "bind_context",
    "clear_context",
    "get_context",
    "bind_context_scope",
    "trace_span",
    "get_current_span",
    "set_llm_span_attributes",
    "TelemetryMiddleware",
    "register_celery_signals",
    "send_task_with_trace",
    "truncate",
]

# Idempotency flag: configure_telemetry returns immediately once already run.
_configured: bool = False


def configure_telemetry(settings: Any) -> None:
    """Initialize telemetry (loguru + structlog + OpenTelemetry). Idempotent.

    When ``telemetry.enabled=false`` only minimal stdlib logging is configured;
    structlog/loguru/OTel are not imported, and ``get_logger``/``get_ai_logger``
    fall back to stdlib logging.
    """
    global _configured
    if _configured:
        return

    tel = settings.telemetry
    if not tel.enabled:
        import logging

        logging.basicConfig(level=logging.INFO)
        _set_ctx_enabled(False)
        _configured = True
        return

    _set_ctx_enabled(True)
    configure_logging(settings)
    configure_tracing(settings)
    _configured = True
