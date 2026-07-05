"""MCP HTTP transport mounting helpers (fastmcp streamable HTTP, stateless + JSON-only).

Wraps ``eagle_rag.api.mcp_server.mcp`` (PrefectHQ/fastmcp ``FastMCP`` instance) via
``mcp.http_app(...)`` to produce a Starlette ASGI sub-app for two use cases:

1. **Mount into the existing FastAPI** (``eagle_rag/api/app.py``):
   ``app.mount("/mcp", mcp_app)`` lets the MCP service share the same process and
   telemetry middleware as the ``/query`` and ``/ingest`` REST routes.
2. **Standalone uvicorn process** (``eagle_rag/api/mcp_server_http.py``):
   ``uvicorn.run(app, ...)`` scales independently by MCP traffic, decoupled from
   REST traffic.

Key constraints (verified against fastmcp v3.4.2 source + experience):

- ``mcp.http_app(path=...)`` registers a ``Route(path, ...)`` inside the sub-app.
  When the sub-app is mounted via ``app.mount(prefix, sub_app)``, Starlette
  ``Mount`` strips the ``prefix`` and passes the remaining path to the sub-app.
  Therefore **the sub-app internal ``path`` must be ``"/"`` when mounted**;
  otherwise a doubled ``/mcp/mcp`` path results (the spec text
  ``path=streamable_http_path`` was verified to be wrong; this module follows the
  actual API behavior: pass ``path="/"`` for both mount and standalone deployment).
- **Lifespan composition**: the fastmcp streamable HTTP sub-app depends on
  ``mcp_app.lifespan`` to start the ``StreamableHTTPSessionManager`` task group; if
  the host FastAPI does not fold ``mcp_app.lifespan`` into its own lifespan,
  requests raise ``Task group is not initialized``. ``get_combined_lifespan``
  merges telemetry initialization (``configure_telemetry``) with
  ``mcp_app.lifespan`` into a single lifespan for the host FastAPI.
- ``stateless_http`` / ``json_response`` are passed explicitly to ``http_app`` to
  avoid the timing constraint that ``FASTMCP_STATELESS_HTTP`` must be set before
  ``import fastmcp``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from eagle_rag.api.mcp_server import configure_mcp_auth, mcp
from eagle_rag.config import get_settings
from eagle_rag.telemetry import configure_telemetry, get_logger

logger = get_logger(__name__)

__all__ = ["build_mcp_app", "get_combined_lifespan", "mcp"]


def build_mcp_app(path: str | None = None) -> Any:
    """Build the fastmcp streamable HTTP ASGI sub-app.

    Args:
        path: Sub-app internal route path. ``None`` falls back to
            ``settings.mcp.streamable_http_path`` (kept for spec compatibility).
            **Pass ``"/"`` for the mount scenario**: when the host FastAPI mounts
            via ``app.mount(settings.mcp.streamable_http_path, mcp_app)``, Starlette
            ``Mount`` strips the prefix and the remaining path is ``"/"``, so the
            sub-app internal route must also be ``"/"`` to match (otherwise a
            doubled ``/mcp/mcp`` path results).

    Returns:
        ``StarletteWithLifespan`` ASGI sub-app with a ``.lifespan`` attribute
        (must be invoked by the host FastAPI lifespan to initialize the fastmcp
        session manager task group).
    """
    settings = get_settings()
    # Inject the auth provider (static-token / oauth-github / oauth-custom) before
    # building. ``mcp.auth`` is a public attribute; ``http_app()`` uses it to mount
    # auth middleware at the ASGI layer.
    configure_mcp_auth()
    if path is None:
        path = settings.mcp.streamable_http_path
    return mcp.http_app(
        path=path,
        transport="http",
        stateless_http=settings.mcp.stateless_http,
        json_response=settings.mcp.json_response,
    )


def get_combined_lifespan(mcp_app: Any) -> Any:
    """Return a host lifespan callable combining telemetry and fastmcp ``mcp_app.lifespan``.

    The return value is an ``@asynccontextmanager``-decorated lifespan function
    that can be passed directly to ``FastAPI(lifespan=...)`` /
    ``Starlette(lifespan=...)`` (Starlette invokes it with the host app instance
    and expects an async context manager).

    Entry order:
    1. ``configure_telemetry(get_settings())`` -- initialize loguru + structlog + OTel
       (idempotent; failure only logs and does not block startup, mirroring the
       original ``app.py`` lifespan behavior).
    2. ``mcp_app.lifespan`` -- start the fastmcp ``StreamableHTTPSessionManager``
       task group (even in stateless mode the task group must start to host the
       per-request transport).

    Exit is in reverse order (exit mcp_app lifespan first, then return).
    """

    @asynccontextmanager
    async def combined_lifespan(app: Any) -> AsyncIterator[None]:
        try:
            configure_telemetry(get_settings())
        except Exception:  # noqa: BLE001
            logger.exception("telemetry configure failed")
        # ``mcp_app.lifespan`` is a Starlette ``Lifespan`` callable and must be
        # invoked with the app instance.
        async with mcp_app.lifespan(mcp_app):
            yield

    return combined_lifespan
