"""URL validation, SSRF guard and reachability prefetch for ingest-by-URL.

Preflight used by ``POST /ingest/validate/url`` runs, in order:

1. :func:`validate_url_format` — rejects non-http(s) schemes, missing hosts,
   userinfo credentials and out-of-range ports.
2. :func:`assert_not_ssrf_target` — resolves the hostname (bounded DNS) and
   rejects private/loopback/link-local/metadata addresses.
3. :func:`prefetch_url` — lightweight HEAD (GET fallback) reachability check.
4. Content-type-aware limit checks — PDF URLs share MinerU size/page rules
   with local file ingest via :mod:`eagle_rag.ingest.limits`.

``POST /ingest`` (enqueue) only runs steps 1–2 so submit stays snappy after
a successful validate.
"""

from __future__ import annotations

import ipaddress
import socket
import tempfile
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

import httpx

from eagle_rag.ingest.limits import (
    IngestLimitError,
    ResourceKind,
    check_size_limit,
    validate_downloaded_pdf,
)
from eagle_rag.telemetry import get_logger

logger = get_logger(__name__)

__all__ = [
    "UrlValidationError",
    "PrefetchResult",
    "UrlValidateResult",
    "validate_url_format",
    "assert_not_ssrf_target",
    "prefetch_url",
    "classify_url_resource_kind",
    "validate_url_preflight",
]

# Networks that must never be reached by a user-supplied URL. Cloud metadata
# services (169.254.169.254) live in 169.254.0.0/16, which is included here.
_FORBIDDEN_NETWORKS: tuple[ipaddress.IPv6Network | ipaddress.IPv4Network, ...] = (
    ipaddress.ip_network("127.0.0.0/8", strict=False),
    ipaddress.ip_network("10.0.0.0/8", strict=False),
    ipaddress.ip_network("172.16.0.0/12", strict=False),
    ipaddress.ip_network("192.168.0.0/16", strict=False),
    ipaddress.ip_network("169.254.0.0/16", strict=False),
    ipaddress.ip_network("0.0.0.0/8", strict=False),
    ipaddress.ip_network("::1/128", strict=False),
    ipaddress.ip_network("fc00::/7", strict=False),
    ipaddress.ip_network("fe80::/10", strict=False),
)

_ALLOWED_SCHEMES = {"http", "https"}
_UA = "Eagle-RAG/1.0 (URL prefetch)"


class UrlValidationError(Exception):
    """Raised when a user-supplied URL fails validation/prefetch.

    Attributes
    ----------
    code:
        Machine-readable error code (e.g. ``url_unreachable``).
    reason:
        Human-readable explanation.
    suggestion:
        Optional corrective hint surfaced to the end user.
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
        """Return the JSON-serialisable ``detail`` payload for a 422 response.

        ``suggestion`` is omitted entirely when ``None`` so the response body
        only contains the keys that carry a value.
        """
        detail: dict[str, Any] = {"code": self.code, "reason": self.reason}
        if self.suggestion is not None:
            detail["suggestion"] = self.suggestion
        return detail


@dataclass
class PrefetchResult:
    """Outcome of a successful :func:`prefetch_url` call."""

    status_code: int
    content_type: str | None = None
    final_url: str | None = None
    content_length: int | None = None
    ssl_insecure: bool = False


@dataclass(frozen=True)
class UrlValidateResult:
    """Outcome of a successful :func:`validate_url_preflight` call."""

    status_code: int
    content_type: str | None
    final_url: str | None
    resource_kind: ResourceKind
    size_bytes: int | None = None
    page_count: int | None = None
    suggested_pipeline: Literal["pixelrag", "knowhere"] | None = None
    ssl_insecure: bool = False


def _is_ssl_verify_error(exc: BaseException) -> bool:
    """Return True when ``exc`` (or its cause chain) is a TLS verify failure."""
    cur: BaseException | None = exc
    while cur is not None:
        text = str(cur).lower()
        if "certificate_verify_failed" in text or "ssl: certificate" in text:
            return True
        if type(cur).__name__ in {"SSLCertVerificationError", "SSLError"}:
            return True
        cur = cur.__cause__ or cur.__context__  # type: ignore[assignment]
        if cur is exc:
            break
    return False


def validate_url_format(url: str) -> None:
    """Validate the syntactic shape of ``url``.

    Rejects non-http(s) schemes, empty hosts, userinfo credentials and
    out-of-range ports. Raises :class:`UrlValidationError` on any failure.

    If ``urllib.parse.urlparse`` itself raises, that is a programming error
    and the underlying :class:`ValueError` is allowed to propagate.
    """
    parsed = urlparse(url)

    scheme = (parsed.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise UrlValidationError(
            code="invalid_url_format",
            reason=f"URL scheme must be http or https, got {scheme!r}",
            suggestion="Use a URL starting with http:// or https://",
        )

    if not parsed.hostname:
        raise UrlValidationError(
            code="invalid_url_format",
            reason="URL must contain a host name",
            suggestion="Provide a fully-qualified URL such as https://example.com/path",
        )

    if parsed.username is not None or parsed.password is not None:
        raise UrlValidationError(
            code="invalid_url_format",
            reason="URL must not contain userinfo credentials",
            suggestion="Remove the user:password@ segment from the URL",
        )

    port = parsed.port
    if port is not None and not (1 <= port <= 65535):
        raise UrlValidationError(
            code="invalid_url_format",
            reason=f"URL port must be between 1 and 65535, got {port}",
        )


def _is_forbidden_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return ``True`` if ``ip`` belongs to any forbidden network."""
    return any(ip in net for net in _FORBIDDEN_NETWORKS)


