"""URL validation integration tests for POST /ingest (url branch).

Covers the three preflight stages (format / SSRF / reachability) and asserts
that on preflight failure ``ingest_url`` is never called, while on success the
existing dispatch path is preserved.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from eagle_rag.api.app import app
from eagle_rag.ingest.url_validator import UrlValidationError


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


def test_post_ingest_url_invalid_scheme(client: TestClient) -> None:
    """Non-http(s) scheme → 422 with code=invalid_url_format."""
    resp = client.post("/ingest", data={"url": "ftp://example.com/x", "kb_name": "default"})
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["code"] == "invalid_url_format"


def test_post_ingest_url_missing_host(client: TestClient) -> None:
    """Empty host → 422 with code=invalid_url_format."""
    resp = client.post("/ingest", data={"url": "https:///path", "kb_name": "default"})
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["code"] == "invalid_url_format"


def test_post_ingest_url_with_userinfo(client: TestClient) -> None:
    """URL with user:pass@ → 422 with code=invalid_url_format."""
    resp = client.post(
        "/ingest",
        data={"url": "https://user:pass@example.com/x", "kb_name": "default"},
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["code"] == "invalid_url_format"


def test_post_ingest_url_loopback_blocked(client: TestClient) -> None:
    """Loopback IP literal → 422 with code=url_target_forbidden."""
    with patch("eagle_rag.ingest.url_validator.socket.getaddrinfo") as mock_gai:
        mock_gai.return_value = [
            (0, 0, 0, "", ("127.0.0.1", 0)),
        ]
        resp = client.post(
            "/ingest",
            data={"url": "http://127.0.0.1:8000/admin", "kb_name": "default"},
        )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["code"] == "url_target_forbidden"


def test_post_ingest_url_metadata_blocked(client: TestClient) -> None:
    """Cloud metadata IP (169.254.169.254) → 422 with code=url_target_forbidden."""
    resp = client.post(
        "/ingest",
        data={
            "url": "http://169.254.169.254/latest/meta-data/",
            "kb_name": "default",
        },
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["code"] == "url_target_forbidden"


def test_post_ingest_url_unreachable(client: TestClient) -> None:
    """Prefetch raises url_unreachable → 422 and ingest_url NOT called."""
    with (
        patch(
            "eagle_rag.api.ingest.prefetch_url",
            side_effect=UrlValidationError(code="url_unreachable", reason="down"),
        ) as mock_prefetch,
        patch("eagle_rag.api.ingest.ingest_url") as mock_ingest_url,
    ):
        resp = client.post(
            "/ingest",
            data={"url": "https://example.com/x", "kb_name": "default"},
        )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["code"] == "url_unreachable"
    mock_prefetch.assert_called_once()
    mock_ingest_url.assert_not_called()


def test_post_ingest_url_timeout(client: TestClient) -> None:
    """Prefetch raises url_timeout → 422."""
    with patch(
        "eagle_rag.api.ingest.prefetch_url",
        side_effect=UrlValidationError(code="url_timeout", reason="slow"),
    ):
        resp = client.post(
            "/ingest",
            data={"url": "https://example.com/x", "kb_name": "default"},
        )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["code"] == "url_timeout"


def test_post_ingest_url_bad_status(client: TestClient) -> None:
    """Prefetch raises url_bad_status with reason=HTTP 404 → 422 carries reason."""
    with patch(
        "eagle_rag.api.ingest.prefetch_url",
        side_effect=UrlValidationError(code="url_bad_status", reason="HTTP 404"),
    ):
        resp = client.post(
            "/ingest",
            data={"url": "https://example.com/missing", "kb_name": "default"},
        )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["code"] == "url_bad_status"
    assert detail["reason"] == "HTTP 404"


def test_post_ingest_url_valid_dispatches(client: TestClient) -> None:
    """Prefetch passes → ingest_url called → 201 with job_id."""
    fake_result = {
        "job_id": "j1",
        "status": "pending",
        "dedup_hit": False,
        "document_id": "d1",
    }
    with (
        patch("eagle_rag.api.ingest.validate_url_format") as mock_fmt,
        patch("eagle_rag.api.ingest.assert_not_ssrf_target") as mock_ssrf,
        patch("eagle_rag.api.ingest.prefetch_url") as mock_prefetch,
        patch("eagle_rag.api.ingest.ingest_url", return_value=fake_result) as mock_ingest_url,
    ):
        resp = client.post(
            "/ingest",
            data={"url": "https://example.com/x", "kb_name": "default"},
        )
    assert resp.status_code == 201
    body = resp.json()
    assert body["job_id"] == "j1"
    assert body["status"] == "pending"
    mock_fmt.assert_called_once_with("https://example.com/x")
    mock_ssrf.assert_called_once_with("https://example.com/x")
    mock_prefetch.assert_called_once()
    mock_ingest_url.assert_called_once()
