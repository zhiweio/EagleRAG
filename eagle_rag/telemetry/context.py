"""Shared context for dual loggers (structlog + loguru).

Built on ``structlog.contextvars`` and a private ``contextvars.ContextVar[dict]``:
structlog merges bindings automatically via ``bind_contextvars`` in its processor
chain; loguru reads the current context dynamically in ``get_logger`` via
``logger.bind(**get_context())`` (``contextualize`` is not used because request
scope across ``await`` boundaries is hard to manage).

``_enabled`` gates ``bind_context``/``clear_context``: when
``telemetry.enabled=false`` they degrade to no-ops and stay safe to call.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

import structlog.contextvars

__all__ = [
    "bind_context",
    "clear_context",
    "get_context",
    "bind_context_scope",
    "set_enabled",
]

# Shared context container for both loggers: holds session_id/query_id/job_id/kb_name/trace_id etc.
# default={} ensures get() never raises LookupError; the default is a shared object, so it must
# only be read, never mutated in place (bind_context always replaces with a new dict to avoid
# cross-task contamination).
_CTX: ContextVar[dict[str, Any]] = ContextVar("eagle_telemetry_ctx", default={})

# Master telemetry switch: when False, bind/clear degrade to no-ops.
_enabled: bool = False


def set_enabled(flag: bool) -> None:
    """Set the master telemetry switch (called by ``configure_telemetry``)."""
    global _enabled
    _enabled = flag


def bind_context(**kv: Any) -> None:
    """Bind key/values to the current context (structlog contextvars + own ContextVar).

    loguru context is read dynamically at ``get_logger`` time via
    ``logger.bind(**get_context())``; no need to call ``contextualize`` here.
    """
    if not _enabled:
        return
    current = _CTX.get()
    new_dict = {**current, **kv}
    _CTX.set(new_dict)
    structlog.contextvars.bind_contextvars(**kv)


def clear_context(*keys: str) -> None:
    """Clear the context. With no args, clears all; with args, removes only the given keys."""
    if not _enabled:
        return
    if not keys:
        _CTX.set({})
        structlog.contextvars.clear_contextvars()
        return
    current = _CTX.get()
    for k in keys:
        current.pop(k, None)
    _CTX.set(current)
    structlog.contextvars.unbind_contextvars(*keys)


def get_context() -> dict[str, Any]:
    """Return a copy of the current context (for loguru ``logger.bind`` to read dynamically)."""
    return dict(_CTX.get())


@contextmanager
def bind_context_scope(**kv: Any) -> Iterator[None]:
    """Bind context for a request/task scope: bind on enter, clear only the bound keys on exit."""
    bind_context(**kv)
    try:
        yield
    finally:
        clear_context(*kv.keys())
