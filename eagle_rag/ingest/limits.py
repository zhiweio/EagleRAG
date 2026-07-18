"""Early ingest size/page guards (MinerU Precision Extract API limits).

Reject oversized files and PDFs that exceed the mineru.net Precision Extract
caps (200 MiB / 200 pages) before MinIO upload, Celery dispatch, or MinerU
calls. Structured errors mirror :class:`UrlValidationError` so the API can
return a consistent ``422`` ``detail`` payload.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from eagle_rag.config import get_settings
from eagle_rag.telemetry import get_logger

logger = get_logger(__name__)

__all__ = [
    "IngestLimitError",
    "count_pdf_pages",
    "strip_routing_prefix",
    "validate_ingest_file",
]

_ROUTING_PREFIXES = ("knowhere:", "pixelrag:")


class IngestLimitError(Exception):
    """Raised when a file exceeds configured ingest size or PDF page limits.

    Attributes
    ----------
    code:
        Machine-readable error code (``file_too_large``, ``pdf_too_many_pages``,
        ``pdf_unreadable``).
    reason:
        Human-readable explanation.
    suggestion:
        Optional corrective hint for the end user.
    """

    code: str
    reason: str
    suggestion: str | None

    def __init__(
        self,
        code: str,
        reason: str,
        suggestion: str | None = None,
    ) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason
        self.suggestion = suggestion

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.reason

    def to_detail(self) -> dict[str, Any]:
        """Return the JSON-serialisable ``detail`` payload for a 422 response."""
        detail: dict[str, Any] = {"code": self.code, "reason": self.reason}
        if self.suggestion is not None:
            detail["suggestion"] = self.suggestion
        return detail


def strip_routing_prefix(filename: str) -> str:
    """Strip ``knowhere:`` / ``pixelrag:`` routing prefixes from ``filename``."""
    lower = filename.lower()
    for prefix in _ROUTING_PREFIXES:
        if lower.startswith(prefix):
            return filename[len(prefix) :]
    return filename


def count_pdf_pages(path: Path | str) -> int:
    """Return the page count of a PDF using ``pypdf``.

    Raises
    ------
    IngestLimitError
        With code ``pdf_unreadable`` when the file cannot be opened as a PDF.
    """
    from pypdf import PdfReader

    try:
        reader = PdfReader(str(path))
        return len(reader.pages)
    except IngestLimitError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise IngestLimitError(
            "pdf_unreadable",
            f"PDF could not be read for page-count validation: {exc}",
            suggestion="Re-export or repair the PDF, then try again.",
        ) from exc


def validate_ingest_file(
    local_path: Path | str,
    filename: str,
    *,
    settings: Any | None = None,
) -> None:
    """Enforce ``ingest.limits`` against a local file.

    Always checks ``max_file_bytes``. For ``.pdf`` files (after stripping
    routing prefixes), also enforces ``max_pdf_pages``.

    No-op when ``ingest.limits.enabled`` is false.

    Raises
    ------
    IngestLimitError
        When size or page limits are exceeded, or the PDF is unreadable.
    """
    cfg = (settings or get_settings()).ingest.limits
    if not cfg.enabled:
        return

    path = Path(local_path)
    cleaned = strip_routing_prefix(filename or path.name)
    size = path.stat().st_size
    max_bytes = int(cfg.max_file_bytes)
    if size > max_bytes:
        raise IngestLimitError(
            "file_too_large",
            f"File is {size} bytes; maximum allowed is {max_bytes} bytes "
            "(MinerU Precision Extract API limit).",
            suggestion=("Reduce the file size or split the document, then re-upload."),
        )

    if Path(cleaned).suffix.lower() != ".pdf":
        return

    max_pages = int(cfg.max_pdf_pages)
    page_count = count_pdf_pages(path)
    if page_count > max_pages:
        raise IngestLimitError(
            "pdf_too_many_pages",
            f"PDF has {page_count} pages; maximum allowed is {max_pages} "
            "(MinerU Precision Extract API limit).",
            suggestion=(
                f"Split the PDF into parts of at most {max_pages} pages "
                "and ingest each part separately."
            ),
        )
    logger.debug(
        "ingest limit check passed: file=%s size=%s pages=%s",
        cleaned,
        size,
        page_count,
    )
