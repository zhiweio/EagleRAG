"""Shared test fixtures."""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest
import structlog.contextvars


def _reset_telemetry_modules() -> None:
    """Reset idempotency flags and runtime state of telemetry submodules.

    ``configure_telemetry``/``configure_logging`` use module-level ``_configured``
    flags for idempotency; not resetting them between tests prevents subsequent
    tests from re-initializing with new config (e.g. a tmp log path). Also clears
    structlog contextvars, the in-house ContextVar, and handlers on the
    ``eagle_ai_telemetry`` stdlib logger (to avoid stale RotatingFileHandlers
    pointing at deleted tmp paths). The OTel global TracerProvider is process-level
    immutable once set, so here we only reset the ``_tracer`` reference, forcing
    ``trace_span`` to degrade to a no-op until the next ``configure_tracing``.
    """
    import eagle_rag.telemetry as tel
    import eagle_rag.telemetry.context as ctx
    import eagle_rag.telemetry.logging_setup as ls
    import eagle_rag.telemetry.tracing as tr

    tel._configured = False
    ls._configured = False
    ls._enabled = False
    ls._ai_logger_factory = None
    ctx._enabled = False
    ctx._CTX.set({})
    tr._tracer = None
    tr._tracing_enabled = False
    structlog.contextvars.clear_contextvars()
    ai_lg = logging.getLogger("eagle_ai_telemetry")
    ai_lg.handlers = []
    ai_lg.propagate = True


@pytest.fixture(autouse=True)
def _reset_telemetry_state():
    """Reset telemetry module state before and after each test to avoid cross-test contamination."""
    _reset_telemetry_modules()
    yield
    _reset_telemetry_modules()


@pytest.fixture(autouse=True)
def _reset_plugin_manager_singleton():
    """Avoid cross-test plugin/MCP lifespan contamination."""
    yield
    from eagle_rag.plugins import reset_plugin_manager

    reset_plugin_manager()


@pytest.fixture(autouse=True)
def _kb_registered():
    """Treat KB as registered for ingest/query tests (no real Postgres hit)."""
    with (
        patch("eagle_rag.db.repositories.kb.kb_exists_sync", return_value=True),
        patch("eagle_rag.db.repositories.kb.get_pdf_ratio_sync", return_value=None),
        patch("eagle_rag.kb.registry.kb_exists_sync", return_value=True),
        patch("eagle_rag.kb.registry.get_pdf_ratio_sync", return_value=None),
    ):
        yield