def _resolve_host_ips(host: str, *, timeout_sec: float) -> list[str]:
    """Resolve ``host`` with a hard wall-clock timeout."""

    def _lookup() -> list[str]:
        infos = socket.getaddrinfo(host, None)
        ips: list[str] = []
        for info in infos:
            sockaddr = info[4]
            ips.append(str(sockaddr[0]))
        return ips

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_lookup)
        try:
            return future.result(timeout=timeout_sec)
        except FuturesTimeoutError as exc:
            future.cancel()
            raise UrlValidationError(
                code="url_timeout",
                reason=f"DNS resolution timed out for host {host} after {timeout_sec}s",
                suggestion="Check the hostname or try again later",
            ) from exc


def assert_not_ssrf_target(url: str, *, dns_timeout_sec: float = 3.0) -> None:
    """Resolve ``url``'s host and reject forbidden (private/loopback) targets.

    IP-literal hosts are checked directly without DNS resolution. Hostnames
    are resolved via bounded :func:`socket.getaddrinfo`; every returned address
    is checked against the forbidden network list.
    """
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        # validate_url_format should have caught this already, but be defensive.
        raise UrlValidationError(
            code="invalid_url_format",
            reason="URL must contain a host name",
        )

    # IP literal (e.g. http://127.0.0.1/) — check directly, no DNS lookup.
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # Not an IP literal — proceed to DNS resolution below.
        pass
    else:
        if _is_forbidden_ip(ip):
            raise UrlValidationError(
                code="url_target_forbidden",
                reason=f"URL resolves to a forbidden private/loopback address: {ip}",
                suggestion="Use a publicly accessible URL",
            )
        return

    try:
        ip_strs = _resolve_host_ips(host, timeout_sec=dns_timeout_sec)
    except UrlValidationError:
        raise
    except socket.gaierror as exc:
        raise UrlValidationError(
            code="url_unreachable",
            reason=f"DNS resolution failed for host {host}: {exc}",
        ) from exc

    for ip_str in ip_strs:
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            # Skip exotic address families we cannot classify.
            continue
        if _is_forbidden_ip(ip):
            raise UrlValidationError(
                code="url_target_forbidden",
                reason=f"URL resolves to a forbidden private/loopback address: {ip}",
                suggestion="Use a publicly accessible URL",
            )


