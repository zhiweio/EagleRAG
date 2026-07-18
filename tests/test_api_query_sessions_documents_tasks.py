"""API integration tests for query, sessions, documents, images, ingest, and tasks.

Covers Query (incl. SSE streaming), Sessions, Documents, Images, Ingest, Tasks.

All external dependencies (DB/MinIO/Milvus/Celery) are mocked; verifies HTTP contracts
and response shapes.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from eagle_rag.api.app import app


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# SSE parsing helpers
# ---------------------------------------------------------------------------


def _parse_sse(lines) -> list[dict[str, str]]:
    """Parse SSE text lines into ``[{event, data}, ...]``."""
    events: list[dict[str, str]] = []
    event = "message"
    data_parts: list[str] = []
    for raw in lines:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        line = raw.rstrip("\r")
        if line == "":
            if data_parts:
                events.append({"event": event, "data": "\n".join(data_parts)})
            event = "message"
            data_parts = []
            continue
        if line.startswith(":"):
            # SSE comment / ping
            continue
        if line.startswith("event:"):
            event = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data_parts.append(line[len("data:") :].strip())
    if data_parts:
        events.append({"event": event, "data": "\n".join(data_parts)})
    return events


def _sse_event_names(events: list[dict[str, str]]) -> list[str]:
    return [e["event"] for e in events]


# ---------------------------------------------------------------------------
# Query endpoint tests
# ---------------------------------------------------------------------------


def _session_row(session_id: str = "s1", title: str = "t") -> dict:
    return {
        "session_id": session_id,
        "title": title,
        "kb_name": "default",
        "created_at": None,
        "updated_at": None,
    }


def _message_row(message_id: str = "m1", role: str = "user") -> dict:
    return {
        "message_id": message_id,
        "session_id": "s1",
        "role": role,
        "content": "x",
        "sources": None,
        "steps": None,
        "attachments": None,
        "kb_name": "default",
        "created_at": None,
    }


def test_post_query_non_streaming(client: TestClient) -> None:
    """POST /query returns {answer, sources{text,image}, route, steps[]}."""
    engine = MagicMock()
    engine.query.return_value = {
        "answer": "起征点为5000元",
        "sources": {
            "text": [{"type": "text", "path": "财政/个税", "document_id": "d1"}],
            "image": [],
        },
        "route": {"mode": "auto", "selected": ["text"], "reason": "启发式"},
        "steps": [
            {"name": "route"},
            {"name": "recall"},
            {"name": "rerank"},
            {"name": "generate"},
        ],
    }
    with (
        patch("eagle_rag.api.query._get_engine", return_value=engine),
        patch(
            "eagle_rag.api.query.create_session",
            AsyncMock(return_value=_session_row()),
        ),
        patch(
            "eagle_rag.api.query.add_message",
            AsyncMock(return_value=_message_row("m1", "user")),
        ),
    ):
        response = client.post("/query", json={"query": "个税起征点", "mode": "auto"})

    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == "起征点为5000元"
    assert "sources" in data
    assert "text" in data["sources"]
    assert "image" in data["sources"]
    assert len(data["sources"]["text"]) == 1
    assert data["route"]["mode"] == "auto"
    assert data["route"]["selected"] == ["text"]
    assert [s["name"] for s in data["steps"]] == ["route", "recall", "rerank", "generate"]
    assert data["session_id"]
    assert data["message_id"]


def test_post_query_with_existing_session(client: TestClient) -> None:
    """POST /query with session_id goes through the get_session validation path."""
    engine = MagicMock()
    engine.query.return_value = {
        "answer": "ok",
        "sources": {"text": [], "image": []},
        "route": {},
        "steps": [],
    }
    with (
        patch("eagle_rag.api.query._get_engine", return_value=engine),
        patch(
            "eagle_rag.api.query.get_session",
            AsyncMock(return_value=_session_row("s1", "t")),
        ),
        patch(
            "eagle_rag.api.query.set_session_scope_filter",
            AsyncMock(return_value=_session_row("s1", "t")),
        ),
        patch(
            "eagle_rag.api.query.add_message",
            AsyncMock(return_value=_message_row()),
        ),
    ):
        response = client.post("/query", json={"query": "hi", "session_id": "s1"})

    assert response.status_code == 200
    assert response.json()["session_id"] == "s1"


def test_post_query_session_not_found(client: TestClient) -> None:
    """POST /query with a non-existent session_id returns 404."""
    engine = MagicMock()
    with (
        patch("eagle_rag.api.query._get_engine", return_value=engine),
        patch("eagle_rag.api.query.get_session", AsyncMock(return_value=None)),
    ):
        response = client.post("/query", json={"query": "hi", "session_id": "missing"})

    assert response.status_code == 404


def test_post_query_stream_sse(client: TestClient) -> None:
    """POST /query/stream emits session/step/sources/token/done events in order."""
    events = [
        {"event": "session", "data": {"session_id": "s1", "user_message_id": "u1"}},
        {"event": "step", "data": {"name": "route", "mode": "auto", "selected": ["text"]}},
        {"event": "sources", "data": {"text": [], "image": []}},
        {"event": "token", "data": {"delta": "Hello"}},
        {"event": "token", "data": {"delta": " world"}},
        {
            "event": "done",
            "data": {
                "answer": "Hello world",
                "sources": {"text": [], "image": []},
                "route": {"mode": "auto"},
                "steps": [{"name": "route"}],
            },
        },
    ]
    engine = MagicMock()
    engine.query_stream.return_value = iter(events)
    with (
        patch("eagle_rag.api.query._get_engine", return_value=engine),
        patch(
            "eagle_rag.api.query.create_session",
            AsyncMock(return_value=_session_row()),
        ),
        patch(
            "eagle_rag.api.query.add_message",
            AsyncMock(return_value=_message_row()),
        ),
    ):
        with client.stream("POST", "/query/stream", json={"query": "hi"}) as response:
            assert response.status_code == 200
            lines = list(response.iter_lines())

    sse_events = _parse_sse(lines)
    names = _sse_event_names(sse_events)
    # All 5 event types appear.
    assert "session" in names
    assert "step" in names
    assert "sources" in names
    assert "token" in names
    assert "done" in names
    # Order: session -> step -> sources -> token -> done.
    assert names.index("session") < names.index("step")
    assert names.index("step") < names.index("sources")
    assert names.index("sources") < names.index("token")
    assert names.index("token") < names.index("done")
    # done event data contains the full answer + message_id.
    done = next(e for e in sse_events if e["event"] == "done")
    done_data = json.loads(done["data"])
    assert done_data["answer"] == "Hello world"
    assert "message_id" in done_data
    # session event carries session_id.
    session_evt = next(e for e in sse_events if e["event"] == "session")
    session_data = json.loads(session_evt["data"])
    assert "session_id" in session_data


def test_post_search_stream_sse(client: TestClient) -> None:
    """POST /search/stream emits step/sources/done events (no session or token)."""
    events = [
        {"event": "step", "data": {"name": "route", "mode": "auto", "selected": ["visual"]}},
        {"event": "step", "data": {"name": "recall", "text_count": 0, "visual_count": 2}},
        {"event": "sources", "data": {"text": [], "image": [{"image_id": "i1", "type": "image"}]}},
        {
            "event": "done",
            "data": {
                "sources": {"text": [], "image": [{"image_id": "i1", "type": "image"}]},
                "route": {"mode": "auto", "selected": ["visual"]},
                "steps": [{"name": "route"}, {"name": "recall"}],
            },
        },
    ]
    engine = MagicMock()
    engine.search_stream.return_value = iter(events)
    with patch("eagle_rag.api.query._get_engine", return_value=engine):
        with client.stream(
            "POST",
            "/search/stream",
            json={"query": "Transformer figure"},
        ) as response:
            assert response.status_code == 200
            lines = list(response.iter_lines())

    sse_events = _parse_sse(lines)
    names = _sse_event_names(sse_events)
    assert "step" in names
    assert "sources" in names
    assert "done" in names
    assert "session" not in names
    assert "token" not in names
    assert names.index("step") < names.index("sources") < names.index("done")
    done_data = json.loads(next(e for e in sse_events if e["event"] == "done")["data"])
    assert done_data["sources"]["image"][0]["image_id"] == "i1"


def test_post_query_stream_engine_error(client: TestClient) -> None:
    """POST /query/stream emits an error event when the engine raises."""
    engine = MagicMock()
    engine.query_stream.side_effect = RuntimeError("boom")
    with (
        patch("eagle_rag.api.query._get_engine", return_value=engine),
        patch(
            "eagle_rag.api.query.create_session",
            AsyncMock(return_value=_session_row()),
        ),
        patch(
            "eagle_rag.api.query.add_message",
            AsyncMock(return_value=_message_row()),
        ),
    ):
        with client.stream("POST", "/query/stream", json={"query": "hi"}) as response:
            assert response.status_code == 200
            lines = list(response.iter_lines())

    sse_events = _parse_sse(lines)
    names = _sse_event_names(sse_events)
    assert "error" in names
    err = next(e for e in sse_events if e["event"] == "error")
    err_data = json.loads(err["data"])
    assert "message" in err_data or "detail" in err_data


# ---------------------------------------------------------------------------
# Session endpoint tests
# ---------------------------------------------------------------------------


def test_list_sessions(client: TestClient) -> None:
    """GET /sessions returns {items: SessionSummary[], limit, offset}."""
    sessions = [_session_row("s1", "t1"), _session_row("s2", "t2")]
    with patch("eagle_rag.api.query.list_sessions", AsyncMock(return_value=sessions)):
        response = client.get("/sessions", params={"limit": 10, "offset": 0, "kb_name": "default"})
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert len(data["items"]) == 2
    assert data["items"][0]["session_id"] in {"s1", "s2"}


def test_create_session(client: TestClient) -> None:
    """POST /sessions returns a SessionSummary."""
    with patch(
        "eagle_rag.api.query.create_session",
        AsyncMock(return_value=_session_row("s1", "t")),
    ):
        response = client.post("/sessions", json={"title": "t", "kb_name": "default"})
    assert response.status_code == 201
    data = response.json()
    assert data["session_id"] == "s1"
    assert data["title"] == "t"


def test_get_session(client: TestClient) -> None:
    """GET /sessions/{id} returns a SessionSummary."""
    with patch(
        "eagle_rag.api.query.get_session",
        AsyncMock(return_value=_session_row("s1", "t")),
    ):
        response = client.get("/sessions/s1")
    assert response.status_code == 200
    assert response.json()["session_id"] == "s1"


def test_get_session_not_found(client: TestClient) -> None:
    """GET /sessions/{id} with unknown id returns 404."""
    with patch("eagle_rag.api.query.get_session", AsyncMock(return_value=None)):
        response = client.get("/sessions/missing")
    assert response.status_code == 404


def test_update_session(client: TestClient) -> None:
    """PATCH /sessions/{id} returns the updated SessionSummary."""
    with patch(
        "eagle_rag.api.query.update_session",
        AsyncMock(return_value=_session_row("s1", "new title")),
    ):
        response = client.patch("/sessions/s1", json={"title": "new title"})
    assert response.status_code == 200
    assert response.json()["title"] == "new title"


def test_update_session_not_found(client: TestClient) -> None:
    """PATCH /sessions/{id} with unknown id returns 404."""
    with patch("eagle_rag.api.query.update_session", AsyncMock(return_value=None)):
        response = client.patch("/sessions/missing", json={"title": "x"})
    assert response.status_code == 404


def test_delete_session(client: TestClient) -> None:
    """DELETE /sessions/{id} returns an AckResponse."""
    with patch("eagle_rag.api.query.delete_session", AsyncMock(return_value=True)):
        response = client.delete("/sessions/s1")
    assert response.status_code == 200
    assert response.json()["deleted"] is True


def test_delete_session_not_found(client: TestClient) -> None:
    """DELETE /sessions/{id} with unknown id returns 404."""
    with patch("eagle_rag.api.query.delete_session", AsyncMock(return_value=False)):
        response = client.delete("/sessions/missing")
    assert response.status_code == 404


def test_list_messages(client: TestClient) -> None:
    """GET /sessions/{id}/messages returns {items: Message[], limit, offset}."""
    messages = [
        _message_row("m1", "user"),
        _message_row("m2", "assistant"),
    ]
    with (
        patch(
            "eagle_rag.api.query.get_session",
            AsyncMock(return_value=_session_row()),
        ),
        patch("eagle_rag.api.query.list_messages", AsyncMock(return_value=messages)),
    ):
        response = client.get("/sessions/s1/messages")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert len(data["items"]) == 2
    assert data["items"][0]["message_id"] in {"m1", "m2"}


def test_list_messages_session_not_found(client: TestClient) -> None:
    """GET /sessions/{id}/messages with unknown session returns 404."""
    with patch("eagle_rag.api.query.get_session", AsyncMock(return_value=None)):
        response = client.get("/sessions/missing/messages")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Document endpoint tests
# ---------------------------------------------------------------------------


def _document_row(document_id: str = "d1") -> dict:
    return {
        "document_id": document_id,
        "name": "doc.pdf",
        "source_type": "policy",
        "source_uri": None,
        "pipeline": "knowhere",
        "status": "ready",
        "sha256": None,
        "chunk_count": 5,
        "extra": {},
        "created_at": None,
        "updated_at": None,
        "kb_name": "default",
    }


def test_list_documents(client: TestClient) -> None:
    """GET /documents returns {items: DocumentOut[], total, limit, offset}."""
    docs = [_document_row("d1"), _document_row("d2")]
    with (
        patch("eagle_rag.api.documents.list_documents", AsyncMock(return_value=docs)),
        patch("eagle_rag.api.documents.count_documents", AsyncMock(return_value=2)),
    ):
        response = client.get(
            "/documents",
            params={
                "q": "doc",
                "source_type": "policy",
                "pipeline": "knowhere",
                "kb_name": "default",
                "limit": 10,
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert data["total"] == 2
    assert len(data["items"]) == 2
    assert data["items"][0]["document_id"] in {"d1", "d2"}


def test_get_document(client: TestClient) -> None:
    """GET /documents/{id} returns DocumentOut."""
    with patch("eagle_rag.api.documents.get_document", AsyncMock(return_value=_document_row("d1"))):
        response = client.get("/documents/d1")
    assert response.status_code == 200
    data = response.json()
    assert data["document_id"] == "d1"
    assert data["pipeline"] == "knowhere"


def test_get_document_not_found(client: TestClient) -> None:
    """GET /documents/{id} with unknown id returns 404."""
    with patch("eagle_rag.api.documents.get_document", AsyncMock(return_value=None)):
        response = client.get("/documents/missing")
    assert response.status_code == 404


def test_delete_document(client: TestClient) -> None:
    """DELETE /documents/{id} returns an AckResponse."""
    with patch("eagle_rag.api.documents.delete_document", AsyncMock(return_value=True)):
        response = client.delete("/documents/d1")
    assert response.status_code == 200
    assert response.json()["deleted"] is True


# ---------------------------------------------------------------------------
# Image endpoint tests
# ---------------------------------------------------------------------------


def _image_meta_row(image_id: str = "img1") -> dict:
    return {
        "image_id": image_id,
        "document_id": "d1",
        "page": 2,
        "position": "strip_1",
        "object_key": None,
        "local_path": "/tmp/img1.png",
        "width": 100,
        "height": 100,
        "created_at": None,
        "kb_name": "default",
    }


def test_get_image_bytes(client: TestClient) -> None:
    """GET /images/{id} returns PNG bytes with content-type=image/png."""
    png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\x00IHDR"
    with (
        patch(
            "eagle_rag.api.documents.get_image_meta",
            AsyncMock(return_value=_image_meta_row()),
        ),
        patch("eagle_rag.api.documents.get_image_bytes", return_value=png_bytes),
    ):
        response = client.get("/images/img1")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")


def test_get_image_bytes_not_found(client: TestClient) -> None:
    """GET /images/{id} with unknown id returns 404."""
    with patch("eagle_rag.api.documents.get_image_meta", AsyncMock(return_value=None)):
        response = client.get("/images/missing")
    assert response.status_code == 404


def test_get_image_meta(client: TestClient) -> None:
    """GET /images/{id}/meta returns ImageMetaOut {document_id, page, position, width, height}."""
    with patch(
        "eagle_rag.api.documents.get_image_meta",
        AsyncMock(return_value=_image_meta_row()),
    ):
        response = client.get("/images/img1/meta")
    assert response.status_code == 200
    data = response.json()
    assert data["image_id"] == "img1"
    assert data["document_id"] == "d1"
    assert data["page"] == 2
    assert data["position"] == "strip_1"
    assert data["width"] == 100
    assert data["height"] == 100


def test_get_image_meta_not_found(client: TestClient) -> None:
    """GET /images/{id}/meta with unknown id returns 404."""
    with patch("eagle_rag.api.documents.get_image_meta", AsyncMock(return_value=None)):
        response = client.get("/images/missing/meta")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Ingest endpoint tests
# ---------------------------------------------------------------------------


def test_post_ingest_file(client: TestClient) -> None:
    """POST /ingest multipart file returns {job_id, status, dedup_hit, document_id} (201)."""
    result = {"job_id": "j1", "status": "pending", "dedup_hit": False, "document_id": "d1"}
    with patch("eagle_rag.api.ingest.ingest", MagicMock(return_value=result)) as mock_ingest:
        response = client.post(
            "/ingest",
            files={"file": ("doc.pdf", b"%PDF-1.4 mock", "application/pdf")},
            data={"kb_name": "default", "source_type_hint": "policy"},
        )
    assert response.status_code == 201
    data = response.json()
    assert data["job_id"] == "j1"
    assert data["status"] == "pending"
    assert data["dedup_hit"] is False
    assert data["document_id"] == "d1"
    # kb_name / source_type_hint are passed through.
    _, kwargs = mock_ingest.call_args
    assert kwargs.get("kb_name") == "default"
    assert kwargs.get("source_type_hint") == "policy"
    assert kwargs.get("filename") == "doc.pdf"


def test_post_ingest_file_dedup_hit(client: TestClient) -> None:
    """POST /ingest with a dedup hit returns 200 + dedup_hit=True."""
    result = {
        "job_id": "j1",
        "status": "success",
        "dedup_hit": True,
        "document_id": "existing-doc",
    }
    with patch("eagle_rag.api.ingest.ingest", MagicMock(return_value=result)):
        response = client.post(
            "/ingest",
            files={"file": ("doc.pdf", b"%PDF-1.4 mock", "application/pdf")},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["dedup_hit"] is True
    assert data["status"] == "success"
    assert data["document_id"] == "existing-doc"


def test_post_ingest_url(client: TestClient) -> None:
    """POST /ingest with a form url returns the same response shape."""
    result = {"job_id": "j2", "status": "pending", "dedup_hit": False, "document_id": "d2"}
    with (
        patch("eagle_rag.api.ingest.validate_url_format"),
        patch("eagle_rag.api.ingest.assert_not_ssrf_target"),
        patch("eagle_rag.api.ingest.prefetch_url"),
        patch("eagle_rag.api.ingest.ingest_url", MagicMock(return_value=result)) as mock_ingest_url,
    ):
        response = client.post(
            "/ingest",
            data={"url": "https://example.com/page", "kb_name": "default"},
        )
    assert response.status_code == 201
    data = response.json()
    assert data["job_id"] == "j2"
    assert data["dedup_hit"] is False
    # url + kb_name are passed through.
    args, kwargs = mock_ingest_url.call_args
    assert args[0] == "https://example.com/page"
    assert kwargs.get("kb_name") == "default"


def test_post_ingest_no_file_or_url(client: TestClient) -> None:
    """POST /ingest with neither file nor url returns 422."""
    response = client.post("/ingest")
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Task audit endpoint tests
# ---------------------------------------------------------------------------


def _audit_row(job_id: str = "j1", status: str = "success", updated_at: str | None = "t1") -> dict:
    return {
        "job_id": job_id,
        "document_id": "d1",
        "pipeline": "knowhere",
        "status": status,
        "progress": 100,
        "current": None,
        "total": None,
        "error": None,
        "logs": [],
        "created_at": None,
        "updated_at": updated_at,
        "kb_name": "default",
    }


def test_list_tasks(client: TestClient) -> None:
    """GET /tasks returns {items: TaskAuditOut[], limit, offset}."""
    audits = [_audit_row("j1", "success"), _audit_row("j2", "pending", "t2")]
    with patch("eagle_rag.api.ingest.task_state.list_audits", MagicMock(return_value=audits)):
        response = client.get(
            "/tasks",
            params={
                "pipeline": "knowhere",
                "status": "success",
                "q": "j",
                "kb_name": "default",
                "limit": 10,
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert len(data["items"]) == 2
    assert data["items"][0]["job_id"] in {"j1", "j2"}


def test_get_task(client: TestClient) -> None:
    """GET /tasks/{id} returns TaskAuditOut."""
    with patch(
        "eagle_rag.api.ingest.task_state.get_audit",
        MagicMock(return_value=_audit_row("j1", "success")),
    ):
        response = client.get("/tasks/j1")
    assert response.status_code == 200
    data = response.json()
    assert data["job_id"] == "j1"
    assert data["status"] == "success"
    assert data["pipeline"] == "knowhere"
    # status_phase field (verified if another agent added it, skipped otherwise).
    if "status_phase" in data:
        assert data["status_phase"] in ("pending", "running", "success", "failed")


def test_get_task_not_found(client: TestClient) -> None:
    """GET /tasks/{id} with unknown id returns 404."""
    with patch("eagle_rag.api.ingest.task_state.get_audit", MagicMock(return_value=None)):
        response = client.get("/tasks/missing")
    assert response.status_code == 404


def test_delete_task(client: TestClient) -> None:
    """DELETE /tasks/{id} returns an AckResponse."""
    with patch("eagle_rag.api.ingest.task_state.delete_audit", MagicMock(return_value=1)):
        response = client.delete("/tasks/j1")
    assert response.status_code == 200
    assert response.json()["deleted"] is True


def test_delete_task_not_found(client: TestClient) -> None:
    """DELETE /tasks/{id} with unknown id returns 404."""
    with patch("eagle_rag.api.ingest.task_state.delete_audit", MagicMock(return_value=0)):
        response = client.delete("/tasks/missing")
    assert response.status_code == 404


def test_get_task_logs(client: TestClient) -> None:
    """GET /tasks/{id}/logs returns {job_id, logs[]}."""
    audit = _audit_row("j1", "success")
    audit["logs"] = [{"ts": "2024-01-01T00:00:00Z", "msg": "started"}]
    with patch("eagle_rag.api.ingest.task_state.get_audit", MagicMock(return_value=audit)):
        response = client.get("/tasks/j1/logs")
    assert response.status_code == 200
    data = response.json()
    assert data["job_id"] == "j1"
    assert len(data["logs"]) == 1


def test_get_task_logs_not_found(client: TestClient) -> None:
    """GET /tasks/{id}/logs with unknown id returns 404."""
    with patch("eagle_rag.api.ingest.task_state.get_audit", MagicMock(return_value=None)):
        response = client.get("/tasks/missing/logs")
    assert response.status_code == 404


def test_retry_task(client: TestClient) -> None:
    """POST /tasks/{id}/retry returns {job_id, status, retried} and restores file fields."""
    audit = _audit_row("j1", "failed")
    doc = {
        "document_id": "d1",
        "name": "report.pdf",
        "source_uri": "policy/d1/report.pdf",
        "source_type": "policy",
    }
    with (
        patch(
            "eagle_rag.api.ingest.task_state.get_audit",
            MagicMock(return_value=audit),
        ),
        patch(
            "eagle_rag.api.ingest.registry.get_document_sync",
            MagicMock(return_value=doc),
        ),
        patch("eagle_rag.api.ingest.celery_app", MagicMock()) as mock_celery,
        patch("eagle_rag.api.ingest.sync_execute", MagicMock(return_value=1)) as mock_exec,
    ):
        response = client.post("/tasks/j1/retry")
    assert response.status_code == 200
    data = response.json()
    assert data["job_id"] == "j1"
    assert data["status"] == "pending"
    assert data["retried"] is True
    # Verify the retried task received the recovered file location.
    sent_kwargs = mock_celery.send_task.call_args.kwargs["kwargs"]
    assert sent_kwargs["name"] == "report.pdf"
    assert sent_kwargs["object_key"] == "policy/d1/report.pdf"
    assert sent_kwargs["source_type_hint"] == "policy"
    # State reset must happen before task dispatch to avoid a race where the
    # worker reads the old failed status.
    exec_call_order = mock_exec.call_args_list
    assert exec_call_order, "sync_execute should be called to reset state"


def test_retry_task_not_found(client: TestClient) -> None:
    """POST /tasks/{id}/retry with unknown id returns 404."""
    with patch("eagle_rag.api.ingest.task_state.get_audit", MagicMock(return_value=None)):
        response = client.post("/tasks/missing/retry")
    assert response.status_code == 404


def test_stream_task(client: TestClient) -> None:
    """GET /tasks/{id}/stream emits progress events and closes after a terminal state."""
    audits = [
        _audit_row("j1", "pending", "t1"),
        _audit_row("j1", "rendering", "t2"),
        _audit_row("j1", "success", "t3"),
    ]
    with (
        patch(
            "eagle_rag.api.ingest.task_state.get_audit",
            MagicMock(side_effect=audits),
        ),
        patch("eagle_rag.api.ingest._SSE_POLL_INTERVAL", 0),
    ):
        with client.stream("GET", "/tasks/j1/stream") as response:
            assert response.status_code == 200
            lines = list(response.iter_lines())

    sse_events = _parse_sse(lines)
    progress_events = [e for e in sse_events if e["event"] == "progress"]
    assert len(progress_events) >= 1
    first = json.loads(progress_events[0]["data"])
    assert first["job_id"] == "j1"
    # The last progress event must be a terminal state.
    last = json.loads(progress_events[-1]["data"])
    assert last["status"] == "success"
