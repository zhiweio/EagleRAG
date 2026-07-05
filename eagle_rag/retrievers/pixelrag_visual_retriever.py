"""PixelRAG visual retriever (Phase 4.2).

Wraps LlamaIndex ``BaseRetriever``, retrieving visual tiles from the Milvus
visual collection (``eagle_visual``, backed by Milvus built-in HNSW/DiskANN)
and returning ``ImageNode`` carrying ``image_path``/``image_id``.

Architecture:

- PixelRAG is reduced to a "visual encoder + slicer" library call; it no longer
  runs as a standalone ``pixelrag serve``. Visual vector storage and retrieval
  are handled entirely by Milvus.
- Retrieval flow: ``embed_query`` encodes the query text into a visual vector
  (pixelrag_embed, dim 2048) -> ``search_visual`` queries Milvus directly
  (HNSW/DiskANN + scalar filtering).
- Supports ``kb_name`` multi-tenant isolation and ``year``/``source_type``
  mixed-retrieval filtering.
- On any exception from ``embed_query``/``search_visual`` returns ``[]``; the
  router decides the fallback strategy.
"""

from __future__ import annotations

import time
from typing import Any

from llama_index.core.retrievers import BaseRetriever
from llama_index.core.schema import ImageNode, NodeWithScore, QueryBundle
from opentelemetry.trace import StatusCode

from eagle_rag.index.milvus_visual_store import search_visual
from eagle_rag.ingest.pixelrag_adapter import embed_query
from eagle_rag.telemetry import get_ai_logger, get_logger, trace_span, truncate

__all__ = ["PixelRAGVisualRetriever"]

logger = get_logger(__name__)
ai_logger = get_ai_logger(__name__)


def _truncate_hits_visual(results: list[dict]) -> list[dict]:
    """Summarize image_id/document_id/score for the first 5 visual results, for AI telemetry."""
    out: list[dict] = []
    for r in results[:5]:
        out.append(
            {
                "image_id": r.get("image_id"),
                "document_id": r.get("document_id"),
                "score": r.get("score"),
            }
        )
    return out


class PixelRAGVisualRetriever(BaseRetriever):
    """Visual retrieval: ``embed_query`` encoding + ``search_visual`` direct Milvus query."""

    def __init__(
        self,
        *,
        top_k: int = 5,
        document_id: str | None = None,
        kb_name: str | None = None,
        kb_names: list[str] | None = None,
        document_ids: list[str] | None = None,
        year: int | list[int] | None = None,
        source_type: str | None = None,
        parent_section: str | None = None,
        chunk_type: str | None = None,
    ) -> None:
        super().__init__()
        self.top_k = top_k
        self.document_id = document_id
        self.kb_name = kb_name
        # Advanced scope filter (union OR): (kb_name IN kb_names) OR
        # (document_id IN document_ids); takes precedence over single kb_name.
        self.kb_names = kb_names or []
        self.document_ids = document_ids or []
        self.year = year
        self.source_type = source_type
        self.parent_section = parent_section
        self.chunk_type = chunk_type

    def _retrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]:
        query_str = query_bundle.query_str
        t0 = time.monotonic()
        with trace_span("retrieve.visual") as span:
            try:
                query_vector = embed_query(query_str)
                results = search_visual(
                    query_vector,
                    top_k=self.top_k,
                    document_id=self.document_id,
                    kb_name=self.kb_name,
                    kb_names=self.kb_names or None,
                    document_ids=self.document_ids or None,
                    year=self.year,
                    source_type=self.source_type,
                    parent_section=self.parent_section,
                    chunk_type=self.chunk_type,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("visual retrieval failed; returning empty list: %s", exc)
                if span:
                    span.set_status(StatusCode.ERROR)
                    span.record_exception(exc)
                try:
                    ai_logger.info(
                        "retrieve",
                        retriever="visual",
                        query=truncate(query_str, 512),
                        top_k=self.top_k,
                        kb_name=self.kb_name,
                        hits=[],
                        error=truncate(str(exc), 256),
                        latency_ms=int((time.monotonic() - t0) * 1000),
                    )
                except Exception:  # noqa: BLE001
                    logger.debug("telemetry emit failed", exc_info=True)
                return []
            nodes = [self._to_node_with_score(r) for r in results]
            try:
                ai_logger.info(
                    "retrieve",
                    retriever="visual",
                    query=truncate(query_str, 512),
                    top_k=self.top_k,
                    kb_name=self.kb_name,
                    hits=_truncate_hits_visual(results),
                    latency_ms=int((time.monotonic() - t0) * 1000),
                )
            except Exception:  # noqa: BLE001
                logger.debug("telemetry emit failed", exc_info=True)
            return nodes

    @staticmethod
    def _to_node_with_score(result: dict[str, Any]) -> NodeWithScore:
        image_path = result.get("image_path") or result.get("url")
        image_url = result.get("url") or image_path
        metadata = {
            "image_id": result.get("image_id"),
            "document_id": result.get("document_id"),
            "page": result.get("page"),
            "position": result.get("position"),
            "kb_name": result.get("kb_name"),
            "year": result.get("year"),
            "source_type": result.get("source_type"),
            "chunk_type": result.get("chunk_type"),
            "parent_section": result.get("parent_section"),
            "content_summary": result.get("content_summary"),
            "source_chunk_id": result.get("source_chunk_id"),
        }
        node = ImageNode(
            image_url=image_url,
            image_path=image_path,
            metadata=metadata,
        )
        score = result.get("score")
        if score is None:
            score = 1.0
        try:
            score = float(score)
        except (TypeError, ValueError):
            score = 1.0
        return NodeWithScore(node=node, score=score)

    def retrieve(self, query_str: str) -> list[NodeWithScore]:  # type: ignore[override]
        """Convenience sync entry: build a ``QueryBundle`` and call ``_retrieve``."""
        return self._retrieve(QueryBundle(query_str))
