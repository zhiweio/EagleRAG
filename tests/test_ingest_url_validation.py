"""URL validation tests for enqueue gate and ``POST /ingest/validate/url``."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from eagle_rag.api.app import app
from eagle_rag.ingest.limits import IngestLimitError
from eagle_rag.ingest.url_validator import UrlValidateResult, UrlValidationError


@pytest.fixture
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


def test_post_ingest_url_valid_dispatches(client: TestClient) -> None:
    """Format + SSRF pass → ingest_url called → 201 (no prefetch on enqueue)."""
    fake_result = {
        "job_id": "j1",
        "status": "pending",
        "dedup_hit": False,
        "document_id": "d1",
    }
    with (
        patch("eagle_rag.api.ingest.validate_url_format") as mock_fmt,
        patch("eagle_rag.api.ingest.assert_not_ssrf_target") as mock_ssrf,
        patch("eagle_rag.ingest.url_validator.prefetch_url") as mock_prefetch,
        patch("eagle_rag.api.ingest.ingest_url", return_value=fake_result) as mock_ingest_url,
    ):
        resp = client.post(
            "/ingest",
            data={
                "url": "https://example.com/x",
                "kb_name": "default",
                "filename": "knowhere:https://example.com/x",
            },
        )
    assert resp.status_code == 201
    body = resp.json()
    assert body["job_id"] == "j1"
    mock_fmt.assert_called_once_with("https://example.com/x")
    mock_ssrf.assert_called_once()
    mock_prefetch.assert_not_called()
    mock_ingest_url.assert_called_once()
    assert mock_ingest_url.call_args.kwargs.get("filename") == "knowhere:https://example.com/x"


def test_validate_url_unreachable(client: TestClient) -> None:
    with patch(
        "eagle_rag.api.ingest.validate_url_preflight",
        side_effect=UrlValidationError(code="url_unreachable", reason="down"),
    ):
        resp = client.post("/ingest/validate/url", data={"url": "https://example.com/x"})
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "url_unreachable"


def test_validate_url_timeout(client: TestClient) -> None:
    with patch(
        "eagle_rag.api.ingest.validate_url_preflight",
        side_effect=UrlValidationError(code="url_timeout", reason="slow"),
    ):
        resp = client.post("/ingest/validate/url", data={"url": "https://example.com/x"})
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "url_timeout"


def test_validate_url_pdf_too_many_pages(client: TestClient) -> None:
    with patch(
        "eagle_rag.api.ingest.validate_url_preflight",
        side_effect=IngestLimitError(
            "pdf_too_many_pages",
            "PDF has 250 pages; maximum allowed is 200",
        ),
    ):
        resp = client.post(
            "/ingest/validate/url",
            data={"url": "https://example.com/doc.pdf"},
        )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "pdf_too_many_pages"


def test_validate_url_ok_html(client: TestClient) -> None:
    fake = UrlValidateResult(
        status_code=200,
        content_type="text/html; charset=utf-8",
        final_url="https://example.com/x",
        resource_kind="html",
        size_bytes=None,
        page_count=None,
        suggested_pipeline="pixelrag",
    )
    with patch("eagle_rag.api.ingest.validate_url_preflight", return_value=fake):
        resp = client.post("/ingest/validate/url", data={"url": "https://example.com/x"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["resource_kind"] == "html"
    assert body["status_code"] == 200


def test_validate_file_pdf_pages(client: TestClient, tmp_path: Path) -> None:
    pdf_path = tmp_path / "ok.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.add_blank_page(width=72, height=72)
    with pdf_path.open("wb") as fh:
        writer.write(fh)

    with pdf_path.open("rb") as fh:
        resp = client.post(
            "/ingest/validate/file",
            files={"file": ("ok.pdf", fh, "application/pdf")},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["resource_kind"] == "pdf"
    assert body["page_count"] == 2


def test_validate_file_too_many_pages(client: TestClient, tmp_path: Path) -> None:
    pdf_path = tmp_path / "big.pdf"
    writer = PdfWriter()
    for _ in range(5):
        writer.add_blank_page(width=72, height=72)
    with pdf_path.open("wb") as fh:
        writer.write(fh)

    fake_settings = MagicMock()
    fake_settings.ingest.limits.enabled = True
    fake_settings.ingest.limits.max_file_bytes = 209_715_200
    fake_settings.ingest.limits.max_pdf_pages = 3

    with (
        pdf_path.open("rb") as fh,
        patch("eagle_rag.ingest.limits.get_settings", return_value=fake_settings),
    ):
        resp = client.post(
            "/ingest/validate/file",
            files={"file": ("big.pdf", fh, "application/pdf")},
        )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "pdf_too_many_pages"


def test_dns_timeout_raises_url_timeout() -> None:
    from eagle_rag.ingest import url_validator as uv

    with patch(
        "eagle_rag.ingest.url_validator._resolve_host_ips",
        side_effect=UrlValidationError(
            code="url_timeout",
            reason="DNS resolution timed out for host example.com after 3.0s",
        ),
    ):
        with pytest.raises(UrlValidationError) as exc_info:
            uv.assert_not_ssrf_target("https://example.com/x", dns_timeout_sec=3.0)
    assert exc_info.value.code == "url_timeout"


def test_validate_url_preflight_ssl_fallback() -> None:
    """Incomplete cert chains: first verify fails, fallback without verify succeeds."""
    from eagle_rag.ingest.url_validator import PrefetchResult, validate_url_preflight

    insecure = PrefetchResult(
        status_code=200,
        content_type="text/html; charset=utf-8",
        final_url="https://example.com/x",
        content_length=None,
        ssl_insecure=True,
    )
    calls: list[bool] = []

    def _prefetch(url: str, **kwargs: object) -> PrefetchResult:
        verify = bool(kwargs.get("verify", True))
        calls.append(verify)
        if verify:
            raise UrlValidationError(
                code="url_ssl_error",
                reason="TLS certificate verification failed",
            )
        return insecure

    with (
        patch("eagle_rag.ingest.url_validator.assert_not_ssrf_target"),
        patch("eagle_rag.ingest.url_validator.prefetch_url", side_effect=_prefetch),
    ):
        result = validate_url_preflight(
            "https://example.com/x",
            verify_ssl=True,
            ssl_verify_fallback=True,
        )
    assert result.resource_kind == "html"
    assert result.ssl_insecure is True
    assert calls == [True, False]
