"""URL validation, SSRF guard and reachability prefetch for ingest-by-URL.

The ``post_ingest`` endpoint accepts an ``url`` Form parameter and dispatches it
to the ingestion pipeline via :func:`eagle_rag.ingest.runner.ingest_url`. Before
the dispatch actually happens, three checks are run, in order:

1. :func:`validate_url_format` — rejects non-http(s) schemes, missing hosts,
   userinfo credentials and out-of-range ports.
2. :func:`assert_not_ssrf_target` — resolves the hostname and rejects
   private/loopback/link-local/metadata addresses (Server-Side Request
   Forgery guard).
3. :func:`prefetch_url` — performs a lightweight HEAD (GET fallback) request
   to confirm the URL is reachable and returns a 2xx status code, without
   downloading the response body.

Each failure raises :class:`UrlValidationError`, which carries a
machine-readable ``code``, a human-readable ``reason`` and an optional
``suggestion``. The API layer maps it to a ``422`` response whose ``detail``
field is the structured dict returned by :meth:`UrlValidationError.to_detail`.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

from eagle_rag.telemetry import get_logger

logger = get_logger(__name__)

__all__ = [
    "UrlValidationError",
    "PrefetchResult",
    "validate_url_format",
    "assert_not_ssrf_target",
    "prefetch_url",
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


def assert_not_ssrf_target(url: str) -> None:
    """Resolve ``url``'s host and reject forbidden (private/loopback) targets.

    IP-literal hosts are checked directly without DNS resolution. Hostnames
    are resolved via :func:`socket.getaddrinfo`; every returned address is
    checked against the forbidden network list.
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
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise UrlValidationError(
            code="url_unreachable",
            reason=f"DNS resolution failed for host {host}: {exc}",
        ) from exc

    for info in infos:
        sockaddr = info[4]
        ip_str = sockaddr[0]
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


def prefetch_url(
    url: str,
    *,
    timeout: float = 10.0,
    max_redirects: int = 3,
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
        headers={"User-Agent": "Eagle-RAG/1.0 (URL prefetch)"},
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
        else:
            status_code = resp.status_code
            content_type = resp.headers.get("content-type")
            final_url = str(resp.url)

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
        )
    except UrlValidationError:
        raise
    except httpx.ConnectError as exc:
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
