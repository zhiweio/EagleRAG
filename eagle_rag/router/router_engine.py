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
from typing import Any
from uuid import uuid4

from llama_index.core.schema import ImageNode, NodeWithScore, TextNode

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
        # kb_name fallback: default to ctx.kb_name when selectors left it unset.
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
        self.text_retriever = (
            text_retriever
            if text_retriever is not None
            else KnowhereGraphRetriever(top_k=top_k, kb_name=kb_name)
        )
        self.visual_retriever = (
            visual_retriever
            if visual_retriever is not None
            else PixelRAGVisualRetriever(top_k=top_k, kb_name=kb_name)
        )
        self.mode = mode or get_settings().router.mode
        self.top_k = top_k

    @staticmethod
    def _resolve_scope_filter(
        scope_filter: dict[str, Any] | None,
    ) -> tuple[list[str], list[str], bool]:
        """Expand the advanced scope filter into ``(kb_names, document_ids, active)``.

        Folds the selected tags into the document set by resolving them to the
        documents that contain those keywords (union semantics; tags resolve
        across all knowledge bases). ``active`` is False when nothing is selected,
        in which case the legacy single ``kb_name`` / ``scope`` path is used.
        """
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
                for doc_id in resolve_tags_to_document_ids(tags, cap=cap):
                    doc_set.setdefault(doc_id, None)
            except Exception as exc:  # noqa: BLE001
                logger.warning("tag resolution failed; ignoring tag dimension: %s", exc)
        return kb_names, list(doc_set), True

    def _route_decision(
        self,
        query: str,
        *,
        mode: str | None = None,
        scope: list[str] | None = None,
        kb_name: str | None = None,
        filters: dict[str, Any] | None = None,
        has_doc_attachments: bool = False,
    ) -> RouteDecision:
        """Run routing only (fast); retrieval may follow in :meth:`_fetch_nodes`."""
        effective_mode = mode or self.mode
        if filters and filters.get("pipeline") in ("knowhere", "pixelrag"):
            effective_mode = "text" if filters["pipeline"] == "knowhere" else "visual"
        ctx = RouteContext(
            query=query,
            mode=effective_mode,
            scope=scope,
            kb_name=kb_name,
            has_doc_attachments=has_doc_attachments,
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
    ) -> list[NodeWithScore]:
        """Retrieve nodes for a precomputed routing decision."""
        selected = decision.selected
        source_type = filters.get("source_type") if filters else None
        year = filters.get("year") if filters else None

        scope_kb_names, scope_doc_ids, use_scope_filter = self._resolve_scope_filter(scope_filter)
        has_facet_filters = bool(filters and any(v is not None for v in filters.values()))

        if use_scope_filter:
            text_retriever = KnowhereGraphRetriever(
                top_k=self.top_k,
                kb_names=scope_kb_names,
                document_ids=scope_doc_ids,
                source_type=source_type,
                year=year,
            )
            visual_retriever = PixelRAGVisualRetriever(
                top_k=self.top_k,
                kb_names=scope_kb_names,
                document_ids=scope_doc_ids,
                source_type=source_type,
                year=year,
            )
        elif has_facet_filters or kb_name:
            text_retriever = KnowhereGraphRetriever(
                top_k=self.top_k,
                kb_name=kb_name,
                source_type=source_type,
                year=year,
            )
            visual_retriever = PixelRAGVisualRetriever(
                top_k=self.top_k,
                kb_name=kb_name,
                source_type=source_type,
                year=year,
            )
        else:
            text_retriever = self.text_retriever
            visual_retriever = self.visual_retriever

        nodes: list[NodeWithScore] = []
        if "text" in selected:
            try:
                with trace_span("retrieve.text"):
                    nodes.extend(text_retriever.retrieve(query) or [])
            except Exception as exc:  # noqa: BLE001
                logger.warning("text retriever call failed; skipping: %s", exc)
        if "visual" in selected:
            try:
                with trace_span("retrieve.visual"):
                    nodes.extend(visual_retriever.retrieve(query) or [])
            except Exception as exc:  # noqa: BLE001
                logger.warning("visual retriever call failed; skipping: %s", exc)

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
        has_doc_attachments: bool = False,
    ) -> tuple[list[NodeWithScore], RouteDecision]:
        """Route then retrieve, returning ``(nodes, route_decision)``."""
        decision = self._route_decision(
            query,
            mode=mode,
            scope=scope,
            kb_name=kb_name,
            filters=filters,
            has_doc_attachments=has_doc_attachments,
        )
        nodes = self._fetch_nodes(
            query,
            decision,
            scope=scope,
            kb_name=kb_name,
            filters=filters,
            scope_filter=scope_filter,
        )
        return nodes, decision

    @staticmethod
    def _prepare_attachments(
        attachments: list[str] | None,
    ) -> tuple[list[NodeWithScore], Any, dict[str, Any] | None, bool]:
        if not attachments:
            return [], None, None, False
        parsed = parse_attachments(attachments)
        attach_nodes = [NodeWithScore(node=node, score=1.0) for node in parsed.text_nodes]
        return attach_nodes, parsed.image_docs, parsed.step_payload(), parsed.has_doc_attachments

    @staticmethod
    def _map_nodes_to_search_payload(
        nodes: list[NodeWithScore],
        decision: RouteDecision,
    ) -> dict[str, Any]:
        """Map retrieved nodes to the pure-search response shape."""
        text_nodes = [
            n for n in nodes if isinstance(n.node, TextNode) and not isinstance(n.node, ImageNode)
        ]
        image_nodes = [n for n in nodes if isinstance(n.node, ImageNode)]
        text_sources = [EagleMultimodalQueryEngine._text_source(n) for n in text_nodes]
        image_sources = [EagleMultimodalQueryEngine._image_source(n) for n in image_nodes]
        return {
            "sources": {"text": text_sources, "image": image_sources},
            "route": decision.to_dict(),
            "steps": [
                {"name": "route", **decision.to_dict()},
                {
                    "name": "recall",
                    "text_count": len(text_sources),
                    "visual_count": len(image_sources),
                },
            ],
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
    ) -> dict:
        """Pure retrieval: route → retrieve → map to sources. No LLM generation.

        Accepts the same ``filters`` (facet) and ``scope_filter`` (kb/doc/tag
        union) as :meth:`query`, so pure retrieval has full parity with the
        generative path.
        """
        nodes, decision = self.retrieve(
            query,
            mode=mode,
            scope=scope,
            kb_name=kb_name,
            filters=filters,
            scope_filter=scope_filter,
        )
        return self._map_nodes_to_search_payload(nodes, decision)

    def search_stream(
        self,
        query: str,
        *,
        mode: str | None = None,
        scope: list[str] | None = None,
        kb_name: str | None = None,
        filters: dict[str, Any] | None = None,
        scope_filter: dict[str, Any] | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Streaming pure retrieval: yields SSE event dicts (step | sources | done | error)."""
        decision = self._route_decision(
            query,
            mode=mode,
            scope=scope,
            kb_name=kb_name,
            filters=filters,
        )
        yield {"event": "step", "data": {"name": "route", **decision.to_dict()}}
        nodes = self._fetch_nodes(
            query,
            decision,
            scope=scope,
            kb_name=kb_name,
            filters=filters,
            scope_filter=scope_filter,
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
    ) -> dict:
        attach_nodes, image_docs, attach_step, has_doc = self._prepare_attachments(attachments)
        nodes, decision = self.retrieve(
            query,
            mode=mode,
            scope=scope,
            kb_name=kb_name,
            filters=filters,
            scope_filter=scope_filter,
            has_doc_attachments=has_doc,
        )
        nodes = attach_nodes + nodes
        engine = EagleMultimodalQueryEngine()
        return engine.custom_query(
            query,
            nodes=nodes,
            route_info=decision.to_dict(),
            attachment_image_docs=image_docs,
            attach_parse_step=attach_step,
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
        session_id: str | None = None,
        user_message_id: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Streaming Q&A: yields SSE event dicts (with event/data keys)."""
        if session_id:
            yield {
                "event": "session",
                "data": {
                    "session_id": session_id,
                    "user_message_id": user_message_id or str(uuid4()),
                },
            }

        attach_nodes, image_docs, attach_step, has_doc = self._prepare_attachments(attachments)
        decision = self._route_decision(
            query,
            mode=mode,
            scope=scope,
            kb_name=kb_name,
            filters=filters,
            has_doc_attachments=has_doc,
        )
        yield {"event": "step", "data": {"name": "route", **decision.to_dict()}}
        nodes = self._fetch_nodes(
            query,
            decision,
            scope=scope,
            kb_name=kb_name,
            filters=filters,
            scope_filter=scope_filter,
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

        nodes = attach_nodes + nodes
        if attach_step:
            yield {"event": "step", "data": attach_step}

        engine = EagleMultimodalQueryEngine()
        yield from engine.stream_custom_query(
            query,
            nodes=nodes,
            route_info=decision.to_dict(),
            attachment_image_docs=image_docs,
            attach_parse_step=attach_step,
        )

    @staticmethod
    def _filter_by_scope(nodes: list[NodeWithScore], scope: list[str]) -> list[NodeWithScore]:
        scope_set = set(scope)
        return [nws for nws in nodes if (nws.node.metadata or {}).get("document_id") in scope_set]
