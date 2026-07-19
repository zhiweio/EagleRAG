"""Unit and API tests for ingest size / PDF page guards."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from eagle_rag.api.app import app
from eagle_rag.ingest.limits import (
    IngestLimitError,
    count_pdf_pages,
    strip_routing_prefix,
    validate_ingest_file,
)


def _write_pdf(path: Path, pages: int) -> Path:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    with path.open("wb") as fh:
        writer.write(fh)
    return path


def _limits_settings(
    *,
    enabled: bool = True,
    max_file_bytes: int = 209_715_200,
    max_pdf_pages: int = 200,
) -> SimpleNamespace:
    return SimpleNamespace(
        ingest=SimpleNamespace(
            limits=SimpleNamespace(
                enabled=enabled,
                max_file_bytes=max_file_bytes,
                max_pdf_pages=max_pdf_pages,
            )
        )
    )


def test_strip_routing_prefix() -> None:
    assert strip_routing_prefix("knowhere:report.pdf") == "report.pdf"
    assert strip_routing_prefix("pixelrag:scan.PDF") == "scan.PDF"
    assert strip_routing_prefix("plain.pdf") == "plain.pdf"


def test_count_pdf_pages(tmp_path: Path) -> None:
    pdf = _write_pdf(tmp_path / "three.pdf", 3)
    assert count_pdf_pages(pdf) == 3


def test_validate_ingest_file_accepts_small_pdf(tmp_path: Path) -> None:
    pdf = _write_pdf(tmp_path / "ok.pdf", 2)
    validate_ingest_file(pdf, "ok.pdf", settings=_limits_settings(max_pdf_pages=10))


def test_validate_ingest_file_rejects_too_many_pages(tmp_path: Path) -> None:
    pdf = _write_pdf(tmp_path / "big.pdf", 5)
    with pytest.raises(IngestLimitError) as exc_info:
        validate_ingest_file(
            pdf,
            "knowhere:big.pdf",
            settings=_limits_settings(max_pdf_pages=3),
        )
    assert exc_info.value.code == "pdf_too_many_pages"
    detail = exc_info.value.to_detail()
    assert detail["code"] == "pdf_too_many_pages"
    assert "suggestion" in detail


def test_validate_ingest_file_rejects_too_large(tmp_path: Path) -> None:
    path = tmp_path / "fat.bin"
    path.write_bytes(b"x" * 100)
    with pytest.raises(IngestLimitError) as exc_info:
        validate_ingest_file(
            path,
            "fat.bin",
            settings=_limits_settings(max_file_bytes=50),
        )
    assert exc_info.value.code == "file_too_large"


def test_validate_ingest_file_disabled(tmp_path: Path) -> None:
    pdf = _write_pdf(tmp_path / "huge.pdf", 10)
    validate_ingest_file(
        pdf,
        "huge.pdf",
        settings=_limits_settings(enabled=False, max_pdf_pages=1),
    )


def test_validate_ingest_file_unreadable_pdf(tmp_path: Path) -> None:
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"not a pdf")
    with pytest.raises(IngestLimitError) as exc_info:
        validate_ingest_file(path, "broken.pdf", settings=_limits_settings())
    assert exc_info.value.code == "pdf_unreadable"


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as c:
        yield c


def test_post_ingest_rejects_over_page_pdf(client: TestClient, tmp_path: Path) -> None:
    """POST /ingest with an over-page PDF → 422 pdf_too_many_pages before dispatch."""
    pdf = _write_pdf(tmp_path / "over.pdf", 4)
    data = pdf.read_bytes()

    fake_settings = MagicMock()
    fake_settings.kb_name = "default"
    fake_settings.ingest.limits.enabled = True
    fake_settings.ingest.limits.max_file_bytes = 209_715_200
    fake_settings.ingest.limits.max_pdf_pages = 2

    with (
        patch("eagle_rag.ingest.limits.get_settings", return_value=fake_settings),
        patch("eagle_rag.db.repositories.kb.kb_exists_sync", return_value=True),
    ):
        resp = client.post(
            "/ingest",
            data={"kb_name": "default"},
            files={"file": ("over.pdf", data, "application/pdf")},
        )

    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["code"] == "pdf_too_many_pages"
    assert "suggestion" in detail


def test_post_ingest_rejects_oversize_file(client: TestClient) -> None:
    fake_settings = MagicMock()
    fake_settings.kb_name = "default"
    fake_settings.ingest.limits.enabled = True
    fake_settings.ingest.limits.max_file_bytes = 10
    fake_settings.ingest.limits.max_pdf_pages = 200

    with (
        patch("eagle_rag.ingest.limits.get_settings", return_value=fake_settings),
        patch("eagle_rag.db.repositories.kb.kb_exists_sync", return_value=True),
    ):
        resp = client.post(
            "/ingest",
            data={"kb_name": "default"},
            files={"file": ("note.txt", b"0123456789abcdef", "text/plain")},
        )

    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["code"] == "file_too_large"
