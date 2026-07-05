"""Format distribution bucket classification."""

from __future__ import annotations

import pytest

from eagle_rag.kb.stats import _classify_format


@pytest.mark.parametrize(
    ("name", "pipeline", "source_uri", "expected"),
    [
        ("report.pdf", "knowhere", None, "pdf_text"),
        ("scan.pdf", "pixelrag", None, "pdf_scan"),
        ("brief.docx", "knowhere", None, "docx"),
        ("deck.pptx", "knowhere", None, "pptx"),
        ("data.xlsx", "knowhere", None, "xlsx"),
        ("rows.csv", "knowhere", None, "csv"),
        ("notes.md", "knowhere", None, "md"),
        ("readme.txt", "knowhere", None, "txt"),
        ("config.json", "knowhere", None, "json"),
        ("page.html", "pixelrag", None, "web"),
        ("photo.jpg", "pixelrag", None, "image"),
        ("tile.png", "pixelrag", None, "image"),
        ("article", "pixelrag", "https://example.com/a", "web"),
        ("unknown.bin", "knowhere", None, "other"),
    ],
)
def test_classify_format(
    name: str,
    pipeline: str,
    source_uri: str | None,
    expected: str,
) -> None:
    assert _classify_format(name=name, pipeline=pipeline, source_uri=source_uri) == expected
