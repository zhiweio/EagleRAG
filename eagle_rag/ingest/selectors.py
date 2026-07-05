"""Ingest route selectors: strategy pattern + FallbackChain.

Each ``IngestRouteSelector`` implements one routing decision, returning
``list[str]`` (decided pipeline names) or ``None`` (abstain, defer to the next
strategy). ``FallbackChain`` tries them in order; the first non-None wins. If
all abstain, ``default_pipeline`` is used.

Default chain order (matches the original 4-level ``route()`` priority):
    1. ``PrefixSelector`` — filename prefix ``knowhere:``/``pixelrag:`` forces a
       single pipeline.
    2. ``ForcedModeSelector`` — ``settings.router.mode`` text/visual/hybrid
       forces; auto abstains.
    3. ``HttpUriSelector`` — source_uri of http/https → pixelrag.
    4. ``PdfFormSelector`` — PDF form probe (``probe`` is constructor-injected
       to avoid a circular import).
    5. ``ExtensionSelector`` — extension hit on the knowhere/pixelrag sets.
    6. ``ContentTypeSelector`` — sequential content_type rule matching as the
       fallback.

All selectors take their config/dependencies via the constructor and never read
the ``get_settings()`` global, making them easy to unit-test.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from eagle_rag.telemetry import get_logger

__all__ = [
    "IngestRouteContext",
    "IngestRouteSelector",
    "PrefixSelector",
    "ForcedModeSelector",
    "HttpUriSelector",
    "PdfFormSelector",
    "ExtensionSelector",
    "ContentTypeSelector",
    "FallbackChain",
]

logger = get_logger(__name__)


@dataclass(frozen=True)
class IngestRouteContext:
    """Ingest routing context: entry pre-computes derived fields; selectors read-only."""

    filename: str
    cleaned_name: str  # after prefix stripping
    ext: str  # lowercase extension (with dot)
    content_type: str | None
    source_uri: str | None
    is_http: bool
    local_path: str | None
    forced_prefix: str | None  # knowhere/pixelrag prefix hit
    kb_name: str | None
    text_page_ratio: float | None


class IngestRouteSelector(Protocol):
    """Ingest route selector protocol: returns a pipeline list when decided, None to abstain."""

    def select(self, ctx: IngestRouteContext) -> list[str] | None: ...


class PrefixSelector:
    """Prefix selector: filename prefix hit forces a single pipeline; otherwise abstain."""

    def __init__(self, *, prefix_force: dict[str, str]) -> None:
        self.prefix_force = prefix_force

    def select(self, ctx: IngestRouteContext) -> list[str] | None:
        if ctx.forced_prefix:
            return [ctx.forced_prefix]
        return None


class ForcedModeSelector:
    """Forced-mode selector: router.mode of text/visual/hybrid forces; auto abstains."""

    def __init__(self, *, router_mode: str = "auto") -> None:
        self.router_mode = (router_mode or "auto").lower()

    def select(self, ctx: IngestRouteContext) -> list[str] | None:
        if self.router_mode == "text":
            return ["knowhere"]
        if self.router_mode == "visual":
            return ["pixelrag"]
        if self.router_mode == "hybrid":
            return ["knowhere", "pixelrag"]
        return None


class HttpUriSelector:
    """HTTP URI selector: source_uri of http/https → pixelrag."""

    def select(self, ctx: IngestRouteContext) -> list[str] | None:
        if ctx.is_http:
            return ["pixelrag"]
        return None


class PdfFormSelector:
    """PDF form-probe selector: runs the probe when extension/content_type indicates a PDF.

    The ``probe`` callable (i.e. ``probe_pdf_form``) is constructor-injected to
    avoid a circular import with ``router.py``. When ``local_path`` is absent it
    defaults to knowhere (matching the original ``_route_pdf`` fallback).
    """

    def __init__(
        self,
        *,
        probe: Callable[..., str],
        pdf_exts: list[str],
    ) -> None:
        self.probe = probe
        self.pdf_exts = set(pdf_exts)

    def select(self, ctx: IngestRouteContext) -> list[str] | None:
        is_pdf = ctx.ext in self.pdf_exts or (
            ctx.content_type is not None and "pdf" in ctx.content_type.lower()
        )
        if not is_pdf:
            return None
        if not ctx.local_path:
            return ["knowhere"]
        try:
            form = self.probe(ctx.local_path, text_page_ratio=ctx.text_page_ratio)
        except Exception as exc:  # noqa: BLE001
            logger.debug("PDF form probe failed; falling back to knowhere: %s", exc)
            return ["knowhere"]
        return ["pixelrag"] if form == "scanned" else ["knowhere"]


class ExtensionSelector:
    """Extension selector: hits the knowhere/pixelrag extension sets; otherwise abstains."""

    def __init__(
        self,
        *,
        knowhere_exts: list[str],
        pixelrag_exts: list[str],
    ) -> None:
        self.knowhere_exts = set(knowhere_exts)
        self.pixelrag_exts = set(pixelrag_exts)

    def select(self, ctx: IngestRouteContext) -> list[str] | None:
        if ctx.ext in self.knowhere_exts:
            return ["knowhere"]
        if ctx.ext in self.pixelrag_exts:
            return ["pixelrag"]
        return None


class ContentTypeSelector:
    """content_type fallback selector: matches rules in order (startswith/contains)."""

    def __init__(self, *, rules: list[Any]) -> None:
        self.rules = rules

    def select(self, ctx: IngestRouteContext) -> list[str] | None:
        if not ctx.content_type:
            return None
        ct = ctx.content_type.lower()
        for rule in self.rules:
            match = rule.match.lower()
            mode = (rule.mode or "contains").lower()
            hit = ct.startswith(match) if mode == "startswith" else match in ct
            if hit:
                return [rule.pipeline]
        return None


class FallbackChain:
    """Try selectors in order; first non-None wins. Returns default_pipeline if all abstain."""

    def __init__(
        self, selectors: list[IngestRouteSelector], *, default_pipeline: str = "knowhere"
    ) -> None:
        self.selectors = selectors
        self.default_pipeline = default_pipeline

    def select(self, ctx: IngestRouteContext) -> list[str]:
        for selector in self.selectors:
            decision = selector.select(ctx)
            if decision is not None:
                return decision
        logger.warning(
            "all ingest route selectors deferred; falling back to default pipeline %s",
            self.default_pipeline,
        )
        return [self.default_pipeline]
