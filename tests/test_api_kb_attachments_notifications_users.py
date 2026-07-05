"""Knowledge base, attachment, notification, and user API contract tests.

Drives ``eagle_rag.api.app.app`` directly with FastAPI TestClient and mocks out the
service / store layer (DB / MinIO / Milvus all isolated); only HTTP contracts are
verified: request validation, response shape, and status codes. Patch targets follow
the rule "patch where the route module references the symbol":
- KB routes use ``from eagle_rag.kb import lifecycle, registry, stats`` and call them
  as module attributes -> patch the source modules ``eagle_rag.kb.registry.*`` /
  ``eagle_rag.kb.stats.*`` / ``eagle_rag.kb.lifecycle.*``.
- Attachment routes use ``from eagle_rag.attachments.store import ...`` and bind
  symbols into the route namespace -> patch ``eagle_rag.api.attachments.*``.
- Notification routes use ``from eagle_rag... import store as ...`` and call them as
  module attributes -> patch ``eagle_rag.notifications.store.*``.
- User routes (/users/me*) are static stubs with no store dependency; assert the
  static default response directly.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from eagle_rag.api.app import app


@pytest.fixture
def client() -> TestClient:
    """Bare TestClient (no lifespan, no external connections)."""
    return TestClient(app)


# ---------------------------------------------------------------------------
# Shared data
# ---------------------------------------------------------------------------

KB_META = {
    "kb_name": "tax_law",
    "display_name": "税法知识库",
    "description": "个税法规",
    "theme": "blue",
    "icon": "database",
    "updated_at": "2024-01-01T00:00:00",
}

KB_STATS = {
    "documents": 12,
    "graph_nodes": 120,
    "visual_slices": 8,
    "active_ingestions": 1,
    "collections": ["eagle_text", "eagle_visual"],
}


# ===========================================================================
# Knowledge base API (/knowledge_bases*)
# ===========================================================================


def test_list_knowledge_bases(client: TestClient):
    """GET /knowledge_bases returns items + total; each carries stats fields and collections."""
    rows = [KB_META, {**KB_META, "kb_name": "finance", "display_name": "财务"}]
    with (
        patch(
            "eagle_rag.kb.registry.list_kbs", new_callable=AsyncMock, return_value=(rows, 2)
        ) as m_list,
        patch("eagle_rag.kb.stats.get_kb_stats", new_callable=AsyncMock, return_value=KB_STATS),
    ):
        resp = client.get(
            "/knowledge_bases",
            params={"query": "税", "sort": "name", "limit": 50, "offset": 0},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2
    item = body["items"][0]
    for key in (
        "kb_name",
        "display_name",
        "theme",
        "icon",
        "documents",
        "graph_nodes",
        "visual_slices",
        "active_ingestions",
        "updated_at",
        "collections",
    ):
        assert key in item
    assert item["kb_name"] == "tax_law"
    assert item["collections"] == ["eagle_text", "eagle_visual"]
    m_list.assert_awaited_once()
    assert m_list.call_args.kwargs.get("query") == "税"
    assert m_list.call_args.kwargs.get("sort") == "name"


def test_list_knowledge_bases_invalid_limit(client: TestClient):
    """limit < 1 -> 422."""
    resp = client.get("/knowledge_bases", params={"limit": 0})
    assert resp.status_code == 422


def test_create_knowledge_base(client: TestClient):
    """POST /knowledge_bases succeeds and returns 201 with the created KB."""
    with (
        patch("eagle_rag.kb.registry.kb_exists", new_callable=AsyncMock, return_value=False),
        patch(
            "eagle_rag.kb.registry.create_kb", new_callable=AsyncMock, return_value=KB_META
        ) as m_create,
        patch("eagle_rag.kb.stats.get_kb_stats", new_callable=AsyncMock, return_value=KB_STATS),
    ):
        resp = client.post(
            "/knowledge_bases",
            json={
                "kb_name": "tax_law",
                "display_name": "税法知识库",
                "theme": "blue",
                "icon": "database",
            },
        )
    assert resp.status_code == 201
    body = resp.json()
    assert body["kb_name"] == "tax_law"
    assert body["display_name"] == "税法知识库"
    m_create.assert_awaited_once()


def test_create_knowledge_base_invalid_name(client: TestClient):
    """kb_name containing uppercase/hyphen -> 422."""
    resp = client.post("/knowledge_bases", json={"kb_name": "Tax-Law", "display_name": "x"})
    assert resp.status_code == 422


def test_create_knowledge_base_missing_display_name(client: TestClient):
    """display_name is required -> 422."""
    resp = client.post("/knowledge_bases", json={"kb_name": "tax_law"})
    assert resp.status_code == 422


def test_create_knowledge_base_duplicate(client: TestClient):
    """kb_name already exists -> 409."""
    with patch("eagle_rag.kb.registry.kb_exists", new_callable=AsyncMock, return_value=True):
        resp = client.post("/knowledge_bases", json={"kb_name": "tax_law", "display_name": "税法"})
    assert resp.status_code == 409


def test_knowledge_bases_overview(client: TestClient):
    """GET /knowledge_bases/overview returns cross-KB summary metrics."""
    overview = {
        "kb_count": 3,
        "active_ingestions": 1,
        "total_documents": 100,
        "total_graph_nodes": 500,
        "total_vectors": 2000,
    }
    with patch("eagle_rag.kb.stats.get_overview", new_callable=AsyncMock, return_value=overview):
        resp = client.get("/knowledge_bases/overview")
    assert resp.status_code == 200
    assert resp.json() == overview


def test_get_knowledge_base(client: TestClient):
    """GET /knowledge_bases/{kb_name} returns details and kpi."""
    with (
        patch("eagle_rag.kb.registry.get_kb", new_callable=AsyncMock, return_value=KB_META),
        patch("eagle_rag.kb.stats.get_kb_stats", new_callable=AsyncMock, return_value=KB_STATS),
        patch("eagle_rag.kb.stats.count_queries_7d", new_callable=AsyncMock, return_value=42),
        patch(
            "eagle_rag.kb.health.compute_kb_status", new_callable=AsyncMock, return_value="online"
        ),
    ):
        resp = client.get("/knowledge_bases/tax_law")
    assert resp.status_code == 200
    body = resp.json()
    assert body["kb_name"] == "tax_law"
    assert body["status"] == "online"
    assert body["kpi"]["documents"] == 12
    assert body["kpi"]["graph_nodes"] == 120
    assert body["kpi"]["visual_slices"] == 8
    assert body["kpi"]["queries_7d"] == 42


def test_get_knowledge_base_not_found(client: TestClient):
    """KB does not exist -> 404."""
    with patch("eagle_rag.kb.registry.get_kb", new_callable=AsyncMock, return_value=None):
        resp = client.get("/knowledge_bases/missing")
    assert resp.status_code == 404


def test_patch_knowledge_base(client: TestClient):
    """PATCH updates display_name / theme / pdf_text_page_ratio."""
    updated = {**KB_META, "display_name": "新名称", "theme": "violet"}
    with (
        patch("eagle_rag.kb.registry.kb_exists", new_callable=AsyncMock, return_value=True),
        patch(
            "eagle_rag.kb.registry.update_kb", new_callable=AsyncMock, return_value=updated
        ) as m_upd,
        patch("eagle_rag.kb.stats.get_kb_stats", new_callable=AsyncMock, return_value=KB_STATS),
    ):
        resp = client.patch(
            "/knowledge_bases/tax_law",
            json={"display_name": "新名称", "theme": "violet", "pdf_text_page_ratio": 0.5},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["display_name"] == "新名称"
    assert body["theme"] == "violet"
    m_upd.assert_awaited_once()
    assert m_upd.call_args.kwargs.get("pdf_text_page_ratio") == 0.5


def test_patch_knowledge_base_not_found(client: TestClient):
    """PATCH on a non-existent KB -> 404."""
    with patch("eagle_rag.kb.registry.kb_exists", new_callable=AsyncMock, return_value=False):
        resp = client.patch("/knowledge_bases/missing", json={"display_name": "x"})
    assert resp.status_code == 404


def test_patch_knowledge_base_invalid_ratio(client: TestClient):
    """pdf_text_page_ratio outside [0,1] -> 422."""
    with patch("eagle_rag.kb.registry.kb_exists", new_callable=AsyncMock, return_value=True):
        resp = client.patch("/knowledge_bases/tax_law", json={"pdf_text_page_ratio": 2.0})
    assert resp.status_code == 422


def test_delete_knowledge_base(client: TestClient):
    """DELETE returns cascade-delete counts."""
    counts = {
        "milvus_text": 5,
        "milvus_visual": 3,
        "documents": 2,
        "images": 1,
        "dedup": 2,
        "task_audit": 1,
    }
    with (
        patch("eagle_rag.kb.registry.kb_exists", new_callable=AsyncMock, return_value=True),
        patch("eagle_rag.kb.lifecycle.delete_kb_namespace", return_value=counts) as m_del,
    ):
        resp = client.delete("/knowledge_bases/tax_law")
    assert resp.status_code == 200
    body = resp.json()
    assert body["kb_name"] == "tax_law"
    assert body["deleted"] == counts
    assert body["ok"] is True
    m_del.assert_called_once_with("tax_law")


def test_delete_knowledge_base_not_found(client: TestClient):
    with patch("eagle_rag.kb.registry.kb_exists", new_callable=AsyncMock, return_value=False):
        resp = client.delete("/knowledge_bases/missing")
    assert resp.status_code == 404


def test_kb_format_distribution(client: TestClient):
    """GET /format-distribution returns segments."""
    data = {
        "segments": [
            {
                "key": "pdf_text",
                "label": "PDF (text)",
                "value": 80,
                "color": "#3B82F6",
            },
            {
                "key": "pdf_scan",
                "label": "PDF (scanned)",
                "value": 20,
                "color": "#A855F7",
            },
        ]
    }
    with (
        patch("eagle_rag.kb.registry.kb_exists", new_callable=AsyncMock, return_value=True),
        patch(
            "eagle_rag.kb.stats.get_format_distribution", new_callable=AsyncMock, return_value=data
        ),
    ):
        resp = client.get("/knowledge_bases/tax_law/format-distribution")
    assert resp.status_code == 200
    body = resp.json()
    assert "segments" in body
    assert body["segments"][0]["key"] == "pdf_text"
    assert body["segments"][0]["value"] == 80


def test_kb_format_distribution_not_found(client: TestClient):
    with patch("eagle_rag.kb.registry.kb_exists", new_callable=AsyncMock, return_value=False):
        resp = client.get("/knowledge_bases/missing/format-distribution")
    assert resp.status_code == 404


def test_kb_ingestion_volume(client: TestClient):
    """GET /ingestion-volume?days=7 returns unit/peak/points."""
    data = {
        "unit": "docs",
        "peak": 5,
        "points": [
            {"date": "2024-01-01", "label": "周一", "value": 3},
            {"date": "2024-01-02", "label": "周二", "value": 5},
        ],
    }
    with (
        patch("eagle_rag.kb.registry.kb_exists", new_callable=AsyncMock, return_value=True),
        patch(
            "eagle_rag.kb.stats.get_ingestion_volume", new_callable=AsyncMock, return_value=data
        ) as m_vol,
    ):
        resp = client.get("/knowledge_bases/tax_law/ingestion-volume", params={"days": 7})
    assert resp.status_code == 200
    body = resp.json()
    assert body["unit"] == "docs"
    assert body["peak"] == 5
    assert len(body["points"]) == 2
    assert body["points"][0]["date"] == "2024-01-01"
    m_vol.assert_awaited_once()
    assert m_vol.call_args.kwargs.get("days") == 7


def test_kb_collections(client: TestClient):
    """GET /collections returns the watermarks of the two Milvus collections."""
    data = {
        "collections": [
            {
                "name": "eagle_text",
                "model": "Qwen text-embedding-v4",
                "dim": 1024,
                "index": "hnsw",
                "entities": 100,
                "capacity_ratio": 0.2,
            },
            {
                "name": "eagle_visual",
                "model": "Qwen3-VL-Embedding-2B",
                "dim": 512,
                "index": "ivf",
                "entities": 50,
                "capacity_ratio": 0.1,
            },
        ]
    }
    with (
        patch("eagle_rag.kb.registry.kb_exists", new_callable=AsyncMock, return_value=True),
        patch("eagle_rag.kb.stats.get_collections", new_callable=AsyncMock, return_value=data),
    ):
        resp = client.get("/knowledge_bases/tax_law/collections")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["collections"]) == 2
    assert body["collections"][0]["name"] == "eagle_text"
    assert body["collections"][0]["entities"] == 100
    assert body["collections"][0]["capacity_ratio"] == 0.2


def test_kb_facets(client: TestClient):
    """GET /facets returns source_type / pipeline / year dimensions."""
    data = {
        "source_type": ["policy", "financial"],
        "pipeline": ["knowhere", "pixelrag"],
        "year": [2023, 2024],
    }
    with (
        patch("eagle_rag.kb.registry.kb_exists", new_callable=AsyncMock, return_value=True),
        patch("eagle_rag.kb.stats.get_facets", new_callable=AsyncMock, return_value=data),
    ):
        resp = client.get("/knowledge_bases/tax_law/facets")
    assert resp.status_code == 200
    body = resp.json()
    assert body["source_type"] == ["policy", "financial"]
    assert body["pipeline"] == ["knowhere", "pixelrag"]
    assert body["year"] == [2023, 2024]


def test_rebuild_knowledge_base(client: TestClient):
    """POST /rebuild returns job_id."""
    with (
        patch("eagle_rag.kb.registry.kb_exists", new_callable=AsyncMock, return_value=True),
        patch("eagle_rag.kb.lifecycle.start_rebuild", return_value="job-123") as m_rebuild,
    ):
        resp = client.post("/knowledge_bases/tax_law/rebuild")
    assert resp.status_code == 200
    assert resp.json()["job_id"] == "job-123"
    m_rebuild.assert_called_once_with("tax_law")


def test_rebuild_knowledge_base_not_found(client: TestClient):
    with patch("eagle_rag.kb.registry.kb_exists", new_callable=AsyncMock, return_value=False):
        resp = client.post("/knowledge_bases/missing/rebuild")
    assert resp.status_code == 404


def test_kb_crud_flow(client: TestClient):
    """Full create -> list -> detail -> patch -> delete flow."""
    updated_meta = {**KB_META, "display_name": "已更新", "theme": "violet"}
    # kb_exists call order: create(False) -> patch(True) -> delete(True);
    # list / detail do not go through kb_exists.
    with (
        patch(
            "eagle_rag.kb.registry.kb_exists",
            new_callable=AsyncMock,
            side_effect=[False, True, True],
        ),
        patch("eagle_rag.kb.registry.create_kb", new_callable=AsyncMock, return_value=KB_META),
        patch(
            "eagle_rag.kb.registry.list_kbs", new_callable=AsyncMock, return_value=([KB_META], 1)
        ),
        patch("eagle_rag.kb.registry.get_kb", new_callable=AsyncMock, return_value=KB_META),
        patch("eagle_rag.kb.registry.update_kb", new_callable=AsyncMock, return_value=updated_meta),
        patch("eagle_rag.kb.stats.get_kb_stats", new_callable=AsyncMock, return_value=KB_STATS),
        patch("eagle_rag.kb.stats.count_queries_7d", new_callable=AsyncMock, return_value=7),
        patch(
            "eagle_rag.kb.health.compute_kb_status", new_callable=AsyncMock, return_value="online"
        ),
        patch("eagle_rag.kb.lifecycle.delete_kb_namespace", return_value={"documents": 1}),
    ):
        r1 = client.post(
            "/knowledge_bases", json={"kb_name": "tax_law", "display_name": "税法知识库"}
        )
        assert r1.status_code == 201

        r2 = client.get("/knowledge_bases")
        assert r2.status_code == 200
        assert r2.json()["total"] == 1

        r3 = client.get("/knowledge_bases/tax_law")
        assert r3.status_code == 200
        assert r3.json()["kpi"]["queries_7d"] == 7

        r4 = client.patch("/knowledge_bases/tax_law", json={"display_name": "已更新"})
        assert r4.status_code == 200
        assert r4.json()["display_name"] == "已更新"

        r5 = client.delete("/knowledge_bases/tax_law")
        assert r5.status_code == 200
        assert r5.json()["kb_name"] == "tax_law"


def test_kb_detail_returns_pdf_text_page_ratio(client: TestClient):
    """GET /knowledge_bases/{kb_name} response includes the pdf_text_page_ratio field."""
    meta = {**KB_META, "pdf_text_page_ratio": 0.5}
    with (
        patch("eagle_rag.kb.registry.get_kb", new_callable=AsyncMock, return_value=meta),
        patch("eagle_rag.kb.stats.get_kb_stats", new_callable=AsyncMock, return_value=KB_STATS),
        patch("eagle_rag.kb.stats.count_queries_7d", new_callable=AsyncMock, return_value=0),
        patch(
            "eagle_rag.kb.health.compute_kb_status", new_callable=AsyncMock, return_value="online"
        ),
    ):
        resp = client.get(f"/knowledge_bases/{KB_META['kb_name']}")
    assert resp.status_code == 200
    body = resp.json()
    assert "pdf_text_page_ratio" in body
    assert body["pdf_text_page_ratio"] == 0.5


def test_kb_patch_pdf_text_page_ratio_roundtrip(client: TestClient):
    """PATCH pdf_text_page_ratio then GET reads back the same value."""
    updated_meta = {**KB_META, "pdf_text_page_ratio": 0.6}
    with (
        patch("eagle_rag.kb.registry.kb_exists", new_callable=AsyncMock, return_value=True),
        patch(
            "eagle_rag.kb.registry.update_kb", new_callable=AsyncMock, return_value=updated_meta
        ) as m_update,
        patch("eagle_rag.kb.stats.get_kb_stats", new_callable=AsyncMock, return_value=KB_STATS),
    ):
        resp = client.patch(
            f"/knowledge_bases/{KB_META['kb_name']}",
            json={"pdf_text_page_ratio": 0.6},
        )
    assert resp.status_code == 200
    assert resp.json()["pdf_text_page_ratio"] == 0.6
    # Verify update_kb received the correct ratio.
    m_update.assert_awaited_once()
    call_kwargs = m_update.await_args.kwargs
    assert call_kwargs.get("pdf_text_page_ratio") == 0.6


def test_kb_status_is_valid_value(client: TestClient):
    """status is one of online/degraded/offline (not hardcoded)."""
    for expected_status in ("online", "degraded", "offline"):
        with (
            patch("eagle_rag.kb.registry.get_kb", new_callable=AsyncMock, return_value=KB_META),
            patch("eagle_rag.kb.stats.get_kb_stats", new_callable=AsyncMock, return_value=KB_STATS),
            patch("eagle_rag.kb.stats.count_queries_7d", new_callable=AsyncMock, return_value=0),
            patch(
                "eagle_rag.kb.health.compute_kb_status",
                new_callable=AsyncMock,
                return_value=expected_status,
            ),
        ):
            resp = client.get(f"/knowledge_bases/{KB_META['kb_name']}")
        assert resp.status_code == 200
        assert resp.json()["status"] == expected_status


def test_kb_collections_returns_model(client: TestClient):
    """GET /knowledge_bases/{kb_name}/collections returns the model field."""
    collections_data = {
        "collections": [
            {
                "name": "eagle_text",
                "model": "Qwen text-embedding-v4",
                "dim": 1536,
                "index": "hnsw",
                "entities": 100,
                "capacity_ratio": 0.1,
            },
            {
                "name": "eagle_visual",
                "model": "Qwen3-VL-Embedding-2B",
                "dim": 2048,
                "index": "hnsw",
                "entities": 50,
                "capacity_ratio": 0.05,
            },
        ]
    }
    with (
        patch("eagle_rag.kb.registry.kb_exists", new_callable=AsyncMock, return_value=True),
        patch(
            "eagle_rag.kb.stats.get_collections",
            new_callable=AsyncMock,
            return_value=collections_data,
        ),
    ):
        resp = client.get(f"/knowledge_bases/{KB_META['kb_name']}/collections")
    assert resp.status_code == 200
    body = resp.json()
    assert "collections" in body
    for coll in body["collections"]:
        assert "model" in coll
        assert isinstance(coll["model"], str)
        assert len(coll["model"]) > 0
    text_coll = next(c for c in body["collections"] if c["name"] == "eagle_text")
    assert text_coll["model"] == "Qwen text-embedding-v4"
    visual_coll = next(c for c in body["collections"] if c["name"] == "eagle_visual")
    assert visual_coll["model"] == "Qwen3-VL-Embedding-2B"


# ===========================================================================
# Attachments API (/attachments*)
# ===========================================================================


def test_upload_attachment(client: TestClient):
    """POST /attachments upload succeeds and returns attachment_id."""
    store_result = {
        "attachment_id": "att-1",
        "file_name": "test.png",
        "mime": "image/png",
        "size_bytes": 5,
        "expires_at": "2024-01-01T00:00:00",
    }
    with patch(
        "eagle_rag.api.attachments.store_attachment_sync",
        return_value=store_result,
    ) as m_store:
        resp = client.post(
            "/attachments",
            files={"file": ("test.png", b"\x89PNG", "image/png")},
            data={"session_id": "sess-1"},
        )
    assert resp.status_code == 201
    body = resp.json()
    assert body["attachment_id"] == "att-1"
    assert body["file_name"] == "test.png"
    assert body["size_bytes"] == 5
    m_store.assert_called_once()
    assert m_store.call_args.kwargs.get("session_id") == "sess-1"
    assert m_store.call_args.kwargs.get("data") == b"\x89PNG"
    assert m_store.call_args.kwargs.get("file_name") == "test.png"


def test_upload_attachment_rejects_non_image(client: TestClient):
    resp = client.post(
        "/attachments",
        files={"file": ("test.txt", b"hello", "text/plain")},
        data={"session_id": "sess-1"},
    )
    assert resp.status_code == 422


def test_upload_attachment_rejects_oversize_image(client: TestClient):
    resp = client.post(
        "/attachments",
        files={"file": ("big.png", b"x" * (5 * 1024 * 1024 + 1), "image/png")},
    )
    assert resp.status_code == 422


def test_upload_attachment_empty_file(client: TestClient):
    """Empty file -> 422."""
    resp = client.post("/attachments", files={"file": ("empty.png", b"", "image/png")})
    assert resp.status_code == 422


def test_upload_attachment_store_returns_no_id():
    """store returns no attachment_id -> server error (frontend uploadAttachment raises on this)."""
    with patch(
        "eagle_rag.api.attachments.store_attachment_sync",
        return_value={"file_name": "x", "mime": "text/plain", "size_bytes": 5},
    ):
        # Do not surface the server exception; observe the HTTP error contract via 5xx response.
        local_client = TestClient(app, raise_server_exceptions=False)
        resp = local_client.post(
            "/attachments",
            files={"file": ("test.png", b"\x89PNG", "image/png")},
        )
    assert resp.status_code >= 500


def test_get_attachment_meta(client: TestClient):
    """GET /attachments/{id} returns metadata; storage_path is excluded."""
    meta = {
        "attachment_id": "att-1",
        "session_id": "s1",
        "file_name": "test.txt",
        "mime": "text/plain",
        "size_bytes": 5,
        "storage_path": "/tmp/att-1",
        "expires_at": "2024-01-01T00:00:00",
        "created_at": "2024-01-01T00:00:00",
    }
    with patch(
        "eagle_rag.api.attachments.get_attachment", new_callable=AsyncMock, return_value=meta
    ):
        resp = client.get("/attachments/att-1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["attachment_id"] == "att-1"
    assert body["file_name"] == "test.txt"
    assert body["mime"] == "text/plain"
    assert body["size_bytes"] == 5
    assert "storage_path" not in body


def test_get_attachment_meta_not_found(client: TestClient):
    with patch(
        "eagle_rag.api.attachments.get_attachment", new_callable=AsyncMock, return_value=None
    ):
        resp = client.get("/attachments/missing")
    assert resp.status_code == 404


def test_get_attachment_content(client: TestClient):
    """GET /attachments/{id}/content returns the raw byte stream."""
    meta = {"attachment_id": "att-1", "mime": "text/plain", "storage_path": "/tmp/att-1"}
    with (
        patch(
            "eagle_rag.api.attachments.get_attachment", new_callable=AsyncMock, return_value=meta
        ),
        patch("eagle_rag.api.attachments.get_attachment_bytes_sync", return_value=b"hello"),
    ):
        resp = client.get("/attachments/att-1/content")
    assert resp.status_code == 200
    assert resp.content == b"hello"
    assert resp.headers["content-type"].startswith("text/plain")


def test_get_attachment_content_not_found(client: TestClient):
    with patch(
        "eagle_rag.api.attachments.get_attachment", new_callable=AsyncMock, return_value=None
    ):
        resp = client.get("/attachments/missing/content")
    assert resp.status_code == 404


def test_get_attachment_content_bytes_missing(client: TestClient):
    """Metadata exists but bytes are missing -> 404."""
    meta = {"attachment_id": "att-1", "mime": "text/plain", "storage_path": "/tmp/att-1"}
    with (
        patch(
            "eagle_rag.api.attachments.get_attachment", new_callable=AsyncMock, return_value=meta
        ),
        patch("eagle_rag.api.attachments.get_attachment_bytes_sync", return_value=None),
    ):
        resp = client.get("/attachments/att-1/content")
    assert resp.status_code == 404


def test_delete_attachment(client: TestClient):
    with patch("eagle_rag.api.attachments.delete_attachment_sync", return_value=True):
        resp = client.delete("/attachments/att-1")
    assert resp.status_code == 200
    assert resp.json()["deleted"] is True


def test_delete_attachment_not_found(client: TestClient):
    with patch("eagle_rag.api.attachments.delete_attachment_sync", return_value=False):
        resp = client.delete("/attachments/missing")
    assert resp.status_code == 404


# ===========================================================================
# Notifications API (/notifications*)
# ===========================================================================


def test_list_notifications(client: TestClient):
    """GET /notifications returns items + unread_count + pagination metadata."""
    items = [
        {
            "id": "n1",
            "type": "ingest",
            "title": "Ingest complete",
            "body": "ok",
            "kb_name": "tax_law",
            "job_id": "j1",
            "read": False,
            "created_at": "2024-01-01T00:00:00",
        },
        {
            "id": "n2",
            "type": "system",
            "title": "欢迎",
            "body": "",
            "kb_name": None,
            "job_id": None,
            "read": True,
            "created_at": "2024-01-02T00:00:00",
        },
    ]
    with (
        patch(
            "eagle_rag.notifications.store.list_notifications",
            new_callable=AsyncMock,
            return_value=items,
        ),
        patch("eagle_rag.notifications.store.unread_count", new_callable=AsyncMock, return_value=3),
    ):
        resp = client.get("/notifications", params={"limit": 50, "offset": 0})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 2
    assert body["items"][0]["id"] == "n1"
    assert body["items"][0]["read"] is False
    assert body["unread_count"] == 3
    assert body["limit"] == 50
    assert body["offset"] == 0


def test_list_notifications_filter_unread(client: TestClient):
    """read=false returns only unread (matches the frontend unread_only semantics)."""
    with (
        patch(
            "eagle_rag.notifications.store.list_notifications",
            new_callable=AsyncMock,
            return_value=[],
        ) as m_list,
        patch("eagle_rag.notifications.store.unread_count", new_callable=AsyncMock, return_value=0),
    ):
        resp = client.get("/notifications", params={"read": "false", "limit": 10})
    assert resp.status_code == 200
    m_list.assert_awaited_once()
    assert m_list.call_args.kwargs.get("read") is False


def test_list_notifications_invalid_limit(client: TestClient):
    resp = client.get("/notifications", params={"limit": 0})
    assert resp.status_code == 422


def test_mark_notification_read(client: TestClient):
    """PATCH /notifications/{id} marks as read."""
    with patch(
        "eagle_rag.notifications.store.mark_read", new_callable=AsyncMock, return_value=True
    ):
        resp = client.patch("/notifications/n1")
    assert resp.status_code == 200
    assert resp.json()["read"] is True


def test_mark_notification_read_not_found(client: TestClient):
    with patch(
        "eagle_rag.notifications.store.mark_read", new_callable=AsyncMock, return_value=False
    ):
        resp = client.patch("/notifications/missing")
    assert resp.status_code == 404


def test_read_all_notifications(client: TestClient):
    """POST /notifications/read-all marks all as read."""
    with patch(
        "eagle_rag.notifications.store.mark_all_read", new_callable=AsyncMock, return_value=5
    ):
        resp = client.post("/notifications/read-all")
    assert resp.status_code == 200
    assert resp.json()["updated"] == 5


# ===========================================================================
# User and preferences API (/users/me*)
# ===========================================================================


def test_get_me(client: TestClient):
    """GET /users/me returns the static default user profile."""
    resp = client.get("/users/me")
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == "default"
    assert body["display_name"] == "Eagle User"
    assert body["avatar_initials"] == "EU"
    assert body["locale"] == "zh"


def test_patch_me(client: TestClient):
    """PATCH /users/me is a no-op; returns the static default profile."""
    resp = client.patch("/users/me", json={"display_name": "新名字", "locale": "en"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == "default"
    assert body["display_name"] == "Eagle User"
    assert body["locale"] == "zh"


def test_get_preferences(client: TestClient):
    """GET /users/me/preferences returns the static default preferences."""
    resp = client.get("/users/me/preferences")
    assert resp.status_code == 200
    body = resp.json()
    assert body["default_kb_name"] == ""
    assert body["notifications_enabled"] is True
    assert body["ingest_poll_interval_ms"] == 5000


def test_patch_preferences(client: TestClient):
    """PATCH /users/me/preferences is a no-op; returns the static default preferences."""
    resp = client.patch(
        "/users/me/preferences",
        json={"default_kb_name": "finance", "notifications_enabled": False},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["default_kb_name"] == ""
    assert body["notifications_enabled"] is True
    assert body["ingest_poll_interval_ms"] == 5000
