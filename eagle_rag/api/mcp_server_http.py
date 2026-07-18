"""Standalone MCP HTTP service entry (uvicorn, streamable HTTP, stateless + JSON-only).

For production deployment that scales independently by MCP traffic (decoupled
from ``/query`` and ``/ingest`` REST traffic). ``settings.mcp.standalone``
controls whether standalone deployment is enabled; ``docker/Dockerfile.mcp``
uses ``uvicorn eagle_rag.api.mcp_server_http:app --workers ${MCP_WORKERS}`` as
its ENTRYPOINT.

Usage:

- Module-level ``app``: ``uvicorn eagle_rag.api.mcp_server_http:app --host 0.0.0.0 --port 8081``
  (recommended for production; uvicorn loads by import string and supports
  ``--workers`` multiprocess prefork).
- ``python -m eagle_rag.api.mcp_server_http``: starts via ``main()``, with
  workers taken from ``settings.mcp.workers``.

Key points:

- ``FASTMCP_STATELESS_HTTP`` / ``FASTMCP_JSON_RESPONSE`` env vars are set at the
  top of the module, **before ``import fastmcp`` (via ``build_mcp_app`` ->
  ``mcp_server`` -> ``fastmcp``)**, so the ``fastmcp.settings`` singleton reads
  the correct values at instantiation; uvicorn prefork workers inherit them.
- Composite Starlette app: ``/metrics`` and ``/health`` are handled directly by
  ``eagle_rag.metrics`` handlers; all other paths are forwarded to the fastmcp
  streamable HTTP sub-app via ``Mount("/", app=mcp_app)`` (internal route "/",
  so the MCP service is exposed at root "/"). Routes match in declaration order;
  ``/metrics`` and ``/health`` precede ``Mount("/", ...)``, so the MCP sub-app
  does not intercept them.
- Lifespan is combined via ``get_combined_lifespan(mcp_app)`` to merge telemetry
  initialization with the fastmcp ``StreamableHTTPSessionManager`` task group, so
  MCP HTTP requests do not raise ``Task group is not initialized``.
"""

from __future__ import annotations

import os

# Module top level: set env vars before importing fastmcp so the
# ``fastmcp.settings`` singleton reads the correct values at instantiation
# (``fastmcp.settings`` is constructed at ``import fastmcp``; post-import env
# changes do not update the singleton). uvicorn prefork workers inherit the
# parent process env via fork. Must ``import eagle_rag.config`` first (does not
# trigger fastmcp import), then import build_mcp_app.
from eagle_rag.config import get_settings

_settings = get_settings()
if _settings.mcp.stateless_http:
    os.environ["FASTMCP_STATELESS_HTTP"] = "true"
if _settings.mcp.json_response:
    os.environ["FASTMCP_JSON_RESPONSE"] = "true"

import uvicorn  # noqa: E402
from starlette.applications import Starlette  # noqa: E402
from starlette.routing import Mount, Route  # noqa: E402

from eagle_rag.api.mcp_http import build_mcp_app, get_combined_lifespan  # noqa: E402
from eagle_rag.metrics import health_handler, metrics_handler  # noqa: E402

# fastmcp streamable HTTP sub-app (internal route path="/", MCP service exposed at root "/").
_mcp_app = build_mcp_app(path="/")

# Composite Starlette app: ``/metrics`` and ``/health`` match first; all other
# paths forward to the MCP sub-app. Routes match in declaration order:
# ``Route("/metrics", ...)`` and ``Route("/health", ...)`` precede
# ``Mount("/", app=_mcp_app)``, so they are not intercepted by the MCP sub-app.
app = Starlette(
    routes=[
        Route("/metrics", metrics_handler),
        Route("/health", health_handler),
        Mount("/", app=_mcp_app),
    ],
    lifespan=get_combined_lifespan(""),
)


def main() -> None:
    """Start the standalone MCP HTTP service (uvicorn, workers from ``settings.mcp.workers``)."""
    settings = get_settings()
    uvicorn.run(
        app,
        host=settings.mcp.host,
        port=settings.mcp.port,
        workers=settings.mcp.workers,
    )


if __name__ == "__main__":
    main()