def _parse_content_length(headers: httpx.Headers) -> int | None:
    raw = headers.get("content-length")
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def prefetch_url(
    url: str,
    *,
    timeout: float = 10.0,
    max_redirects: int = 3,
    verify: bool = True,
) -> PrefetchResult:
    """Prefetch ``url`` to confirm reachability and a 2xx response.

    Uses HEAD first; falls back to a streaming GET (closed immediately after
    headers are received) when the server rejects HEAD with 405 or 403. The
    response body is never consumed.

    Raises :class:`UrlValidationError` (codes ``url_unreachable``,
    ``url_timeout``, ``invalid_url_format``, ``url_bad_status``) on failure.
    """
    client = httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        max_redirects=max_redirects,
        headers={"User-Agent": _UA},
        verify=verify,
    )
    try:
        resp = client.head(url)
        if resp.status_code in (403, 405):
            # Server forbids HEAD; fall back to a streaming GET that we close
            # as soon as the headers arrive (response body not consumed).
            with client.stream("GET", url) as stream_resp:
                status_code = stream_resp.status_code
                content_type = stream_resp.headers.get("content-type")
                final_url = str(stream_resp.url)
                content_length = _parse_content_length(stream_resp.headers)
        else:
            status_code = resp.status_code
            content_type = resp.headers.get("content-type")
            final_url = str(resp.url)
            content_length = _parse_content_length(resp.headers)

        if not (200 <= status_code < 300):
            raise UrlValidationError(
                code="url_bad_status",
                reason=f"HTTP {status_code}",
                suggestion="Ensure the URL returns a 2xx status code",
            )

        return PrefetchResult(
            status_code=status_code,
            content_type=content_type,
            final_url=final_url,
            content_length=content_length,
            ssl_insecure=not verify,
        )
    except UrlValidationError:
        raise
    except httpx.ConnectError as exc:
        if _is_ssl_verify_error(exc):
            raise UrlValidationError(
                code="url_ssl_error",
                reason=f"TLS certificate verification failed for {url}: {exc}",
                suggestion=(
                    "The site may send an incomplete certificate chain. "
                    "Retry is attempted automatically when ssl_verify_fallback is enabled."
                ),
            ) from exc
        raise UrlValidationError(
            code="url_unreachable",
            reason=f"Cannot connect to {url}: {exc}",
        ) from exc
    except httpx.TimeoutException as exc:
        raise UrlValidationError(
            code="url_timeout",
            reason=f"Request to {url} timed out after {timeout}s",
            suggestion="Check if the target server is reachable or try again later",
        ) from exc
    except httpx.TooManyRedirects as exc:
        raise UrlValidationError(
            code="url_unreachable",
            reason=f"Too many redirects from {url}",
        ) from exc
    except httpx.InvalidURL as exc:
        raise UrlValidationError(
            code="invalid_url_format",
            reason=f"Invalid URL: {exc}",
        ) from exc
    finally:
        client.close()


def classify_url_resource_kind(
    *,
    content_type: str | None,
    final_url: str | None,
    original_url: str,
) -> ResourceKind:
    """Classify a URL resource from Content-Type and path hints."""
    ct = (content_type or "").lower()
    path = urlparse(final_url or original_url).path.lower()
    if "pdf" in ct or path.endswith(".pdf"):
        return "pdf"
    if ct.startswith("image/"):
        return "image"
    if ct.startswith("text/html") or "xhtml" in ct or path.endswith((".htm", ".html")):
        return "html"
    return "other"


def _suggested_pipeline(kind: ResourceKind) -> Literal["pixelrag", "knowhere"]:
    # Bare HTTP URIs route to PixelRAG via HttpUriSelector; PDF/HTML force-Knowhere
    # is available via filename prefix on enqueue.
    if kind in {"html", "pdf", "image"}:
        return "pixelrag"
    return "pixelrag"


