"""Knowhere text + graph-expansion retriever (Phase 4.1).

Wraps LlamaIndex ``BaseRetriever``, combining Milvus text-vector retrieval with
``connect_to``-based graph expansion. Returns ``TextNode`` carrying hierarchy
metadata (path/level/summary/connect_to/document_id/source_type).

Multi-tenant isolation via ``kb_name``: when set, ``MetadataFilters`` are pushed
down to the vector store to scope retrieval to a single knowledge base; when
``None``, retrieval spans tenants (used for global debugging/ops).

Retrieval flow:

1. ``get_text_index()`` returns the text ``VectorStoreIndex`` (lazy, with embed_model).
2. ``text_index.as_retriever(similarity_top_k=..., filters=...)`` builds a retriever;
   ``retrieve(query_str)`` returns Top-K ``NodeWithScore``. When ``kb_name`` is set,
   ``filters`` carries the ``kb_name == self.kb_name`` scalar predicate.
3. If ``document_id`` is given, filter client-side on ``metadata.document_id``.
4. **Graph expansion**: for each returned TextNode, read ``metadata["connect_to"]``
   (list of chunk_ids) and fetch related nodes via
   ``text_index.docstore.get_node(target_id, raise_error=False)``, dedup and append.
   Silently skip when docstore is unavailable or target is missing.
5. Return the merged, deduped ``list[NodeWithScore]``.

If the underlying Milvus/embedding is unavailable, the exception is caught and
``[]`` returned; the router decides the fallback strategy. The convenience sync
``retrieve(query_str)`` builds a ``QueryBundle`` and calls ``_retrieve`` directly,
bypassing BaseRetriever's callback/dispatcher wrapping for tests and lightweight use.
"""

from __future__ import annotations

import time
from typing import Any

from llama_index.core.retrievers import BaseRetriever
from llama_index.core.schema import NodeWithScore, QueryBundle
from llama_index.core.vector_stores import (
    FilterCondition,
    FilterOperator,
    MetadataFilter,
    MetadataFilters,
)
from opentelemetry.trace import StatusCode

from eagle_rag.index.milvus_text_store import get_text_index
from eagle_rag.telemetry import get_ai_logger, get_logger, trace_span, truncate

__all__ = ["KnowhereGraphRetriever"]

logger = get_logger(__name__)
ai_logger = get_ai_logger(__name__)


def _truncate_hits_text(nodes: list[NodeWithScore]) -> list[dict]:
    """Summarize path/document_id/score for the first 5 nodes, for AI event telemetry."""
    out: list[dict] = []
    for nws in nodes[:5]:
        meta = nws.node.metadata or {}
        out.append(
            {
                "path": meta.get("path"),
                "document_id": meta.get("document_id"),
                "score": nws.score,
            }
        )
    return out


