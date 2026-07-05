"""Query routing selectors: strategy pattern + FallbackChain.

Each ``RouteSelector`` implements one routing strategy and returns a ``RouteDecision``
(when it can decide) or ``None`` (to defer to the next strategy). ``FallbackChain``
tries selectors in order and the first non-None decision wins.

Default chain order (matches the original ``route_query`` auto-mode decision chain):
    1. ``ForcedModeSelector`` — decides text/visual/hybrid directly; defers on auto.
    2. ``AttachmentSelector`` — when attachments contain documents → hybrid; otherwise defers.
    3. ``LLMIntentSelector`` — LLM intent classification; returns None when
       unconfigured/failing (falls back).
    4. ``HeuristicSelector`` — first-match keyword rules; always decides (including the default).

All selectors take their config/dependencies via constructor injection and never read
the global ``get_settings()``, easing unit testing.
"""

from __future__ import annotations

import time
from typing import Any, Protocol

from eagle_rag.router.models import RouteContext, RouteDecision
from eagle_rag.telemetry import get_ai_logger, get_logger, trace_span, truncate

__all__ = [
    "RouteSelector",
    "ForcedModeSelector",
    "AttachmentSelector",
    "LLMIntentSelector",
    "HeuristicSelector",
    "FallbackChain",
]

logger = get_logger(__name__)
ai_logger = get_ai_logger(__name__)


class RouteSelector(Protocol):
    """Routing selector protocol: return a decision to commit, or None to defer."""

    def select(self, ctx: RouteContext) -> RouteDecision | None: ...


class ForcedModeSelector:
    """Forced-mode selector: decides text/visual/hybrid directly; defers on auto."""

    def __init__(self, *, default_mode: str = "auto") -> None:
        self.default_mode = default_mode

    def select(self, ctx: RouteContext) -> RouteDecision | None:
        mode = (ctx.mode or self.default_mode or "auto").lower()
        if mode == "text":
            return RouteDecision(
                mode=mode, selected=["text"], reason="forced text mode", selector="forced"
            )
        if mode == "visual":
            return RouteDecision(
                mode=mode, selected=["visual"], reason="forced visual mode", selector="forced"
            )
        if mode == "hybrid":
            return RouteDecision(
                mode=mode,
                selected=["text", "visual"],
                reason="forced hybrid mode",
                selector="forced",
            )
        # auto or unknown: defer to the next strategy.
        return None


class AttachmentSelector:
    """Attachment selector: doc attachments → hybrid retrieval; otherwise defer."""

    def select(self, ctx: RouteContext) -> RouteDecision | None:
        if ctx.has_doc_attachments:
            return RouteDecision(
                mode="auto",
                selected=["text", "visual"],
                reason="attachments include documents; prefer hybrid retrieval",
                kb_name=ctx.kb_name,
                selector="attachment",
            )
        return None


class LLMIntentSelector:
    """LLM intent classification selector: calls the LLM to decide the retrieval method.

    Constructor-injected with ``llm`` (optional; defers when None), ``prompt_template``,
    and ``model_name``. Returns None (falling back to heuristics) when the call fails or
    the response cannot be parsed.
    """

    def __init__(
        self,
        *,
        llm: Any | None,
        prompt_template: str,
        model_name: str = "",
        enabled: bool = True,
    ) -> None:
        self.llm = llm
        self.prompt_template = prompt_template
        self.model_name = model_name
        self.enabled = enabled

    def select(self, ctx: RouteContext) -> RouteDecision | None:
        if not self.enabled or self.llm is None:
            return None
        with trace_span("llm_intent"):
            t0 = time.monotonic()
            prompt = self.prompt_template.replace("{query}", ctx.query)
            try:
                resp = self.llm.complete(prompt)
                raw = (getattr(resp, "text", str(resp)) or "").strip().lower()
                latency_ms = int((time.monotonic() - t0) * 1000)
                self._emit(
                    "llm_intent",
                    model=self.model_name,
                    prompt=truncate(prompt, 512),
                    response=truncate(raw, 512),
                    latency_ms=latency_ms,
                    fallback=False,
                )
                # Match the prompt contract ("text" / "visual" / "hybrid" single word).
                if "hybrid" in raw:
                    return RouteDecision(
                        mode="auto",
                        selected=["text", "visual"],
                        reason="LLM:hybrid",
                        kb_name=ctx.kb_name,
                        selector="llm",
                    )
                if "visual" in raw and "text" in raw:
                    return RouteDecision(
                        mode="auto",
                        selected=["text", "visual"],
                        reason="LLM:hybrid",
                        kb_name=ctx.kb_name,
                        selector="llm",
                    )
                if "visual" in raw:
                    return RouteDecision(
                        mode="auto",
                        selected=["visual"],
                        reason="LLM:visual",
                        kb_name=ctx.kb_name,
                        selector="llm",
                    )
                if "text" in raw:
                    return RouteDecision(
                        mode="auto",
                        selected=["text"],
                        reason="LLM:text",
                        kb_name=ctx.kb_name,
                        selector="llm",
                    )
                return None
            except Exception as exc:  # noqa: BLE001
                latency_ms = int((time.monotonic() - t0) * 1000)
                logger.debug(
                    "LLM intent classification failed; falling back to heuristics: %s",
                    exc,
                )
                self._emit(
                    "llm_intent",
                    model=self.model_name,
                    prompt=truncate(prompt, 512),
                    response="",
                    latency_ms=latency_ms,
                    fallback=True,
                    error=truncate(str(exc), 256),
                )
                return None

    @staticmethod
    def _emit(event: str, **kwargs: Any) -> None:
        try:
            ai_logger.info(event, **kwargs)
        except Exception:  # noqa: BLE001
            logger.debug("telemetry emit failed", exc_info=True)


class HeuristicSelector:
    """Heuristic keyword selector: first-match in rule order; always decides.

    Covers the default case as well. Constructor-injected with ``rules``
    (``list[HeuristicRule]``) and the ``default`` route.
    """

    def __init__(self, *, rules: list[Any], default: str = "text") -> None:
        self.rules = rules
        self.default = default

    def select(self, ctx: RouteContext) -> RouteDecision:
        q = (ctx.query or "").lower()
        for rule in self.rules:
            for kw in rule.keywords:
                if kw.lower() in q:
                    route = rule.route
                    return RouteDecision(
                        mode="auto",
                        selected=[route] if route != "hybrid" else ["text", "visual"],
                        reason=f"heuristic: matched keyword '{kw}'",
                        kb_name=ctx.kb_name,
                        selector="heuristic",
                    )
        # No keyword matched: return the default route.
        default = self.default
        return RouteDecision(
            mode="auto",
            selected=[default] if default != "hybrid" else ["text", "visual"],
            reason=f"heuristic: default {default} retrieval",
            kb_name=ctx.kb_name,
            selector="default",
        )


class FallbackChain:
    """Tries selectors in order; first non-None decision wins.

    If all defer, returns a default text decision.
    """

    def __init__(self, selectors: list[RouteSelector]) -> None:
        self.selectors = selectors

    def select(self, ctx: RouteContext) -> RouteDecision:
        for selector in self.selectors:
            decision = selector.select(ctx)
            if decision is not None:
                return decision
        # Fallback: all selectors deferred (HeuristicSelector always decides;
        # this branch is defensive).
        logger.warning("all route selectors deferred; falling back to default text retrieval")
        return RouteDecision(
            mode="auto",
            selected=["text"],
            reason="fallback default text retrieval",
            kb_name=ctx.kb_name,
            selector="default",
        )
