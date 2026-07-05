"""Dual-logger configuration core: loguru (ops) + structlog (AI events JSONL).

- ``configure_logging(settings)``: idempotent config. loguru registers stderr /
  rotating file / Redis pubsub sinks, and installs ``_InterceptHandler`` to route
  stdlib logging (uvicorn/fastapi/celery/llama_index) into loguru; structlog is
  configured with a processor chain (including the custom
  ``add_open_telemetry_span`` that injects trace_id/span_id) and a
  ``_JsonlFileLoggerFactory`` that writes rotating JSONL.
- ``get_ai_logger(name)``: returns a structlog BoundLogger bound to
  ``component=name``, writing to ``logs/ai_telemetry.jsonl``; falls back to
  stdlib ``logging.getLogger`` when telemetry is disabled.
- ``get_logger(name)``: returns loguru ``logger.bind(name=name, **get_context())``,
  reading contextvars on each call so dynamic fields like trace_id stay current;
  falls back to stdlib when disabled.
- ``truncate(text, limit)``: helper for truncating telemetry fields.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
from pathlib import Path
from types import FrameType
from typing import Any

import structlog
from structlog.processors import CallsiteParameter
from structlog.types import EventDict, Processor, WrappedLogger

from eagle_rag.telemetry.context import bind_context, get_context

__all__ = [
    "configure_logging",
    "get_ai_logger",
    "get_logger",
    "truncate",
]

# Idempotency flag: configure_logging returns immediately once already run.
_configured: bool = False
# Master telemetry switch (set by configure_logging): when False, get_*_logger falls back to stdlib.
_enabled: bool = False

# structlog AI logger factory (assigned after configure).
_ai_logger_factory: Any = None

# JSONL logger name for structlog output (skipped by _InterceptHandler to avoid loops).
_AI_TELEMETRY_LOGGER_NAME = "eagle_ai_telemetry"

# loguru pretty format: time/level/name:trace_id/message (extras pre-set to avoid KeyError).
_PRETTY_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{extra[name]}</cyan>:<cyan>{extra[trace_id]}</cyan> | "
    "{message}"
)


def configure_logging(settings: Any) -> None:
    """Configure loguru (ops) + structlog (AI events). Idempotent: re-calls return early."""
    global _configured, _enabled, _ai_logger_factory
    if _configured:
        return

    tel = settings.telemetry
    if not tel.enabled:
        # Master switch off: minimal stdlib config as fallback.
        _enabled = False
        logging.basicConfig(level=logging.INFO)
        _configured = True
        return

    _enabled = True

    # Ensure log directories exist.
    Path(tel.op_log_file).parent.mkdir(parents=True, exist_ok=True)
    Path(tel.ai_log_file).parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # loguru configuration (ops logging)
    # ------------------------------------------------------------------
    from loguru import logger

    logger.remove()
    # Pre-set extra defaults so {extra[name]}/{extra[trace_id]} in format never KeyError.
    logger.configure(extra={"name": "", "trace_id": ""})

    # stderr sink: pretty-colored on TTY, same format otherwise (loguru auto-detects colorize).
    logger.add(
        sys.stderr,
        level=tel.op_log_level,
        format=_PRETTY_FORMAT,
        colorize=sys.stderr.isatty(),
        backtrace=True,
        diagnose=True,
    )

    # Rotating file sink: serialize=True emits JSON; enqueue=True for async writes.
    logger.add(
        tel.op_log_file,
        level=tel.op_log_level,
        rotation=tel.op_log_rotation,
        retention=tel.op_log_retention,
        serialize=True,
        enqueue=True,
    )

    # Redis pubsub sink: publishes {level, message, timestamp, trace_id?} to redis_log_channel,
    # consumed by /admin/logs SSE (same channel "logs" as RedisLogStreamHandler in health.py).
    logger.add(
        _make_redis_sink(settings, tel.redis_log_channel),
        level=tel.op_log_level,
    )

    # ------------------------------------------------------------------
    # InterceptHandler: route stdlib logging into loguru
    # ------------------------------------------------------------------
    logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)

    # ------------------------------------------------------------------
    # structlog configuration (AI events JSONL)
    # ------------------------------------------------------------------
    _ai_logger_factory = _JsonlFileLoggerFactory(
        tel.ai_log_file,
        tel.ai_log_max_bytes,
        tel.ai_log_backup_count,
        tel.ai_log_level,
    )

    processors: list[Processor] = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        add_open_telemetry_span,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.CallsiteParameterAdder(
            {
                CallsiteParameter.FILENAME,
                CallsiteParameter.FUNC_NAME,
                CallsiteParameter.LINENO,
            }
        ),
        structlog.processors.dict_tracebacks,
        structlog.processors.JSONRenderer(),
    ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=_ai_logger_factory,
        cache_logger_on_first_use=True,
    )

    _configured = True


class _JsonlFileLoggerFactory:
    """structlog logger_factory returning a stdlib logger bound to a RotatingFileHandler.

    After the processor chain's ``JSONRenderer`` produces the final JSON string,
    ``logger.info(json_str)`` flushes it to disk via RotatingFileHandler. The
    logger sets ``propagate=False`` to prevent records reaching the root
    (InterceptHandler) and looping.
    """

    def __init__(
        self,
        path: str,
        max_bytes: int,
        backup_count: int,
        level: str,
    ) -> None:
        self._logger = logging.getLogger(_AI_TELEMETRY_LOGGER_NAME)
        # Idempotent: avoid duplicate addHandler (configure_logging is already idempotent).
        if not self._logger.handlers:
            handler = logging.handlers.RotatingFileHandler(
                path,
                maxBytes=max_bytes,
                backupCount=backup_count,
                encoding="utf-8",
            )
            handler.setFormatter(logging.Formatter("%(message)s"))
            self._logger.addHandler(handler)
        self._logger.setLevel(getattr(logging, level.upper(), logging.INFO))
        # Critical: do not propagate to root, or InterceptHandler routes JSONL back into loguru.
        self._logger.propagate = False

    def __call__(self, name: str) -> Any:
        # Return the same logger (component is injected via structlog bind).
        return self._logger


def add_open_telemetry_span(
    logger: WrappedLogger, method_name: str, event_dict: EventDict
) -> EventDict:
    """structlog processor: inject trace_id/span_id/parent_span_id.

    Prefers ``opentelemetry.trace.get_current_span()`` when the span is recording;
    when no span is recording and contextvars has no fallback trace_id, generates
    random hex on demand and caches it in contextvars, so each "request without a
    span" still has a stable trace_id for log correlation.
    """
    from opentelemetry import trace

    span = trace.get_current_span()
    if span is not None and span.is_recording():
        span_ctx = span.get_span_context()
        event_dict["trace_id"] = format(span_ctx.trace_id, "032x")
        event_dict["span_id"] = format(span_ctx.span_id, "016x")
        parent = getattr(span, "parent", None)
        if parent is not None:
            event_dict["parent_span_id"] = format(parent.span_id, "016x")
        return event_dict

    # Fallback: read trace_id from contextvars; generate and cache if absent.
    ctx = get_context()
    if "trace_id" not in ctx:
        import secrets

        bind_context(
            trace_id=secrets.token_hex(16),
            span_id=secrets.token_hex(8),
        )
        ctx = get_context()
    event_dict["trace_id"] = ctx.get("trace_id")
    event_dict["span_id"] = ctx.get("span_id")
    return event_dict


def get_ai_logger(name: str) -> Any:
    """Return the AI events logger (structlog BoundLogger bound to component=name).

    Falls back to stdlib ``logging.getLogger(name)`` when telemetry is disabled
    (provides compatible .info/.warning etc. API; telemetry calls should sit inside
    try/except so a failed kwargs call is swallowed without affecting the main path).
    """
    if not _enabled:
        return logging.getLogger(name)
    return structlog.get_logger(name).bind(component=name)


def get_logger(name: str) -> Any:
    """Return the ops logger (loguru ``logger.bind``, reading contextvars per call).

    Falls back to stdlib ``logging.getLogger(name)`` when telemetry is disabled.
    """
    if not _enabled:
        return logging.getLogger(name)
    from loguru import logger

    # Read contextvars dynamically so trace_id etc. stay current
    # (contextualize is hard to manage across awaits).
    return logger.bind(name=name, **get_context())


class _InterceptHandler(logging.Handler):
    """Forward stdlib logging records to loguru.

    Used to intercept stdlib loggers from uvicorn/fastapi/celery/llama_index and
    funnel them into loguru's multi-sink pipeline. Skips the ``eagle_ai_telemetry``
    logger (structlog JSONL output, to avoid loops). The frame-depth algorithm is
    the loguru-recommended one, ensuring correct callsite info.
    """

    def emit(self, record: logging.LogRecord) -> None:
        # Skip structlog's JSONL logger to avoid loop interception.
        if record.name == _AI_TELEMETRY_LOGGER_NAME or record.name.startswith(
            _AI_TELEMETRY_LOGGER_NAME + "."
        ):
            return

        from loguru import logger as loguru_logger

        # Map stdlib level -> loguru level.
        try:
            level: str | int = loguru_logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # Compute frame depth: skip logging internal frames so loguru locates the real callsite.
        frame: FrameType | None = logging.currentframe()
        depth = 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        loguru_logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def _make_redis_sink(settings: Any, channel: str) -> Any:
    """Build a loguru Redis pubsub sink closure (caches client, silently swallows publish failures).

    Publishes to the same channel name (default ``logs``) as ``RedisLogStreamHandler``
    in ``api/health.py``, with schema ``{level, message, timestamp, trace_id?}``, so
    the frontend SSE needs no changes. Reuses ``settings.celery.broker_url`` for the
    Redis client without creating a new connection pool.
    """
    _redis_client: Any = None

    def sink(message: Any) -> None:
        nonlocal _redis_client
        record = message.record
        payload: dict[str, Any] = {
            "level": record["level"].name,
            "message": record["message"],
            "timestamp": record["time"].isoformat(),
        }
        extra = record["extra"]
        if "trace_id" in extra:
            payload["trace_id"] = extra["trace_id"]
        try:
            if _redis_client is None:
                import redis

                _redis_client = redis.Redis.from_url(settings.celery.broker_url)
            _redis_client.publish(channel, json.dumps(payload, ensure_ascii=False))
        except Exception:  # noqa: BLE001
            # Silent: Redis being unreachable must not affect other sinks (stderr/file).
            pass

    return sink


def truncate(text: Any, limit: int) -> Any:
    """Truncate a string to ``limit`` chars and append a ``...<truncated>`` marker.

    None / non-str values are returned unchanged (telemetry fields may be None or
    non-string). Used by AI-event telemetry for prompt/completion/query/hits fields
    to avoid JSONL bloat and full sensitive-data persistence.
    """
    if text is None or not isinstance(text, str):
        return text
    if len(text) > limit:
        return text[:limit] + "...<truncated>"
    return text
