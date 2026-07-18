"""Eagle-RAG FastAPI application.

Aggregates all APIRouters: documents/images, ingest/tasks, health/admin,
query/sessions. No authentication middleware (internal network only). PostgreSQL
schema is managed by Alembic; run ``alembic upgrade head`` (or ``task db:migrate``)
before deployment.
"""

from __future__ import annotations

import uvicorn
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from eagle_rag.api.deps import enforce_plugin_namespace_header
from eagle_rag.api.mcp_http import build_mcp_app, get_combined_lifespan
from eagle_rag.api.schemas.common import RootResponse
from eagle_rag.config import get_settings
from eagle_rag.metrics import health_handler, metrics_handler
from eagle_rag.telemetry import TelemetryMiddleware, get_logger

logger = get_logger(__name__)
settings = get_settings()

# fastmcp streamable HTTP sub-app. When mounted, the sub-app internal path must be
# "/" (root): Starlette ``Mount`` strips the prefix and the remaining path is "/",
# so the sub-app must route on "/" to match. Passing ``streamable_http_path`` here
# would produce a doubled ``/mcp/mcp`` path (see mcp_http.py for details).
mcp_app = build_mcp_app(path="/")

# Combined lifespan: run ``configure_telemetry`` first (mirrors the original
# lifespan), then start the fastmcp ``StreamableHTTPSessionManager`` task group
# (``mcp_app.lifespan``) so MCP HTTP requests don't raise
# ``Task group is not initialized``.
app = FastAPI(
    title="Eagle-RAG",
    version="0.1.0",
    lifespan=get_combined_lifespan(settings.mcp.streamable_http_path),
    dependencies=[Depends(enforce_plugin_namespace_header)],
)

# Telemetry middleware: open a SERVER span per HTTP request and bind
# request_id/trace_id (does not read the body).
app.add_middleware(TelemetryMiddleware)

# GZip compression for >1KB JSON responses (retrieval results often exceed 1KB).
app.add_middleware(GZipMiddleware, minimum_size=1024)

# CORS: allow the frontend (Next.js defaults to localhost:3000) to call cross-origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount routers (each module exposes its own APIRouter to avoid circular imports).
from eagle_rag.api.attachments import router as attachments_router  # noqa: E402
from eagle_rag.api.documents import images_router  # noqa: E402
from eagle_rag.api.documents import router as documents_router  # noqa: E402
from eagle_rag.api.health import admin_router  # noqa: E402
from eagle_rag.api.health import router as health_router  # noqa: E402
from eagle_rag.api.ingest import router as ingest_router  # noqa: E402
from eagle_rag.api.knowledge_bases import router as kb_router  # noqa: E402
from eagle_rag.api.notifications import router as notifications_router  # noqa: E402
from eagle_rag.api.tags import router as tags_router  # noqa: E402
from eagle_rag.api.users import router as users_router  # noqa: E402

app.include_router(health_router)
app.include_router(documents_router)
app.include_router(images_router)
app.include_router(ingest_router)
app.include_router(kb_router)
app.include_router(tags_router)
app.include_router(attachments_router)
app.include_router(notifications_router)
app.include_router(users_router)
app.include_router(admin_router)

# Query/session routes (optional mount when the module is available).
try:
    from eagle_rag.api.query import router as query_router

    app.include_router(query_router)
except ImportError:
    logger.info("query router not available, skipping mount")

# Mount the fastmcp streamable HTTP sub-app (stateless + JSON-only). Must be
# mounted after all ``include_router`` calls so the ``/mcp/tools`` REST route
# registers first and matches with priority; only ``/mcp`` (exact) falls through
# to the MCP sub-app. The sub-app internal path is "/" (see above).
app.mount(settings.mcp.streamable_http_path, mcp_app)

# Prometheus metrics + health endpoints (for Prometheus scraping, Docker Swarm
# healthcheck, and HAProxy httpchk probes).
app.add_api_route("/metrics", metrics_handler, methods=["GET"], include_in_schema=False)
app.add_api_route("/health", health_handler, methods=["GET"], include_in_schema=False)


@app.get("/", response_model=RootResponse)
def root() -> RootResponse:
    """Root path info."""
    return RootResponse(app="Eagle-RAG", version="0.1.0", docs="/docs")


if __name__ == "__main__":
    uvicorn.run(app, host=settings.app.host, port=settings.app.port)
