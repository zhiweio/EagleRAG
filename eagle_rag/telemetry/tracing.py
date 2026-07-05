"""OpenTelemetry tracing: trace propagation across FastAPI/Celery/LlamaIndex + GenAI semantics.

- ``configure_tracing(settings)``: builds a TracerProvider (resource includes
  service.name/version/environment), selects an exporter based on
  ``tracing_enabled``/``otlp_endpoint`` (OTLP gRPC + BatchSpanProcessor /
  ConsoleSpanExporter / no processor, local only). When disabled, still installs
  a NoOp TracerProvider so ``add_open_telemetry_span``'s fallback injects a trace_id.
- ``trace_span(name, kind=...)``: dual form, contextmanager + argumentless decorator.
  On enter ``bind_context(trace_id=, span_id=)``; on exception ``record_exception``
  + ``set_status(ERROR)``; on exit ``clear_context(trace_id, span_id)``.
- ``set_llm_span_attributes(span, *, system, model, prompt, completion, ...)``: sets
  ``gen_ai.*`` attributes per GenAI semantic conventions, truncating
  prompt/completion per telemetry config.
- ``TelemetryMiddleware``: FastAPI middleware opening a SERVER span per request and
  binding request_id.
- ``register_celery_signals(app)``: Celery task_prerun/postrun/failure signal hooks
  to continue traces.
- ``send_task_with_trace(...)``: injects the current span context into headers when
  dispatching a Celery task.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from functools import wraps
from typing import Any
from uuid import uuid4

from opentelemetry import trace
from opentelemetry.trace import SpanKind, StatusCode
from opentelemetry.trace.span import Span

from eagle_rag.telemetry.context import bind_context, clear_context
from eagle_rag.telemetry.logging_setup import truncate

__all__ = [
    "configure_tracing",
    "trace_span",
    "get_current_span",
    "set_llm_span_attributes",
    "TelemetryMiddleware",
    "register_celery_signals",
    "send_task_with_trace",
]

# Configured tracer (assigned after configure_tracing). None means telemetry is
# disabled and trace_span degrades to no-op.
_tracer: Any = None
# Whether tracing is enabled (telemetry.enabled=true AND tracing_enabled=true).
_tracing_enabled: bool = False


def configure_tracing(settings: Any) -> None:
    """Build a TracerProvider and install the global tracer.

    - ``telemetry.enabled=false`` or ``tracing_enabled=false``: still installs a
      NoOp TracerProvider (spans are created but not exported), and the
      ``add_open_telemetry_span`` fallback injects a trace_id. ``_tracing_enabled``
      is set to False.
    - Enabled with ``otlp_endpoint``: OTLP gRPC exporter + BatchSpanProcessor.
    - Enabled without endpoint: ConsoleSpanExporter (dev debugging).
    """
    global _tracer, _tracing_enabled

    from opentelemetry.sdk.trace import TracerProvider

    tel = settings.telemetry
    if not tel.enabled or not tel.tracing_enabled:
        # NoOp default: spans are created but not exported; still yields a valid
        # trace_id/span_id for log correlation.
        trace.set_tracer_provider(TracerProvider())
        _tracer = trace.get_tracer("eagle-rag")
        _tracing_enabled = False
        return

    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create(
        {
            "service.name": tel.service_name,
            "service.version": "0.1.0",
            "deployment.environment": tel.environment,
        }
    )
    provider = TracerProvider(resource=resource)

    if tel.otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )

        exporter = OTLPSpanExporter(endpoint=tel.otlp_endpoint, insecure=tel.otlp_insecure)
        provider.add_span_processor(BatchSpanProcessor(exporter))
    else:
        # Dev with no endpoint: console output for debugging.
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter

        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)
    _tracer = trace.get_tracer("eagle-rag")
    _tracing_enabled = True


def trace_span(name: Any = None, kind: SpanKind = SpanKind.INTERNAL) -> Any:
    """Open a child span; dual form: contextmanager or argumentless decorator.

    Usage:
    - ``with trace_span("route") as span: ...``
    - ``@trace_span`` (argumentless decorator; span name taken from the function name)
    - ``@trace_span("custom")`` (named decorator; relies on the contextmanager's __call__)

    On enter ``bind_context(trace_id=, span_id=)``; on exception
    ``record_exception`` + ``set_status(ERROR)``; on exit
    ``clear_context(trace_id, span_id)``. When ``_tracer`` is None (telemetry
    unconfigured) it degrades to a no-op (yield None).
    """
    # @trace_span (argumentless decorator): name is actually the decorated function.
    if callable(name) and not isinstance(name, str):
        func = name
        if asyncio.iscoroutine_function(func):

            @wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                with _trace_span_context(func.__name__, kind):
                    return await func(*args, **kwargs)

            return async_wrapper

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            with _trace_span_context(func.__name__, kind):
                return func(*args, **kwargs)

        return wrapper

    # with trace_span("route") or @trace_span("route")
    return _trace_span_context(name, kind)


@contextmanager
def _trace_span_context(name: str | None, kind: SpanKind = SpanKind.INTERNAL) -> Iterator[Any]:
    """contextmanager implementation backing trace_span."""
    if _tracer is None:
        # Telemetry unconfigured: no-op, do not bind context.
        yield None
        return

    cm = _tracer.start_as_current_span(name or "span", kind=kind)
    with cm as span:
        try:
            if span is not None and span.is_recording():
                span_ctx = span.get_span_context()
                bind_context(
                    trace_id=format(span_ctx.trace_id, "032x"),
                    span_id=format(span_ctx.span_id, "016x"),
                )
            yield span
        except BaseException:
            if span is not None and span.is_recording():
                span.record_exception(sys.exc_info()[1])
                span.set_status(StatusCode.ERROR)
            raise
        finally:
            # Restore: clear the trace_id/span_id bound by this span
            # (the parent span is still held by OTel context).
            clear_context("trace_id", "span_id")


def get_current_span() -> Any:
    """Return the current OTel span (INVALID_SPAN/None when no active span)."""
    return trace.get_current_span()


def set_llm_span_attributes(
    span: Span | None,
    *,
    system: str,
    model: str,
    prompt: Any,
    completion: Any,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    **extra: Any,
) -> None:
    """Set span attributes per GenAI semantic conventions (``gen_ai.*``).

    prompt/completion are truncated per ``telemetry.prompt_truncate``/``completion_truncate``.
    No-op when span is None or not recording.
    """
    if span is None or not span.is_recording():
        return

    # Truncation lengths come from settings (lazy import to avoid a circular import).
    from eagle_rag.config import get_settings

    tel = get_settings().telemetry

    span.set_attribute("gen_ai.system", system)
    span.set_attribute("gen_ai.request.model", model)
    span.set_attribute("gen_ai.prompt", truncate(prompt, tel.prompt_truncate))
    span.set_attribute("gen_ai.completion", truncate(completion, tel.completion_truncate))
    if prompt_tokens is not None:
        span.set_attribute("gen_ai.usage.prompt_tokens", prompt_tokens)
    if completion_tokens is not None:
        span.set_attribute("gen_ai.usage.completion_tokens", completion_tokens)
    for k, v in extra.items():
        span.set_attribute(f"gen_ai.{k}", v)


class TelemetryMiddleware:
    """FastAPI/Starlette middleware: opens a SERVER span per request and binds request_id/trace_id.

    Does not read the request body (the query context's session_id/kb_name is bound
    explicitly by the handler via bind_context, so the middleware reading the body
    would consume the stream and break downstream). Extracts W3C traceparent from
    request headers to continue an upstream trace.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        from opentelemetry.propagate import extract

        # Extract trace context from request headers (supports upstream traceparent continuation).
        headers = scope.get("headers") or []
        carrier = {k.decode("latin-1"): v.decode("latin-1") for k, v in headers}
        ctx = extract(carrier)

        method = scope.get("method", "UNKNOWN")
        path = scope.get("path", "/")
        request_id = str(uuid4())

        tracer = _tracer or trace.get_tracer("eagle-rag")
        with tracer.start_as_current_span(
            f"{method} {path}", kind=SpanKind.SERVER, context=ctx
        ) as span:
            if span is not None and span.is_recording():
                span_ctx = span.get_span_context()
                bind_context(
                    request_id=request_id,
                    http_method=method,
                    http_route=path,
                    trace_id=format(span_ctx.trace_id, "032x"),
                    span_id=format(span_ctx.span_id, "016x"),
                )
            else:
                bind_context(request_id=request_id, http_method=method, http_route=path)

            status_code: int = 500

            async def send_wrapper(message: Any) -> None:
                nonlocal status_code
                if message["type"] == "http.response.start":
                    status_code = message.get("status", 500)
                await send(message)

            try:
                await self.app(scope, receive, send_wrapper)
            finally:
                if span is not None and span.is_recording():
                    span.set_attribute("http.status_code", status_code)
                    if status_code >= 500:
                        span.set_status(StatusCode.ERROR)
                clear_context("request_id", "http_method", "http_route", "trace_id", "span_id")


def register_celery_signals(app: Any) -> None:
    """Register Celery task_prerun/postrun/failure signal hooks to continue traces.

    - ``task_prerun``: extracts the remote parent span from ``task.request.headers``,
      opens a CONSUMER span (named ``{task.name}:{task_id}``), and pulls
      job_id/document_id/kb_name from kwargs.
    - ``task_postrun``: ends the span + ``clear_context()``.
    - ``task_failure``: ``record_exception`` + ``set_status(ERROR)``.
    """
    from celery.signals import task_failure, task_postrun, task_prerun
    from opentelemetry.propagate import extract

    @task_prerun.connect
    def _prerun(
        task_id: str,
        task: Any,
        args: tuple,
        kwargs: dict,
        **_: Any,
    ) -> None:
        headers = getattr(task.request, "headers", None) or {}
        ctx = extract(headers)
        span_name = f"{task.name}:{task_id}"
        tracer = _tracer or trace.get_tracer("eagle-rag")
        cm = tracer.start_as_current_span(span_name, kind=SpanKind.CONSUMER, context=ctx)
        span = cm.__enter__()
        # Stash on the task instance for postrun/failure to retrieve.
        task._eagle_span_cm = cm
        task._eagle_span = span

        # Pull business context from kwargs (tolerant; missing keys are skipped).
        bind_kwargs: dict[str, Any] = {}
        for key in ("job_id", "document_id", "kb_name"):
            val = kwargs.get(key)
            if val is not None:
                bind_kwargs[key] = val
        if bind_kwargs:
            bind_context(**bind_kwargs)

        if span is not None and span.is_recording():
            span_ctx = span.get_span_context()
            bind_context(
                trace_id=format(span_ctx.trace_id, "032x"),
                span_id=format(span_ctx.span_id, "016x"),
            )

    @task_postrun.connect
    def _postrun(
        task_id: str,
        task: Any,
        args: tuple,
        kwargs: dict,
        retval: Any,
        state: str,
        **_: Any,
    ) -> None:
        cm = getattr(task, "_eagle_span_cm", None)
        if cm is not None:
            try:
                cm.__exit__(None, None, None)
            except Exception:  # noqa: BLE001
                pass
            task._eagle_span_cm = None
            task._eagle_span = None
        clear_context()

    @task_failure.connect
    def _failure(
        task_id: str,
        task: Any,
        args: tuple,
        kwargs: dict,
        einfo: Any,
        **_: Any,
    ) -> None:
        span = getattr(task, "_eagle_span", None)
        if span is not None and span.is_recording():
            try:
                exc = getattr(einfo, "exception", None) or getattr(einfo, "exc", None)
                if exc is not None:
                    span.record_exception(exc)
            except Exception:  # noqa: BLE001
                pass
            try:
                span.set_status(StatusCode.ERROR, str(einfo))
            except Exception:  # noqa: BLE001
                pass


def send_task_with_trace(
    task_name: str,
    *,
    queue: str,
    kwargs: dict[str, Any],
    routing_key: str | None = None,
    task: Any = None,
) -> Any:
    """Inject current span context into headers when dispatching a Celery task.

    When telemetry is disabled, headers stay empty and the task is still dispatched
    (no trace correlation). The ``task`` parameter is kept for compatibility (unused).
    """
    from opentelemetry.propagate import inject

    headers: dict[str, str] = {}
    inject(headers)

    from eagle_rag.tasks.celery_app import app as celery_app

    return celery_app.send_task(
        task_name,
        kwargs=kwargs,
        queue=queue,
        routing_key=routing_key or queue,
        headers=headers,
    )
