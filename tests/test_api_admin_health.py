"""Admin, health, and MCP HTTP endpoint contract tests.

Covers root path, health, MCP, and admin ops endpoints. Each ``/admin/*`` endpoint
mocks its underlying client/probe and verifies the response shape. All probes go
through mock stand-ins; no real Milvus/Redis/Celery/Knowhere services are required.

Mock targets follow what each handler in ``eagle_rag/api/health.py`` actually calls:
- ``/health`` and ``/admin/probes``: patch ``_probe_all`` (concurrent probe aggregation).
- ``/mcp/tools`` and ``/admin/mcp``: patch ``eagle_rag.api.mcp_server.TOOL_DEFINITIONS``.
- ``/admin/celery``: patch ``celery_app.control.inspect``.
- ``/admin/milvus``: patch ``pymilvus.MilvusClient``.
- ``/admin/pixelrag``: patch ``_probe_pixelrag`` and ``count_visual``.
- ``/admin/knowhere``: patch ``_probe_knowhere``.
- ``/admin/vlm``: patch ``get_settings`` (inject a known api_key and verify it is not leaked).
- ``/admin/config``: patch ``get_settings`` (inject a known secret and verify masking to ``***``).
- ``/admin/logs``: patch ``_log_event_generator`` (terminating generator to avoid an infinite stream
hang).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from eagle_rag.api.app import app
from eagle_rag.config import get_settings as _real_get_settings

# Eight dependency probe names (matches the order in health._PROBES).
_PROBE_NAMES = (
    "milvus",
    "knowhere",
    "pixelrag",
    "vlm",
    "redis",
    "minio",
    "celery",
    "postgres",
)


def _probe_results(*, down: set[str] | None = None) -> dict[str, dict[str, Any]]:
    """Build a mock return value for ``_probe_all``: each entry has status/detail/latency_ms."""
    down = down or set()
    return {
        name: {
            "status": "down" if name in down else "up",
            "detail": "mock",
            "latency_ms": 5,
        }
        for name in _PROBE_NAMES
    }


@pytest.fixture(scope="module")
def client() -> TestClient:
    """Build a single TestClient reused by every test in this module."""
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Root path
# ---------------------------------------------------------------------------


def test_root_returns_app_version_docs(client: TestClient) -> None:
    """GET / returns {app, version, docs} (RootResponse)."""
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["app"] == "Eagle-RAG"
    assert body["version"] == "0.1.0"
    assert body["docs"] == "/docs"
    # No extra fields should be present.
    assert set(body) == {"app", "version", "docs"}


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


def test_health_ok_when_all_probes_up(client: TestClient) -> None:
    """All probes up -> status=ok; each of the 8 dependencies carries a status field."""
    with patch("eagle_rag.api.health._probe_all", return_value=_probe_results()):
        resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    deps = body["dependencies"]
    assert set(deps) == set(_PROBE_NAMES)
    for name in _PROBE_NAMES:
        assert deps[name]["status"] == "up"
        assert "detail" in deps[name]


def test_health_degraded_when_one_probe_down(client: TestClient) -> None:
    """Any probe down -> status=degraded (still 200)."""
    with patch(
        "eagle_rag.api.health._probe_all",
        return_value=_probe_results(down={"postgres"}),
    ):
        resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["dependencies"]["postgres"]["status"] == "down"
    # The rest remain up.
    assert body["dependencies"]["milvus"]["status"] == "up"


# ---------------------------------------------------------------------------
# /mcp/tools
# ---------------------------------------------------------------------------


def test_mcp_tools_lists_definitions(client: TestClient) -> None:
    """GET /mcp/tools returns the tool list; each item has name/description/parameters."""
    # Use the real TOOL_DEFINITIONS (4 items) to verify the REST route reads them correctly.
    resp = client.get("/mcp/tools")
    assert resp.status_code == 200
    body = resp.json()
    tools = body["tools"]
    assert isinstance(tools, list)
    assert len(tools) >= 1
    for t in tools:
        assert "name" in t
        assert "description" in t
        assert "parameters" in t
    # No error field on success (or null).
    assert body.get("error") is None


def test_mcp_tools_graceful_degradation(client: TestClient) -> None:
    """TOOL_DEFINITIONS validation failure -> empty tools + error field."""
    bad_defs = [{"missing": "required-fields"}]
    with patch("eagle_rag.api.mcp_server.TOOL_DEFINITIONS", bad_defs):
        resp = client.get("/mcp/tools")
    assert resp.status_code == 200
    body = resp.json()
    assert body["tools"] == []
    assert isinstance(body["error"], str) and body["error"]


# ---------------------------------------------------------------------------
# /admin/celery
# ---------------------------------------------------------------------------


def test_admin_celery_success(client: TestClient) -> None:
    """GET /admin/celery returns {workers, active_tasks, queues}."""
    inspect_mock = MagicMock()
    inspect_mock.ping.return_value = {"celery@worker1": {"ok": "pong"}}
    inspect_mock.active.return_value = {"celery@worker1": []}
    with patch("eagle_rag.api.health.celery_app") as mock_app:
        mock_app.control.inspect.return_value = inspect_mock
        resp = client.get("/admin/celery")
    assert resp.status_code == 200
    body = resp.json()
    assert body["workers"] == ["celery@worker1"]
    assert body["active_tasks"] == []
    # queues: a list of {queue, size} when Redis is up, or a single {error} record when unreachable.
    # Both environments should be non-empty and each entry should match CeleryQueueInfo shape.
    queues = body["queues"]
    assert isinstance(queues, list)
    assert len(queues) >= 1
    for q in queues:
        if q.get("error"):
            continue
        assert "queue" in q
        assert isinstance(q["size"], int)


def test_admin_celery_unavailable_returns_503(client: TestClient) -> None:
    """Celery inspect raising -> 503."""
    inspect_mock = MagicMock()
    inspect_mock.ping.side_effect = RuntimeError("no broker")
    with patch("eagle_rag.api.health.celery_app") as mock_app:
        mock_app.control.inspect.return_value = inspect_mock
        resp = client.get("/admin/celery")
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# /admin/milvus
# ---------------------------------------------------------------------------


def test_admin_milvus_lists_collections(client: TestClient) -> None:
    """GET /admin/milvus returns {collections:[{name, num_entities}]}."""
    mock_client = MagicMock()
    mock_client.list_collections.return_value = ["eagle_text", "eagle_visual"]
    mock_client.get_collection_stats.return_value = {"row_count": 42}
    with patch("pymilvus.MilvusClient", return_value=mock_client):
        resp = client.get("/admin/milvus")
    assert resp.status_code == 200
    body = resp.json()
    cols = body["collections"]
    assert {c["name"] for c in cols} == {"eagle_text", "eagle_visual"}
    for c in cols:
        assert c["num_entities"] == 42


# ---------------------------------------------------------------------------
# /admin/pixelrag
# ---------------------------------------------------------------------------


def test_admin_pixelrag_shape(client: TestClient) -> None:
    """GET /admin/pixelrag returns {status, detail, visual_vectors, error}."""
    with (
        patch(
            "eagle_rag.api.health._probe_pixelrag",
            return_value={"status": "up", "detail": "libraries=mock"},
        ),
        patch("eagle_rag.index.milvus_visual_store.count_visual", return_value=7),
    ):
        resp = client.get("/admin/pixelrag")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "up"
    assert body["detail"] == "libraries=mock"
    assert body["visual_vectors"] == 7
    assert body["error"] is None


# ---------------------------------------------------------------------------
# /admin/knowhere
# ---------------------------------------------------------------------------


def test_admin_knowhere_shape(client: TestClient) -> None:
    """GET /admin/knowhere returns {base_url, status, detail}."""
    with patch(
        "eagle_rag.api.health._probe_knowhere",
        return_value={"status": "up", "detail": "base_url=mock, status_code=200"},
    ):
        resp = client.get("/admin/knowhere")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "up"
    assert body["base_url"].startswith("http://")
    assert "status_code=200" in body["detail"]


# ---------------------------------------------------------------------------
# /admin/vlm
# ---------------------------------------------------------------------------


def test_admin_vlm_masks_api_key(client: TestClient) -> None:
    """GET /admin/vlm returns api_key_set boolean; never returns the real api_key."""
    fake_vlm = MagicMock(
        provider="dashscope",
        model="qwen-vl-max",
        api_key="sk-super-secret",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    fake_settings = MagicMock(vlm=fake_vlm)
    with patch("eagle_rag.api.health.get_settings", return_value=fake_settings):
        resp = client.get("/admin/vlm")
    assert resp.status_code == 200
    body = resp.json()
    assert body["provider"] == "dashscope"
    assert body["model"] == "qwen-vl-max"
    assert body["base_url"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert body["api_key_set"] is True
    # The real key must not appear in the response.
    assert "api_key" not in body
    assert "sk-super-secret" not in resp.text


def test_admin_vlm_api_key_not_set(client: TestClient) -> None:
    """Empty api_key -> api_key_set=False."""
    fake_vlm = MagicMock(provider="dashscope", model="qwen-vl-max", api_key="", base_url="http://x")
    fake_settings = MagicMock(vlm=fake_vlm)
    with patch("eagle_rag.api.health.get_settings", return_value=fake_settings):
        resp = client.get("/admin/vlm")
    assert resp.status_code == 200
    assert resp.json()["api_key_set"] is False


# ---------------------------------------------------------------------------
# /admin/mcp
# ---------------------------------------------------------------------------


def test_admin_mcp_registered(client: TestClient) -> None:
    """GET /admin/mcp returns {registered: True, tools[]}."""
    resp = client.get("/admin/mcp")
    assert resp.status_code == 200
    body = resp.json()
    assert body["registered"] is True
    assert isinstance(body["tools"], list)
    assert len(body["tools"]) >= 1


def test_admin_mcp_graceful_degradation(client: TestClient) -> None:
    """TOOL_DEFINITIONS validation failure -> registered=False, tools=[]."""
    bad_defs = [{"missing": "required-fields"}]
    with patch("eagle_rag.api.mcp_server.TOOL_DEFINITIONS", bad_defs):
        resp = client.get("/admin/mcp")
    assert resp.status_code == 200
    body = resp.json()
    assert body["registered"] is False
    assert body["tools"] == []


# ---------------------------------------------------------------------------
# /admin/config
# ---------------------------------------------------------------------------


def test_admin_config_masks_secrets(client: TestClient) -> None:
    """GET /admin/config masks field values containing key/secret/password with '***'."""
    # Take the real settings dict (so the shape passes AdminConfigOut validation) and inject known
    # secrets.
    raw = _real_get_settings().model_dump()
    raw["vlm"]["api_key"] = "super-secret-vlm-key"
    raw["minio"]["secret_key"] = "minio-super-secret"
    raw["minio"]["access_key"] = "minio-access-secret"
    raw["auth"]["api_key"] = "auth-secret-key"
    fake_settings = MagicMock()
    fake_settings.model_dump.return_value = raw

    with patch("eagle_rag.api.health.get_settings", return_value=fake_settings):
        resp = client.get("/admin/config")
    assert resp.status_code == 200
    cfg = resp.json()

    # All fields containing key/secret are masked.
    assert cfg["vlm"]["api_key"] == "***"
    assert cfg["minio"]["secret_key"] == "***"
    assert cfg["minio"]["access_key"] == "***"
    assert cfg["auth"]["api_key"] == "***"
    # Non-sensitive fields keep their original values.
    assert cfg["app"]["name"] == "Eagle-RAG"
    assert cfg["milvus"]["text_collection"] == "eagle_text"
    # Real secrets must not leak into the response.
    assert "super-secret-vlm-key" not in resp.text
    assert "minio-super-secret" not in resp.text


# ---------------------------------------------------------------------------
# /admin/probes
# ---------------------------------------------------------------------------


def test_admin_probes_returns_latency(client: TestClient) -> None:
    """GET /admin/probes returns each probe with latency_ms."""
    with patch("eagle_rag.api.health._probe_all", return_value=_probe_results()):
        resp = client.get("/admin/probes")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    deps = body["dependencies"]
    assert set(deps) == set(_PROBE_NAMES)
    for name in _PROBE_NAMES:
        entry = deps[name]
        assert entry["status"] == "up"
        assert isinstance(entry["latency_ms"], int)
        assert entry["latency_ms"] >= 0


def test_admin_probes_degraded(client: TestClient) -> None:
    """Any probe down -> /admin/probes status=degraded."""
    with patch(
        "eagle_rag.api.health._probe_all",
        return_value=_probe_results(down={"milvus"}),
    ):
        resp = client.get("/admin/probes")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["dependencies"]["milvus"]["status"] == "down"


# ---------------------------------------------------------------------------
# /admin/logs (SSE)
# ---------------------------------------------------------------------------


def test_admin_logs_is_sse_stream(client: TestClient) -> None:
    """GET /admin/logs returns a text/event-stream with log/heartbeat events.

    A terminating generator replaces ``_log_event_generator`` to avoid an
    infinite stream hanging the TestClient.
    """
    sentinel = "heartbeat 1700000000"

    async def _fake_stream() -> Any:
        yield {"event": "heartbeat", "data": sentinel}

    with patch("eagle_rag.api.health._log_event_generator", _fake_stream):
        resp = client.get("/admin/logs")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    # Events are serialized as SSE frames.
    assert "event: heartbeat" in resp.text
    assert sentinel in resp.text


# ---------------------------------------------------------------------------
# Extended fields: worker_details / pending / succeeded / queue_backlog_series
# ---------------------------------------------------------------------------


def test_admin_celery_worker_details(client: TestClient) -> None:
    """GET /admin/celery returns worker_details[]; each entry has name/pid/state/current/memory."""
    inspect_mock = MagicMock()
    inspect_mock.ping.return_value = {"celery@w1": {"ok": "pong"}}
    inspect_mock.active.return_value = {"celery@w1": [{"name": "eagle_rag.tasks.ingest"}]}
    inspect_mock.stats.return_value = {
        "celery@w1": {"pid": 12345, "rusage": {"rss": 1048576}}  # 1MB
    }
    with (
        patch("eagle_rag.api.health.celery_app") as mock_app,
        patch(
            "eagle_rag.api.health.async_fetchrow",
            new=AsyncMock(return_value={"cnt": 42}),
        ),
        patch(
            "eagle_rag.api.health.get_queue_backlog_series",
            new=AsyncMock(
                return_value=[
                    {
                        "sampled_at": "2026-01-01T00:00:00",
                        "knowhere": 1.0,
                        "pixelrag": 2.0,
                        "router": 0.0,
                    }
                ]
            ),
        ),
    ):
        mock_app.control.inspect.return_value = inspect_mock
        resp = client.get("/admin/celery")
    assert resp.status_code == 200
    body = resp.json()
    # worker_details
    details = body["worker_details"]
    assert isinstance(details, list)
    assert len(details) == 1
    d = details[0]
    assert d["name"] == "celery@w1"
    assert d["pid"] == 12345
    assert d["state"] == "active"  # has an active task
    assert d["current"] == "eagle_rag.tasks.ingest"
    assert d["memory"] == 1.0  # 1048576 bytes -> 1.0 MB
    # pending (0 when redis unreachable; always int or None).
    assert body["pending"] is None or isinstance(body["pending"], int)
    # succeeded (success count from task_audit over the last 24h).
    assert body["succeeded"] == 42
    # queue_backlog_series
    series = body["queue_backlog_series"]
    assert isinstance(series, list)
    assert len(series) == 1
    point = series[0]
    assert point["sampled_at"] == "2026-01-01T00:00:00"
    assert point["knowhere"] == 1.0
    assert point["pixelrag"] == 2.0
    assert point["router"] == 0.0


def test_admin_celery_db_unavailable(client: TestClient) -> None:
    """task_audit query failure -> succeeded=None, queue_backlog_series=[]; no error raised."""
    inspect_mock = MagicMock()
    inspect_mock.ping.return_value = {"celery@w1": {"ok": "pong"}}
    inspect_mock.active.return_value = {}
    inspect_mock.stats.return_value = {}
    with (
        patch("eagle_rag.api.health.celery_app") as mock_app,
        patch(
            "eagle_rag.api.health.async_fetchrow",
            new=AsyncMock(side_effect=Exception("db down")),
        ),
        patch(
            "eagle_rag.api.health.get_queue_backlog_series",
            new=AsyncMock(side_effect=Exception("db down")),
        ),
    ):
        mock_app.control.inspect.return_value = inspect_mock
        resp = client.get("/admin/celery")
    assert resp.status_code == 200
    body = resp.json()
    assert body["succeeded"] is None
    assert body["queue_backlog_series"] == []


# ---------------------------------------------------------------------------
# Extended fields: collection_details (dim/metric_type/index_type/fields)
# ---------------------------------------------------------------------------


def test_admin_milvus_collection_details(client: TestClient) -> None:
    """GET /admin/milvus returns collection_details[] with dim/metric_type/index_type/fields."""
    mock_client = MagicMock()
    mock_client.list_collections.return_value = ["eagle_text"]
    mock_client.get_collection_stats.return_value = {"row_count": 42}
    mock_client.describe_collection.return_value = {
        "fields": [
            {"name": "id", "type": 5, "is_primary": True},  # DataType.INT64=5
            {
                "name": "vector",
                "type": 101,  # DataType.FLOAT_VECTOR=101
                "is_primary": False,
                "params": {"dim": 1024},
            },
        ]
    }
    mock_client.describe_index.return_value = [{"index_type": "IVF_FLAT", "metric_type": "L2"}]
    with patch("pymilvus.MilvusClient", return_value=mock_client):
        resp = client.get("/admin/milvus")
    assert resp.status_code == 200
    body = resp.json()
    details = body["collection_details"]
    assert isinstance(details, list)
    assert len(details) == 1
    d = details[0]
    assert d["name"] == "eagle_text"
    assert d["dim"] == 1024
    assert d["index_type"] == "IVF_FLAT"
    assert d["metric_type"] == "L2"
    assert d["num_entities"] == 42
    fields = d["fields"]
    assert len(fields) == 2
    assert fields[0]["name"] == "id"
    assert fields[0]["dtype"] == "INT64"
    assert fields[0]["is_primary"] is True
    assert fields[1]["name"] == "vector"
    assert fields[1]["dtype"] == "FLOAT_VECTOR"
    assert fields[1]["is_primary"] is False


# ---------------------------------------------------------------------------
# Extended fields: parsed / chunks / partitions
# ---------------------------------------------------------------------------


def test_admin_knowhere_partitions(client: TestClient) -> None:
    """GET /admin/knowhere returns parsed/chunks/partitions."""
    fake_kb_rows = [
        {"kb_name": "default", "doc_count": 3},
        {"kb_name": "finance", "doc_count": 5},
    ]

    async def _fake_fetch(sql: str, *args: Any) -> list[dict[str, Any]]:
        if "GROUP BY kb_name" in sql:
            return fake_kb_rows
        return []

    with (
        patch(
            "eagle_rag.api.health._probe_knowhere",
            return_value={"status": "up", "detail": "ok"},
        ),
        patch(
            "eagle_rag.api.health.async_fetch",
            new=AsyncMock(side_effect=_fake_fetch),
        ),
        patch(
            "eagle_rag.api.health.async_fetchrow",
            new=AsyncMock(return_value={"cnt": 8}),
        ),
        patch(
            "eagle_rag.index.milvus_text_store.count_text",
            return_value=100,
        ),
    ):
        resp = client.get("/admin/knowhere")
    assert resp.status_code == 200
    body = resp.json()
    assert body["parsed"] == 8
    assert body["chunks"] == 100
    partitions = body["partitions"]
    assert isinstance(partitions, list)
    assert len(partitions) == 2
    kb_names = {p["kb_name"] for p in partitions}
    assert kb_names == {"default", "finance"}
    for p in partitions:
        assert p["document_count"] in (3, 5)
        assert p["chunk_count"] == 100


# ---------------------------------------------------------------------------
# Extended fields: latency / tokens / error_rate / model_router
# ---------------------------------------------------------------------------


def test_admin_vlm_model_router_and_metrics(client: TestClient) -> None:
    """GET /admin/vlm returns latency/tokens/error_rate/model_router."""
    fake_vlm = MagicMock(
        provider="dashscope", model="qwen-vl-max", api_key="sk-x", base_url="http://x"
    )
    fake_settings = MagicMock(vlm=fake_vlm)
    with (
        patch("eagle_rag.api.health.get_settings", return_value=fake_settings),
        patch(
            "eagle_rag.api.health.get_metric_aggregate",
            new=AsyncMock(side_effect=[120.5, 1500.0, 0.05]),
        ),
        patch(
            "eagle_rag.api.health.get_setting",
            new=AsyncMock(return_value={"vlm": False, "text_llm": True, "embedding": True}),
        ),
    ):
        resp = client.get("/admin/vlm")
    assert resp.status_code == 200
    body = resp.json()
    assert body["latency"] == 120.5
    assert body["tokens"] == 1500
    assert body["error_rate"] == 0.05
    routers = body["model_router"]
    assert isinstance(routers, list)
    assert len(routers) == 3
    vlm_router = [m for m in routers if m["key"] == "vlm"][0]
    assert vlm_router["enabled"] is False  # overridden by system_setting
    text_router = [m for m in routers if m["key"] == "text_llm"][0]
    assert text_router["enabled"] is True


def test_admin_vlm_model_router_defaults(client: TestClient) -> None:
    """No system_setting override and no metrics -> model_router all enabled=True; metrics None."""
    fake_vlm = MagicMock(provider="x", model="y", api_key="", base_url="z")
    fake_settings = MagicMock(vlm=fake_vlm)
    with (
        patch("eagle_rag.api.health.get_settings", return_value=fake_settings),
        patch(
            "eagle_rag.api.health.get_metric_aggregate",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "eagle_rag.api.health.get_setting",
            new=AsyncMock(return_value=None),
        ),
    ):
        resp = client.get("/admin/vlm")
    assert resp.status_code == 200
    body = resp.json()
    assert body["latency"] is None
    assert body["tokens"] is None
    assert body["error_rate"] is None
    for m in body["model_router"]:
        assert m["enabled"] is True


def test_admin_update_model_router(client: TestClient) -> None:
    """PATCH /admin/model-router writes and returns the updated model_router, preserving prior
    settings."""
    captured: dict[str, Any] = {}

    async def _fake_set(key: str, value: Any) -> None:
        captured["key"] = key
        captured["value"] = value

    async def _fake_get(key: str) -> Any:
        if captured.get("key") == key:
            return captured.get("value")
        return None

    with (
        patch(
            "eagle_rag.api.health.get_setting",
            new=AsyncMock(side_effect=_fake_get),
        ),
        patch(
            "eagle_rag.api.health.set_setting",
            new=AsyncMock(side_effect=_fake_set),
        ),
    ):
        # First PATCH: disable vlm.
        resp = client.patch("/admin/model-router", json={"vlm": False})
        assert resp.status_code == 200
        body = resp.json()
        vlm = [m for m in body if m["key"] == "vlm"][0]
        assert vlm["enabled"] is False
        assert captured["key"] == "model_router"
        assert captured["value"]["vlm"] is False

        # Second PATCH: disable embedding (should preserve vlm=False).
        resp = client.patch("/admin/model-router", json={"embedding": False})
        assert resp.status_code == 200
        body = resp.json()
        emb = [m for m in body if m["key"] == "embedding"][0]
        assert emb["enabled"] is False
        vlm = [m for m in body if m["key"] == "vlm"][0]
        assert vlm["enabled"] is False  # preserved from the previous setting


# ---------------------------------------------------------------------------
# Extended fields: resource_limits / probe_config
# ---------------------------------------------------------------------------


def test_admin_probes_resource_limits(client: TestClient) -> None:
    """GET /admin/probes returns resource_limits (cpu/memory) and probe_config."""
    fake_psutil = MagicMock()
    fake_psutil.cpu_percent.return_value = 45.5
    fake_psutil.cpu_count.return_value = 8
    fake_psutil.virtual_memory.return_value = MagicMock(
        percent=62.3,
        used=8 * 1024 * 1024 * 1024,
        total=16 * 1024 * 1024 * 1024,
    )
    with (
        patch("eagle_rag.api.health._probe_all", return_value=_probe_results()),
        patch.dict("sys.modules", {"psutil": fake_psutil}),
    ):
        resp = client.get("/admin/probes")
    assert resp.status_code == 200
    body = resp.json()
    rl = body["resource_limits"]
    assert rl is not None
    assert rl["cpu"] is not None
    assert rl["cpu"]["percent"] == 45.5
    assert rl["cpu"]["limit"] == 8.0
    assert rl["memory"] is not None
    assert rl["memory"]["percent"] == 62.3
    pc = body["probe_config"]
    assert pc is not None
    assert pc["liveness"] == "30s"
    assert pc["readiness"] == "10s"


def test_admin_probes_psutil_unavailable(client: TestClient) -> None:
    """psutil unavailable -> resource_limits=None; probe_config still returned."""
    with (
        patch("eagle_rag.api.health._probe_all", return_value=_probe_results()),
        patch.dict("sys.modules", {"psutil": None}),
    ):
        resp = client.get("/admin/probes")
    assert resp.status_code == 200
    body = resp.json()
    assert body["resource_limits"] is None
    assert body["probe_config"] is not None  # probe_config does not depend on psutil
    assert body["probe_config"]["liveness"] == "30s"


# ---------------------------------------------------------------------------
# Extended fields: sse_connections / console_logs
# ---------------------------------------------------------------------------


def test_admin_mcp_console_logs(client: TestClient) -> None:
    """GET /admin/mcp returns sse_connections and console_logs."""
    fake_calls = [
        {
            "tool_name": "ingest",
            "arguments": {"source_uri": "x.pdf"},
            "result_summary": "status=success",
            "caller": "mcp",
            "latency_ms": 150,
            "called_at": "2026-01-01T00:00:00",
        },
    ]
    with patch(
        "eagle_rag.api.health.list_recent_mcp_calls",
        new=AsyncMock(return_value=fake_calls),
    ):
        resp = client.get("/admin/mcp")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["sse_connections"], int)
    logs = body["console_logs"]
    assert isinstance(logs, list)
    assert len(logs) == 1
    log = logs[0]
    assert log["time"] == "2026-01-01T00:00:00"
    assert log["level"] == "INFO"
    assert "ingest" in log["message"]
    assert "status=success" in log["message"]
    assert "150ms" in log["message"]


# ---------------------------------------------------------------------------
# /admin/minio
# ---------------------------------------------------------------------------


def test_admin_minio_returns_buckets(client: TestClient) -> None:
    """GET /admin/minio with probe up: returns endpoint, bucket, bucket list (default count)."""
    from datetime import datetime

    fake_default_bucket = MagicMock()
    fake_default_bucket.name = "eagle-rag"
    fake_default_bucket.creation_date = datetime(2026, 1, 1, 0, 0, 0)
    fake_other_bucket = MagicMock()
    fake_other_bucket.name = "archive"
    fake_other_bucket.creation_date = datetime(2025, 12, 1, 0, 0, 0)

    mock_minio_client = MagicMock()
    mock_minio_client.list_buckets.return_value = [fake_default_bucket, fake_other_bucket]
    # Default bucket object count: 3 objects.
    mock_minio_client.list_objects.return_value = ["obj1", "obj2", "obj3"]

    with (
        patch(
            "eagle_rag.api.health._probe_minio",
            return_value={"status": "up", "detail": "endpoint=mock, buckets=2"},
        ),
        patch(
            "eagle_rag.storage.minio_client.get_minio_client",
            return_value=mock_minio_client,
        ),
    ):
        resp = client.get("/admin/minio")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "up"
    assert isinstance(body["endpoint"], str) and body["endpoint"]
    assert isinstance(body["bucket"], str) and body["bucket"]
    assert body["secure"] is False
    assert body["error"] is None
    buckets = body["buckets"]
    assert isinstance(buckets, list)
    assert len(buckets) == 2
    # The default bucket carries object_count and is_default=True.
    default_entry = next(b for b in buckets if b["name"] == "eagle-rag")
    assert default_entry["is_default"] is True
    assert default_entry["object_count"] == 3
    assert default_entry["creation_date"] == "2026-01-01T00:00:00"
    # Non-default bucket: is_default=False, object_count=None.
    other_entry = next(b for b in buckets if b["name"] == "archive")
    assert other_entry["is_default"] is False
    assert other_entry["object_count"] is None


def test_admin_minio_down_returns_error(client: TestClient) -> None:
    """Probe down -> status=down, buckets empty, error carries the reason."""
    with patch(
        "eagle_rag.api.health._probe_minio",
        return_value={"status": "down", "detail": "connection refused"},
    ):
        resp = client.get("/admin/minio")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "down"
    assert body["buckets"] == []
    assert body["error"] == "connection refused"


# ---------------------------------------------------------------------------
# /admin/redis
# ---------------------------------------------------------------------------


def test_admin_redis_returns_info(client: TestClient) -> None:
    """GET /admin/redis with probe up returns broker_url / db_size / key info fields."""
    fake_redis_client = MagicMock()
    fake_redis_client.info.return_value = {
        "redis_version": "7.2.4",
        "uptime_in_days": 14,
        "connected_clients": 5,
        "used_memory_human": "2.5M",
        "used_memory_peak_human": "3.1M",
        "role": "master",
        "maxmemory_human": "0",
    }
    fake_redis_client.dbsize.return_value = 128

    with (
        patch(
            "eagle_rag.api.health._probe_redis",
            return_value={"status": "up", "detail": "broker=mock"},
        ),
        patch(
            "redis.Redis.from_url",
            return_value=fake_redis_client,
        ),
    ):
        resp = client.get("/admin/redis")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "up"
    assert body["db_size"] == 128
    assert body["error"] is None
    info = body["info"]
    assert info["version"] == "7.2.4"
    assert info["uptime_days"] == 14
    assert info["connected_clients"] == 5
    assert info["used_memory_human"] == "2.5M"
    assert info["role"] == "master"


def test_admin_redis_down_returns_error(client: TestClient) -> None:
    """Probe down -> status=down, info=None, error carries the reason."""
    with patch(
        "eagle_rag.api.health._probe_redis",
        return_value={"status": "down", "detail": "connection refused"},
    ):
        resp = client.get("/admin/redis")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "down"
    assert body["info"] is None
    assert body["error"] == "connection refused"


def test_admin_redis_masks_password_in_url(client: TestClient) -> None:
    """Password in broker_url should be masked as ***."""
    fake_settings = MagicMock()
    fake_settings.celery.broker_url = "redis://:s3cret@redis-host:6379/0"
    fake_redis_client = MagicMock()
    fake_redis_client.info.return_value = {}
    fake_redis_client.dbsize.return_value = 0

    with (
        patch("eagle_rag.api.health.get_settings", return_value=fake_settings),
        patch(
            "eagle_rag.api.health._probe_redis",
            return_value={"status": "up", "detail": "broker=mock"},
        ),
        patch(
            "redis.Redis.from_url",
            return_value=fake_redis_client,
        ),
    ):
        resp = client.get("/admin/redis")
    assert resp.status_code == 200
    body = resp.json()
    # The password must not appear in the response.
    assert "s3cret" not in resp.text
    assert "***" in body["broker_url"]
