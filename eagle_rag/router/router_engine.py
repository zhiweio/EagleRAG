"""Routing engine (Phase 5.1, refactored with the strategy pattern).

Routes user queries to text retrieval (Knowhere), visual retrieval (PixelRAG), or a
hybrid based on the query and ``settings.router.mode``, and returns a routing decision
for the ``steps`` callback. Provides:

- ``route_query(ctx: RouteContext) -> RouteDecision``: routing decision via ``FallbackChain``.
- ``EagleRouterQueryEngine``: query engine combining two retrievers.

Routing logic is implemented by pluggable selectors in ``eagle_rag.router.selectors``;
keywords and the LLM prompt are injected from ``settings.yaml``, so new strategies do
not require changes to this module.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from llama_index.core.schema import ImageDocument, ImageNode, NodeWithScore, TextNode

from eagle_rag.attachments.parser import parse_attachments
from eagle_rag.config import get_settings
from eagle_rag.generation.multimodal_engine import EagleMultimodalQueryEngine
from eagle_rag.retrievers.knowhere_graph_retriever import KnowhereGraphRetriever
from eagle_rag.retrievers.pixelrag_visual_retriever import PixelRAGVisualRetriever
from eagle_rag.router.llm_factory import create_router_llm
from eagle_rag.router.models import RouteContext, RouteDecision
from eagle_rag.router.selectors import (
    AttachmentSelector,
    FallbackChain,
    ForcedModeSelector,
    HeuristicSelector,
    LLMIntentSelector,
    RouteSelector,
)
from eagle_rag.telemetry import get_ai_logger, get_logger, trace_span, truncate

__all__ = ["route_query", "EagleRouterQueryEngine", "RouteContext", "RouteDecision"]

logger = get_logger(__name__)
ai_logger = get_ai_logger(__name__)


def _build_chain(settings: Any) -> FallbackChain:
    """Assemble the default FallbackChain from ``settings``.

    Rebuilt on every call (``get_settings`` is an lru_cache singleton, so the rebuild
    cost is low) to stay patch-friendly.
    """
    router_cfg = settings.router
    llm = create_router_llm(settings.llm)
    selectors: list[RouteSelector] = [
        ForcedModeSelector(default_mode=router_cfg.mode),
        AttachmentSelector(),
        LLMIntentSelector(
            llm=llm,
            prompt_template=router_cfg.llm.prompt_template,
            model_name=settings.llm.model,
            enabled=router_cfg.llm.enabled,
        ),
        HeuristicSelector(rules=router_cfg.heuristic.rules, default=router_cfg.heuristic.default),
    ]
    return FallbackChain(selectors)


def route_query(ctx: RouteContext) -> RouteDecision:
    """Run routing and return the resulting ``RouteDecision``."""
    with trace_span("route"):
        chain = _build_chain(get_settings())
        decision = chain.select(ctx)
        if decision.kb_name is None:
            decision = RouteDecision(
                mode=decision.mode,
                selected=decision.selected,
                reason=decision.reason,
                kb_name=ctx.kb_name,
                selector=decision.selector,
            )
        try:
            ai_logger.info(
                "route",
                query=truncate(ctx.query, 512),
                mode=decision.mode,
                selected=decision.selected,
                reason=decision.reason,
                kb_name=decision.kb_name,
                selector=decision.selector,
            )
        except Exception:  # noqa: BLE001
            logger.debug("telemetry emit failed", exc_info=True)
        return decision


@dataclass
class _AttachmentContext:
    effective_query: str
    user_query: str
    attach_nodes: list[NodeWithScore]
    image_docs: list[ImageDocument]
    attach_step: dict[str, Any] | None
    has_image_attachment: bool
    image_bytes: bytes | None


class EagleRouterQueryEngine:
    """Routing query engine that combines text and visual retrievers."""

    def __init__(
        self,
        *,
        text_retriever: Any = None,
        visual_retriever: Any = None,
        mode: str | None = None,
        top_k: int = 5,
        kb_name: str | None = None,
    ) -> None:
        # Bind default retrievers to the instance's default namespace (G1 single-domain
        # deployment). Explicit retrievers passed by the caller are used as-is.
        try:
            from eagle_rag.plugins import get_plugin_manager

            default_ns = get_plugin_manager().default_namespace
        except Exception:  # noqa: BLE001
            default_ns = get_settings().plugins.default_namespace
        self.text_retriever = (
            text_retriever
            if text_retriever is not None
            else KnowhereGraphRetriever(top_k=top_k, kb_name=kb_name, plugin_namespace=default_ns)
        )
        self.visual_retriever = (
            visual_retriever
            if visual_retriever is not None
            else PixelRAGVisualRetriever(top_k=top_k, kb_name=kb_name, plugin_namespace=default_ns)
        )
        self.mode = mode or get_settings().router.mode
        self.top_k = top_k

    @staticmethod
    def _effective_query(query: str) -> tuple[str, str]:
        user_query = query or ""
        stripped = user_query.strip()
        if stripped:
            return stripped, user_query
        placeholder = get_settings().attachments.image_only_query
        return placeholder, user_query

    @staticmethod
    def _resolve_attachment_context(
        query: str,
        *,
        attachments: list[str] | None = None,
        query_image_bytes: bytes | None = None,
    ) -> _AttachmentContext:
        effective_query, user_query = EagleRouterQueryEngine._effective_query(query)
        attach_nodes: list[NodeWithScore] = []
        image_docs: list[ImageDocument] = []
        attach_step: dict[str, Any] | None = None
        image_bytes = query_image_bytes

        if attachments:
            parsed = parse_attachments(attachments)
            attach_nodes = [NodeWithScore(node=node, score=1.0) for node in parsed.text_nodes]
            image_docs = list(parsed.image_docs)
            if parsed.errors or parsed.parsed_count or parsed.cached_count or parsed.image_docs:
                attach_step = parsed.step_payload()
            if image_bytes is None:
                image_bytes = parsed.image_bytes
            if image_docs and image_bytes is None:
                first = image_docs[0]
                raw = getattr(first, "image", None)
                if isinstance(raw, bytes):
                    image_bytes = raw

        has_image = bool(image_bytes or image_docs)
        if query_image_bytes is not None:
            has_image = True
            if not image_docs:
                image_docs = [ImageDocument(image=query_image_bytes)]

        return _AttachmentContext(
            effective_query=effective_query,
            user_query=user_query,
            attach_nodes=attach_nodes,
            image_docs=image_docs,
            attach_step=attach_step,
            has_image_attachment=has_image,
            image_bytes=image_bytes,
        )

    @staticmethod
    def _resolve_scope_filter(
        scope_filter: dict[str, Any] | None,
        *,
        plugin_namespace: str | None = None,
    ) -> tuple[list[str], list[str], bool]:
        if not scope_filter:
            return [], [], False
        kb_names = list(scope_filter.get("kb_names") or [])
        document_ids = list(scope_filter.get("document_ids") or [])
        tags = list(scope_filter.get("tags") or [])
        if not (kb_names or document_ids or tags):
            return [], [], False
        doc_set: dict[str, None] = dict.fromkeys(document_ids)
        if tags:
            try:
                from eagle_rag.index.tag_catalog import resolve_tags_to_document_ids

                cap = get_settings().router.max_scope_documents
                for doc_id in resolve_tags_to_document_ids(
                    tags,
                    kb_names=kb_names or None,
                    cap=cap,
                    plugin_namespace=plugin_namespace,
                ):
                    doc_set.setdefault(doc_id, None)
            except Exception as exc:  # noqa: BLE001
                logger.warning("tag resolution failed; ignoring tag dimension: %s", exc)
        return kb_names, list(doc_set), True

    def _plan_query_route(
        self,
        route_query_text: str,
        *,
        route_mode: str,
        plugin_namespace: str,
        scope_kb_names: list[str],
        scope_doc_ids: list[str],
        scope_tags: tuple[str, ...],
        has_image: bool,
    ) -> tuple[Any, bool]:
        from eagle_rag.plugins import get_plugin_manager
        from eagle_rag.plugins.core_defaults import _default_classify_query
        from eagle_rag.plugins.hookbus import HookContext
        from eagle_rag.plugins.hooks import Hook
        from eagle_rag.plugins.scope_routing import apply_scope_aware_union

        manager = get_plugin_manager()
        hook_ctx = HookContext(
            plugin_namespace=plugin_namespace,
            extra={"route_mode": route_mode},
        )
        query_decision = manager.bus.invoke_first(
            Hook.CLASSIFY_QUERY,
            hook_ctx,
            route_query_text,
            has_image=has_image,
            route_mode=route_mode,
            scope_document_ids=tuple(scope_doc_ids) if scope_doc_ids else None,
            scope_kb_names=tuple(scope_kb_names) if scope_kb_names else None,
            scope_tags=scope_tags or None,
        )
        if query_decision is None:
            query_decision = _default_classify_query(
                hook_ctx,
                route_query_text,
                has_image=has_image,
                route_mode=route_mode,
            )
        return apply_scope_aware_union(
            query_decision,
            plugin_namespace=plugin_namespace,
            encoder_registry=manager.encoder_registry,
            top_k=self.top_k,
            scope_document_ids=tuple(scope_doc_ids) if scope_doc_ids else None,
            scope_kb_names=tuple(scope_kb_names) if scope_kb_names else None,
            scope_tags=scope_tags or None,
            audit=manager.audit,
        )

    def _route_step_payload(
        self,
        decision: RouteDecision,
        *,
        scope_filter: dict[str, Any] | None,
        user_query: str,
        has_image: bool,
    ) -> dict[str, Any]:
        from eagle_rag.plugins import get_plugin_manager

        manager = get_plugin_manager()
        plugin_namespace = manager.default_namespace
        route_mode = decision.mode
        if route_mode == "auto":
            if "text" in decision.selected and "visual" in decision.selected:
                route_mode = "hybrid"
            elif "visual" in decision.selected:
                route_mode = "visual"
            else:
                route_mode = "text"
        scope_kb_names, scope_doc_ids, _ = self._resolve_scope_filter(
            scope_filter,
            plugin_namespace=plugin_namespace,
        )
        scope_tags = tuple(scope_filter.get("tags") or []) if scope_filter else ()
        query_decision, scope_aware = self._plan_query_route(
            user_query,
            route_mode=route_mode,
            plugin_namespace=plugin_namespace,
            scope_kb_names=scope_kb_names,
            scope_doc_ids=scope_doc_ids,
            scope_tags=scope_tags,
            has_image=has_image,
        )
        collection_plans = [
            {"collection": p.collection, "encoder": p.encoder, "top_k": p.top_k}
            for p in query_decision.plans
        ]
        return {
            "name": "route",
            **decision.to_dict(),
            "collection_plans": collection_plans,
            "scope_aware_union": scope_aware,
        }

    def _route_decision(
        self,
        query: str,
        *,
        mode: str | None = None,
        scope: list[str] | None = None,
        kb_name: str | None = None,
        filters: dict[str, Any] | None = None,
        has_image_attachment: bool = False,
    ) -> RouteDecision:
        effective_mode = mode or self.mode
        if filters and filters.get("pipeline") in ("knowhere", "pixelrag"):
            effective_mode = "text" if filters["pipeline"] == "knowhere" else "visual"
        ctx = RouteContext(
            query=query,
            mode=effective_mode,
            scope=scope,
            kb_name=kb_name,
            has_image_attachment=has_image_attachment,
        )
        return route_query(ctx)

    def _fetch_nodes(
        self,
        query: str,
        decision: RouteDecision,
        *,
        scope: list[str] | None = None,
        kb_name: str | None = None,
        filters: dict[str, Any] | None = None,
        scope_filter: dict[str, Any] | None = None,
        query_image_bytes: bytes | None = None,
        user_query: str | None = None,
    ) -> list[NodeWithScore]:
        from eagle_rag.plugins import get_plugin_manager
        from eagle_rag.plugins.retriever_orchestrator import RetrieverOrchestrator

        manager = get_plugin_manager()
        plugin_namespace = manager.default_namespace

        from eagle_rag.plugins.hotpath_hooks import apply_query_assemble

        base_query = (user_query if user_query is not None else query) or ""
        route_query_text = apply_query_assemble(
            base_query,
            plugin_namespace=plugin_namespace,
            kb_name=kb_name,
        )
        # Keep ANN aligned with assembled user intent unless query is an explicit
        # distinct embed string (rare); empty query falls back to assembled text.
        if user_query is None or query == user_query or not (query or "").strip():
            ann_query = route_query_text
        else:
            ann_query = query
        visual_query_text = route_query_text if route_query_text.strip() else ""
        scope_kb_names, scope_doc_ids, use_scope_filter = self._resolve_scope_filter(
            scope_filter,
            plugin_namespace=plugin_namespace,
        )
        scope_tags = tuple(scope_filter.get("tags") or []) if scope_filter else ()

        route_mode = decision.mode
        if route_mode == "auto":
            if "text" in decision.selected and "visual" in decision.selected:
                route_mode = "hybrid"
            elif "visual" in decision.selected:
                route_mode = "visual"
            else:
                route_mode = "text"

        query_decision, _scope_aware = self._plan_query_route(
            route_query_text,
            route_mode=route_mode,
            plugin_namespace=plugin_namespace,
            scope_kb_names=scope_kb_names,
            scope_doc_ids=scope_doc_ids,
            scope_tags=scope_tags,
            has_image=bool(query_image_bytes),
        )

        orchestrator = RetrieverOrchestrator(
            plugin_manager=manager,
            text_retriever=self.text_retriever,
            visual_retriever=self.visual_retriever,
        )
        nodes = orchestrator.retrieve(
            ann_query,
            plugin_namespace=plugin_namespace,
            route_decision=query_decision,
            kb_name=kb_name,
            scope_filter=scope_filter,
            query_image_bytes=query_image_bytes,
            top_k=self.top_k,
            filters=filters,
            scope_kb_names=scope_kb_names,
            scope_doc_ids=scope_doc_ids,
            use_scope_filter=use_scope_filter,
            visual_query=visual_query_text,
        )

        if scope and not use_scope_filter:
            nodes = self._filter_by_scope(nodes, scope)
        return nodes

    def retrieve(
        self,
        query: str,
        *,
        mode: str | None = None,
        scope: list[str] | None = None,
        kb_name: str | None = None,
        filters: dict[str, Any] | None = None,
        scope_filter: dict[str, Any] | None = None,
        has_image_attachment: bool = False,
        query_image_bytes: bytes | None = None,
        user_query: str | None = None,
    ) -> tuple[list[NodeWithScore], RouteDecision]:
        route_input = user_query if user_query is not None else query
        decision = self._route_decision(
            route_input,
            mode=mode,
            scope=scope,
            kb_name=kb_name,
            filters=filters,
            has_image_attachment=has_image_attachment,
        )
        nodes = self._fetch_nodes(
            query,
            decision,
            scope=scope,
            kb_name=kb_name,
            filters=filters,
            scope_filter=scope_filter,
            query_image_bytes=query_image_bytes,
            user_query=route_input,
        )
        return nodes, decision

    @staticmethod
    def _map_nodes_to_search_payload(
        nodes: list[NodeWithScore],
        decision: RouteDecision,
        *,
        attach_step: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        text_nodes = [
            n for n in nodes if isinstance(n.node, TextNode) and not isinstance(n.node, ImageNode)
        ]
        image_nodes = [n for n in nodes if isinstance(n.node, ImageNode)]
        text_sources = [EagleMultimodalQueryEngine._text_source(n) for n in text_nodes]
        image_sources = [EagleMultimodalQueryEngine._image_source(n) for n in image_nodes]
        steps: list[dict[str, Any]] = [
            {"name": "route", **decision.to_dict()},
            {
                "name": "recall",
                "text_count": len(text_sources),
                "visual_count": len(image_sources),
            },
            {
                "name": "rerank",
                "model": "qwen3-rerank",
                "text_count": len(text_sources),
            },
        ]
        if attach_step:
            steps.append(attach_step)
        return {
            "sources": {"text": text_sources, "image": image_sources},
            "route": decision.to_dict(),
            "steps": steps,
        }

    def search(
        self,
        query: str,
        *,
        mode: str | None = None,
        scope: list[str] | None = None,
        kb_name: str | None = None,
        filters: dict[str, Any] | None = None,
        scope_filter: dict[str, Any] | None = None,
        attachments: list[str] | None = None,
        query_image_bytes: bytes | None = None,
    ) -> dict:
        ctx = self._resolve_attachment_context(
            query,
            attachments=attachments,
            query_image_bytes=query_image_bytes,
        )
        nodes, decision = self.retrieve(
            ctx.effective_query,
            mode=mode,
            scope=scope,
            kb_name=kb_name,
            filters=filters,
            scope_filter=scope_filter,
            has_image_attachment=ctx.has_image_attachment,
            query_image_bytes=ctx.image_bytes,
            user_query=ctx.user_query,
        )
        nodes = ctx.attach_nodes + nodes
        return self._map_nodes_to_search_payload(
            nodes,
            decision,
            attach_step=ctx.attach_step,
        )

    def search_stream(
        self,
        query: str,
        *,
        mode: str | None = None,
        scope: list[str] | None = None,
        kb_name: str | None = None,
        filters: dict[str, Any] | None = None,
        scope_filter: dict[str, Any] | None = None,
        attachments: list[str] | None = None,
        query_image_bytes: bytes | None = None,
    ) -> Iterator[dict[str, Any]]:
        ctx = self._resolve_attachment_context(
            query,
            attachments=attachments,
            query_image_bytes=query_image_bytes,
        )
        decision = self._route_decision(
            ctx.user_query,
            mode=mode,
            scope=scope,
            kb_name=kb_name,
            filters=filters,
            has_image_attachment=ctx.has_image_attachment,
        )
        yield {
            "event": "step",
            "data": self._route_step_payload(
                decision,
                scope_filter=scope_filter,
                user_query=ctx.user_query,
                has_image=ctx.has_image_attachment,
            ),
        }
        if ctx.attach_step:
            yield {"event": "step", "data": ctx.attach_step}
        nodes = self._fetch_nodes(
            ctx.effective_query,
            decision,
            scope=scope,
            kb_name=kb_name,
            filters=filters,
            scope_filter=scope_filter,
            query_image_bytes=ctx.image_bytes,
            user_query=ctx.user_query,
        )
        nodes = ctx.attach_nodes + nodes
        text_nodes = [
            n for n in nodes if isinstance(n.node, TextNode) and not isinstance(n.node, ImageNode)
        ]
        image_nodes = [n for n in nodes if isinstance(n.node, ImageNode)]
        yield {
            "event": "step",
            "data": {
                "name": "recall",
                "text_count": len(text_nodes),
                "visual_count": len(image_nodes),
            },
        }
        payload = self._map_nodes_to_search_payload(nodes, decision)
        yield {"event": "sources", "data": payload["sources"]}
        yield {"event": "done", "data": payload}

    def query(
        self,
        query: str,
        *,
        mode: str | None = None,
        scope: list[str] | None = None,
        kb_name: str | None = None,
        filters: dict[str, Any] | None = None,
        scope_filter: dict[str, Any] | None = None,
        attachments: list[str] | None = None,
        query_image_bytes: bytes | None = None,
    ) -> dict:
        ctx = self._resolve_attachment_context(
            query,
            attachments=attachments,
            query_image_bytes=query_image_bytes,
        )
        nodes, decision = self.retrieve(
            ctx.effective_query,
            mode=mode,
            scope=scope,
            kb_name=kb_name,
            filters=filters,
            scope_filter=scope_filter,
            has_image_attachment=ctx.has_image_attachment,
            query_image_bytes=ctx.image_bytes,
            user_query=ctx.user_query,
        )
        nodes = ctx.attach_nodes + nodes
        engine = EagleMultimodalQueryEngine()
        return engine.custom_query(
            ctx.effective_query,
            nodes=nodes,
            route_info=decision.to_dict(),
            attachment_image_docs=ctx.image_docs,
            attach_parse_step=ctx.attach_step,
        )

    def query_stream(
        self,
        query: str,
        *,
        mode: str | None = None,
        scope: list[str] | None = None,
        kb_name: str | None = None,
        filters: dict[str, Any] | None = None,
        scope_filter: dict[str, Any] | None = None,
        attachments: list[str] | None = None,
        query_image_bytes: bytes | None = None,
        session_id: str | None = None,
        user_message_id: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        if session_id:
            yield {
                "event": "session",
                "data": {
                    "session_id": session_id,
                    "user_message_id": user_message_id or str(uuid4()),
                },
            }

        ctx = self._resolve_attachment_context(
            query,
            attachments=attachments,
            query_image_bytes=query_image_bytes,
        )
        decision = self._route_decision(
            ctx.user_query,
            mode=mode,
            scope=scope,
            kb_name=kb_name,
            filters=filters,
            has_image_attachment=ctx.has_image_attachment,
        )
        yield {
            "event": "step",
            "data": self._route_step_payload(
                decision,
                scope_filter=scope_filter,
                user_query=ctx.user_query,
                has_image=ctx.has_image_attachment,
            ),
        }
        nodes = self._fetch_nodes(
            ctx.effective_query,
            decision,
            scope=scope,
            kb_name=kb_name,
            filters=filters,
            scope_filter=scope_filter,
            query_image_bytes=ctx.image_bytes,
            user_query=ctx.user_query,
        )
        text_nodes = [
            n for n in nodes if isinstance(n.node, TextNode) and not isinstance(n.node, ImageNode)
        ]
        image_nodes = [n for n in nodes if isinstance(n.node, ImageNode)]
        yield {
            "event": "step",
            "data": {
                "name": "recall",
                "text_count": len(text_nodes),
                "visual_count": len(image_nodes),
            },
        }

        nodes = ctx.attach_nodes + nodes
        if ctx.attach_step:
            yield {"event": "step", "data": ctx.attach_step}

        engine = EagleMultimodalQueryEngine()
        yield from engine.stream_custom_query(
            ctx.effective_query,
            nodes=nodes,
            route_info=decision.to_dict(),
            attachment_image_docs=ctx.image_docs,
            attach_parse_step=ctx.attach_step,
        )

    @staticmethod
    def _filter_by_scope(nodes: list[NodeWithScore], scope: list[str]) -> list[NodeWithScore]:
        scope_set = set(scope)
        return [nws for nws in nodes if (nws.node.metadata or {}).get("document_id") in scope_set]