class KnowhereGraphRetriever(BaseRetriever):
    """Text-vector retrieval + ``connect_to`` graph expansion with ``kb_name`` tenant filter."""

    def __init__(
        self,
        *,
        top_k: int = 5,
        similarity_top_k: int | None = None,
        document_id: str | None = None,
        embed_model: Any = None,
        kb_name: str | None = None,
        kb_names: list[str] | None = None,
        document_ids: list[str] | None = None,
        source_type: str | None = None,
        year: int | None = None,
    ) -> None:
        super().__init__()
        self.top_k = top_k
        # similarity_top_k is kept for backward compat; falls back to top_k.
        self.similarity_top_k = similarity_top_k or top_k
        self.document_id = document_id
        # embed_model is not used directly here (vector retrieval uses the embed_model
        # inside text_index); kept for future extension (e.g. custom query embedding).
        self.embed_model = embed_model
        # kb_name multi-tenant filter: when non-None, pushed down to the vector store
        # via MetadataFilters; when None, retrieval spans tenants.
        self.kb_name = kb_name
        # Advanced scope filter (union OR): when either list is non-empty, retrieval
        # is scoped to (kb_name IN kb_names) OR (document_id IN document_ids), pushed
        # down to Milvus. Takes precedence over the single ``kb_name`` filter.
        self.kb_names = kb_names or []
        self.document_ids = document_ids or []
        self.source_type = source_type
        self.year = year

    def _build_filters(self) -> MetadataFilters | None:
        """Assemble Milvus scalar filters (union scope AND facet filters)."""
        filter_list: list[MetadataFilter | MetadataFilters] = []
        if self.kb_names or self.document_ids:
            # Union (OR) of selected knowledge bases and documents.
            scope_filters: list[MetadataFilter | MetadataFilters] = []
            if self.kb_names:
                scope_filters.append(
                    MetadataFilter(key="kb_name", value=self.kb_names, operator=FilterOperator.IN)
                )
            if self.document_ids:
                scope_filters.append(
                    MetadataFilter(
                        key="document_id", value=self.document_ids, operator=FilterOperator.IN
                    )
                )
            if len(scope_filters) == 1:
                filter_list.append(scope_filters[0])
            else:
                filter_list.append(
                    MetadataFilters(filters=scope_filters, condition=FilterCondition.OR)
                )
        elif self.kb_name is not None:
            filter_list.append(
                MetadataFilter(key="kb_name", value=self.kb_name, operator=FilterOperator.EQ)
            )
        if self.source_type is not None:
            filter_list.append(
                MetadataFilter(
                    key="source_type", value=self.source_type, operator=FilterOperator.EQ
                )
            )
        if self.year is not None:
            filter_list.append(
                MetadataFilter(key="year", value=self.year, operator=FilterOperator.EQ)
            )
        if not filter_list:
            return None
        return MetadataFilters(filters=filter_list, condition=FilterCondition.AND)

    def _retrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]:
        query_str = query_bundle.query_str
        t0 = time.monotonic()
        with trace_span("retrieve.text") as span:
            try:
                text_index = get_text_index()
                filters = self._build_filters()
                if filters is not None:
                    retriever = text_index.as_retriever(
                        similarity_top_k=self.similarity_top_k,
                        filters=filters,
                    )
                else:
                    retriever = text_index.as_retriever(similarity_top_k=self.similarity_top_k)
                raw_nodes: list[NodeWithScore] = retriever.retrieve(query_str)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Knowhere text retrieval failed; returning empty list: %s", exc)
                if span:
                    span.set_status(StatusCode.ERROR)
                    span.record_exception(exc)
                try:
                    ai_logger.info(
                        "retrieve",
                        retriever="text",
                        query=truncate(query_str, 512),
                        kb_name=self.kb_name,
                        hits=[],
                        error=truncate(str(exc), 256),
                        latency_ms=int((time.monotonic() - t0) * 1000),
                    )
                except Exception:  # noqa: BLE001
                    logger.debug("telemetry emit failed", exc_info=True)
                return []

            # Client-side document_id filter (match metadata.document_id).
            if self.document_id:
                raw_nodes = [
                    nws
                    for nws in raw_nodes
                    if (nws.node.metadata or {}).get("document_id") == self.document_id
                ]

            expanded: list[NodeWithScore] = list(raw_nodes)
            seen_ids: set[str] = {nws.node.node_id for nws in raw_nodes if nws.node.node_id}

            # Graph expansion: fetch related nodes via connect_to.
            # Silently skip if docstore is inaccessible.
            try:
                docstore = text_index.docstore
            except Exception:  # noqa: BLE001
                docstore = None

            if docstore is not None:
                for nws in raw_nodes:
                    meta = nws.node.metadata or {}
                    connect_to = meta.get("connect_to") or []
                    if isinstance(connect_to, str):
                        connect_to = [connect_to]
                    for target_id in connect_to:
                        # connect_to items may be dicts ({target, relation, ref, position})
                        # or plain id strings; normalise to the id string.
                        if isinstance(target_id, dict):
                            target_id = target_id.get("target")
                        if not target_id or target_id in seen_ids:
                            continue
                        try:
                            related = docstore.get_node(target_id, raise_error=False)
                        except Exception:  # noqa: BLE001
                            related = None
                        if related is None:
                            continue
                        expanded.append(NodeWithScore(node=related, score=nws.score))
                        seen_ids.add(target_id)

            try:
                ai_logger.info(
                    "retrieve",
                    retriever="text",
                    query=truncate(query_str, 512),
                    top_k=self.similarity_top_k,
                    kb_name=self.kb_name,
                    hits=_truncate_hits_text(expanded),
                    expanded_count=len(expanded) - len(raw_nodes),
                    latency_ms=int((time.monotonic() - t0) * 1000),
                )
            except Exception:  # noqa: BLE001
                logger.debug("telemetry emit failed", exc_info=True)
            return expanded

    def retrieve(self, query_str: str) -> list[NodeWithScore]:  # type: ignore[override]
        """Convenience sync entry: build a ``QueryBundle`` and call ``_retrieve``."""
        return self._retrieve(QueryBundle(query_str))