def _download_url_capped(
    url: str,
    *,
    max_bytes: int,
    timeout: float,
    max_redirects: int,
    verify: bool = True,
) -> tuple[Path, int]:
    """Stream-download ``url`` into a temp file, capped at ``max_bytes``."""
    tmp = tempfile.NamedTemporaryFile(prefix="eagle-url-pdf-", suffix=".pdf", delete=False)
    tmp_path = Path(tmp.name)
    written = 0
    try:
        with httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            max_redirects=max_redirects,
            headers={"User-Agent": _UA},
            verify=verify,
        ) as client:
            with client.stream("GET", url) as resp:
                if not (200 <= resp.status_code < 300):
                    raise UrlValidationError(
                        code="url_bad_status",
                        reason=f"HTTP {resp.status_code}",
                        suggestion="Ensure the URL returns a 2xx status code",
                    )
                for chunk in resp.iter_bytes():
                    if not chunk:
                        continue
                    written += len(chunk)
                    if written > max_bytes:
                        raise IngestLimitError(
                            "file_too_large",
                            f"File is larger than {max_bytes} bytes "
                            "(MinerU Precision Extract API limit).",
                            suggestion=(
                                "Reduce the file size or split the document, then re-upload."
                            ),
                        )
                    tmp.write(chunk)
        tmp.close()
        return tmp_path, written
    except (UrlValidationError, IngestLimitError):
        tmp.close()
        tmp_path.unlink(missing_ok=True)
        raise
    except httpx.TimeoutException as exc:
        tmp.close()
        tmp_path.unlink(missing_ok=True)
        raise UrlValidationError(
            code="url_timeout",
            reason=f"Request to {url} timed out after {timeout}s",
            suggestion="Check if the target server is reachable or try again later",
        ) from exc
    except httpx.HTTPError as exc:
        tmp.close()
        tmp_path.unlink(missing_ok=True)
        raise UrlValidationError(
            code="url_unreachable",
            reason=f"Cannot download {url}: {exc}",
        ) from exc
    except Exception:
        tmp.close()
        tmp_path.unlink(missing_ok=True)
        raise


def validate_url_preflight(
    url: str,
    *,
    dns_timeout_sec: float = 3.0,
    timeout_sec: float = 5.0,
    max_redirects: int = 3,
    pdf_download_timeout_sec: float = 30.0,
    verify_ssl: bool = True,
    ssl_verify_fallback: bool = True,
) -> UrlValidateResult:
    """Full URL preflight: format, SSRF, reachability, and kind-aware limits."""
    from eagle_rag.config import get_settings

    validate_url_format(url)
    assert_not_ssrf_target(url, dns_timeout_sec=dns_timeout_sec)

    prefetch: PrefetchResult
    try:
        prefetch = prefetch_url(
            url,
            timeout=timeout_sec,
            max_redirects=max_redirects,
            verify=verify_ssl,
        )
    except UrlValidationError as exc:
        if verify_ssl and ssl_verify_fallback and exc.code == "url_ssl_error":
            logger.warning(
                "TLS verify failed for URL preflight; retrying without verify "
                "(incomplete certificate chain is common on some sites)",
                extra={"url": url},
            )
            prefetch = prefetch_url(
                url,
                timeout=timeout_sec,
                max_redirects=max_redirects,
                verify=False,
            )
        else:
            raise

    kind = classify_url_resource_kind(
        content_type=prefetch.content_type,
        final_url=prefetch.final_url,
        original_url=url,
    )
    size_bytes = prefetch.content_length
    page_count: int | None = None
    verify_for_download = not prefetch.ssl_insecure

    if kind in {"pdf", "image", "other"} and size_bytes is not None:
        check_size_limit(size_bytes)

    if kind == "pdf":
        limits = get_settings().ingest.limits
        max_bytes = int(limits.max_file_bytes)
        if size_bytes is not None:
            check_size_limit(size_bytes)
        tmp_path: Path | None = None
        try:
            tmp_path, downloaded = _download_url_capped(
                prefetch.final_url or url,
                max_bytes=max_bytes,
                timeout=pdf_download_timeout_sec,
                max_redirects=max_redirects,
                verify=verify_for_download,
            )
            size_bytes = downloaded
            # Re-check SSRF on final URL after redirects before treating bytes as trusted.
            assert_not_ssrf_target(
                prefetch.final_url or url,
                dns_timeout_sec=dns_timeout_sec,
            )
            page_count = validate_downloaded_pdf(
                tmp_path,
                size_bytes=downloaded,
                filename="document.pdf",
            )
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

    return UrlValidateResult(
        status_code=prefetch.status_code,
        content_type=prefetch.content_type,
        final_url=prefetch.final_url,
        resource_kind=kind,
        size_bytes=size_bytes,
        page_count=page_count,
        suggested_pipeline=_suggested_pipeline(kind),
        ssl_insecure=prefetch.ssl_insecure,
    )
