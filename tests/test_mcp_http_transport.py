"""MCP Streamable HTTP transport tests (fastmcp, stateless + JSON-only).

Verifies tool listing/calling, ASGI mounting, and HTTP JSON contracts:
- Framework switch: ``from fastmcp import FastMCP`` (not ``mcp.server.fastmcp``).
- Four tools (``ingest`` / ``query`` / ``retrieve_text`` / ``retrieve_visual``) can be listed
  and called via the fastmcp ``Client`` (in-memory transport); signatures and return
  contracts are unchanged.
- Both the standalone uvicorn entrypoint ``mcp_server_http.app`` and the FastAPI-mounted
  ``app`` are valid ASGI apps; the ``/mcp`` mount exists; ``POST /mcp`` ``tools/list`` over
  HTTP returns 4 tools with ``Content-Type: application/json`` (stateless + JSON-only, not SSE).
- ``retrieve_text`` / ``query`` tool calls go through a mocked service layer and return
  structures consistent with the documented contract (no real Milvus / VLM / PostgreSQL).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from fastmcp import Client

from eagle_rag.api.app import app
from eagle_rag.api.mcp_http import build_mcp_app
from eagle_rag.api.mcp_server import TOOL_DEFINITIONS, mcp
from eagle_rag.api.mcp_server_http import app as standalone_app

EXPECTED_TOOL_NAMES = {
    "core_ingest",
    "core_query",
    "core_retrieve_text",
    "core_retrieve_visual",
}


@pytest.fixture(autouse=True)
def _mock_record_mcp_call():
    """Mock ``record_mcp_call`` (DB call-log side effect) so tests do not require PostgreSQL.

    Tool functions call ``record_mcp_call`` on both success and failure paths to write the
    ``mcp_call_log`` table. The test environment has no DB, so ``record_mcp_call`` would raise
    ``OperationalError``; the except branch then calls ``logger.opt(...)``, but with telemetry
    disabled ``get_logger`` returns a stdlib Logger (no ``opt`` method) -> ``AttributeError``
    would abort the tool. Mocking removes the side effect so tests focus on MCP transport and
    tool return contracts (same rationale as conftest mocking ``kb_exists_sync``).
    """
    with patch("eagle_rag.admin.mcp_log.record_mcp_call"):
        yield


# ---------------------------------------------------------------------------
# 1. Framework switch: mcp instance comes from PrefectHQ/fastmcp
# ---------------------------------------------------------------------------


def test_mcp_instance_is_from_prefecthq_fastmcp() -> None:
    """The ``mcp`` class is ``fastmcp.server.server.FastMCP`` (not ``mcp.server.fastmcp``)."""
    assert type(mcp).__module__ == "fastmcp.server.server"
    assert type(mcp).__name__ == "FastMCP"


def test_tool_definitions_constant_unchanged() -> None:
    """``TOOL_DEFINITIONS`` still contains 4 tool metadata entries; names match the decorator
    registrations."""
    names = {t["name"] for t in TOOL_DEFINITIONS}
    assert names == EXPECTED_TOOL_NAMES


# ---------------------------------------------------------------------------
# 2. ASGI app construction: mount / standalone entrypoint
# ---------------------------------------------------------------------------


def test_build_mcp_app_returns_starlette_with_lifespan() -> None:
    """``build_mcp_app`` returns a Starlette ASGI sub-app with a ``.lifespan``."""
    sub_app = build_mcp_app(path="/")
    assert type(sub_app).__module__ == "fastmcp.server.http"
    assert hasattr(sub_app, "lifespan")


def test_fastapi_app_mounts_mcp_at_streamable_path() -> None:
    """FastAPI ``app.routes`` contains the ``settings.mcp.streamable_http_path`` mount (default
    ``/mcp``)."""
    from eagle_rag.config import get_settings

    mount_path = get_settings().mcp.streamable_http_path
    paths = {getattr(r, "path", None) for r in app.routes}
    assert mount_path in paths


def test_standalone_app_is_asgi() -> None:
    """Standalone entrypoint ``mcp_server_http.app`` is a composite Starlette ASGI app."""
    assert type(standalone_app).__module__ == "starlette.applications"
    assert callable(standalone_app)
    route_paths = {getattr(r, "path", None) for r in standalone_app.routes}
    assert "/health" in route_paths
    assert "/metrics" in route_paths


# ---------------------------------------------------------------------------
# 3. Tool contracts (in-memory fastmcp Client, no HTTP server)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inmem_client_lists_four_tools() -> None:
    """In-memory ``Client(mcp)`` lists 4 tools; names match ``TOOL_DEFINITIONS``."""
    async with Client(mcp) as client:
        tools = await client.list_tools()
        names = {t.name for t in tools}
        assert names == EXPECTED_TOOL_NAMES


@pytest.mark.asyncio
async def test_inmem_client_retrieve_text_contract() -> None:
    """``retrieve_text`` returns ``list[{node_id, text, score, metadata}]`` (metadata trimmed)."""
    fake_node = SimpleNamespace(
        node_id="n1",
        metadata={
            "path": "财政/个税/起征点",
            "level": 2,
            "summary": "个税起征点章节",
            "document_id": "d1",
            "source_type": "policy",
            # Internal field that must not leak.
            "connect_to": ["x"],
        },
    )
    fake_node.get_content = MagicMock(return_value="起征点为每月5000元")
    fake_nws = SimpleNamespace(node=fake_node, score=0.95)

    fake_retriever = MagicMock()
    fake_retriever.retrieve.return_value = [fake_nws]

    with patch(
        "eagle_rag.retrievers.knowhere_graph_retriever.KnowhereGraphRetriever",
        return_value=fake_retriever,
    ):
        async with Client(mcp) as client:
            result = await client.call_tool(
                "core_retrieve_text", {"query": "个税起征点", "top_k": 5}
            )

    # fastmcp wraps a list return value into structured_content {"result": [...]} (wrap_result).
    payload = result.structured_content
    items = payload.get("result", payload) if isinstance(payload, dict) else payload
    assert isinstance(items, list)
    assert len(items) == 1
    item = items[0]
    assert item["node_id"] == "n1"
    assert item["text"] == "起征点为每月5000元"
    assert item["score"] == pytest.approx(0.95)
    meta = item["metadata"]
    # Agreed fields are preserved.
    assert meta["path"] == "财政/个税/起征点"
    assert meta["level"] == 2
    assert meta["summary"] == "个税起征点章节"
    assert meta["document_id"] == "d1"
    assert meta["source_type"] == "policy"
    # Internal fields do not leak.
    assert "connect_to" not in meta


@pytest.mark.asyncio
async def test_inmem_client_retrieve_text_scope_filtering() -> None:
    """The ``scope`` argument filters out results whose ``document_id`` is not in scope."""
    n_in = SimpleNamespace(
        node_id="n1",
        metadata={"document_id": "d1", "path": "p", "level": 1, "summary": "s", "source_type": "t"},
    )
    n_in.get_content = MagicMock(return_value="in")
    n_out = SimpleNamespace(
        node_id="n2",
        metadata={"document_id": "d2", "path": "p", "level": 1, "summary": "s", "source_type": "t"},
    )
    n_out.get_content = MagicMock(return_value="out")
    fake_retriever = MagicMock()
    fake_retriever.retrieve.return_value = [
        SimpleNamespace(node=n_in, score=0.9),
        SimpleNamespace(node=n_out, score=0.8),
    ]

    with patch(
        "eagle_rag.retrievers.knowhere_graph_retriever.KnowhereGraphRetriever",
        return_value=fake_retriever,
    ):
        async with Client(mcp) as client:
            result = await client.call_tool(
                "core_retrieve_text", {"query": "x", "scope": ["d1"], "top_k": 5}
            )

    payload = result.structured_content
    items = payload.get("result", payload) if isinstance(payload, dict) else payload
    assert len(items) == 1
    assert items[0]["node_id"] == "n1"


@pytest.mark.asyncio
async def test_inmem_client_query_contract() -> None:
    """``query`` returns ``{answer, sources, route, steps}`` (extra fields are trimmed)."""
    fake_engine = MagicMock()
    fake_engine.query.return_value = {
        "answer": "起征点为5000元",
        "sources": {"text": [{"type": "text", "path": "个税", "document_id": "d1"}], "image": []},
        "route": {"mode": "auto", "selected": ["text"], "reason": "启发式"},
        "steps": [{"name": "route"}, {"name": "generate"}],
        # Extra field should be trimmed.
        "extra_field": "should_be_dropped",
    }

    with patch(
        "eagle_rag.router.router_engine.EagleRouterQueryEngine",
        return_value=fake_engine,
    ):
        async with Client(mcp) as client:
            result = await client.call_tool("core_query", {"query": "个税起征点", "mode": "auto"})

    payload = result.structured_content
    data = payload.get("result", payload) if isinstance(payload, dict) else payload
    assert set(data.keys()) == {"answer", "sources", "route", "steps"}
    assert data["answer"] == "起征点为5000元"
    assert data["sources"]["text"][0]["document_id"] == "d1"
    assert data["route"]["mode"] == "auto"
    assert [s["name"] for s in data["steps"]] == ["route", "generate"]


@pytest.mark.asyncio
async def test_inmem_client_tool_error_returns_error_dict() -> None:
    """When the service layer raises, the tool returns ``{"error": ...}`` (no session abort)."""
    with patch(
        "eagle_rag.retrievers.pixelrag_visual_retriever.PixelRAGVisualRetriever",
        side_effect=RuntimeError("milvus down"),
    ):
        async with Client(mcp) as client:
            result = await client.call_tool("core_retrieve_visual", {"query": "图表"})

    payload = result.structured_content
    # retrieve_visual failure returns [{"error": ...}] (list wrapper).
    items = payload.get("result", payload) if isinstance(payload, dict) else payload
    assert isinstance(items, list)
    assert "error" in items[0]
    assert "RuntimeError" in items[0]["error"]


# ---------------------------------------------------------------------------
# 4. HTTP transport (FastAPI TestClient -> /mcp mount)
# ---------------------------------------------------------------------------


def _mcp_initialize_post(client: TestClient, url: str) -> dict:
    """Send an MCP initialize request and return the parsed JSON response."""
    resp = client.post(
        url,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1.0"},
            },
        },
        headers={"Accept": "application/json, text/event-stream"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    return resp.json()


def _mcp_tools_list_post(client: TestClient, url: str) -> dict:
    """Send an MCP tools/list request and return the parsed JSON response."""
    resp = client.post(
        url,
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        headers={"Accept": "application/json, text/event-stream"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    return resp.json()


def test_http_tools_list_returns_four_tools_via_mounted_app() -> None:
    """``POST /mcp`` tools/list on the FastAPI-mounted app returns 4 tools as JSON (not SSE)."""
    with TestClient(app) as c:
        _mcp_initialize_post(c, "/mcp")
        body = _mcp_tools_list_post(c, "/mcp")
    assert "result" in body
    names = {t["name"] for t in body["result"]["tools"]}
    assert names == EXPECTED_TOOL_NAMES


def test_http_tools_list_returns_four_tools_via_standalone_app() -> None:
    """``POST /`` tools/list on the standalone uvicorn entrypoint returns 4 tools."""
    with TestClient(standalone_app) as c:
        _mcp_initialize_post(c, "/")
        body = _mcp_tools_list_post(c, "/")
    assert "result" in body
    names = {t["name"] for t in body["result"]["tools"]}
    assert names == EXPECTED_TOOL_NAMES


def test_existing_rest_mcp_tools_route_not_shadowed() -> None:
    """After mounting ``/mcp``, REST ``GET /mcp/tools`` route stays reachable (not shadowed)."""
    with TestClient(app) as c:
        resp = c.get("/mcp/tools")
    assert resp.status_code == 200
    data = resp.json()
    names = {t["name"] for t in data.get("tools", [])}
    assert names == EXPECTED_TOOL_NAMES


def test_gzip_middleware_registered() -> None:
    """FastAPI ``app`` has GZipMiddleware registered."""
    middleware_names = {m.cls.__name__ for m in app.user_middleware}
    assert "GZipMiddleware" in middleware_names
    # Pre-existing middlewares are preserved.
    assert "TelemetryMiddleware" in middleware_names
    assert "CORSMiddleware" in middleware_names
