"""PixelRAG visual retriever (Phase 4.2).

Wraps LlamaIndex ``BaseRetriever``, retrieving visual tiles from the Milvus
visual collection (``eagle_visual``, backed by Milvus built-in HNSW/DiskANN)
and returning ``ImageNode`` carrying ``image_path``/``image_id``.

Architecture:

- PixelRAG is reduced to a "visual encoder + slicer" library call; it no longer
  runs as a standalone ``pixelrag serve``. Visual vector storage and retrieval
  are handled entirely by Milvus.
- Retrieval flow: ``embed_query`` / ``embed_image_bytes`` encode the query into
  a visual vector (pixelrag_embed, dim 2048) -> ``search_visual`` queries Milvus
  directly (HNSW/DiskANN + scalar filtering).
- When both text and an image query are present, results are merged by visual
  hit id with max score.
- Supports ``kb_name`` multi-tenant isolation and ``year``/``source_type``
  mixed-retrieval filtering.
- On any exception from embedding/search returns ``[]``; the router decides the
  fallback strategy.
"""

from __future__ import annotations

import time
from typing import Any

from llama_index.core.retrievers import BaseRetriever
from llama_index.core.schema import ImageNode, NodeWithScore, QueryBundle
from opentelemetry.trace import StatusCode

from eagle_rag.config import get_settings
from eagle_rag.index.milvus_visual_store import search_visual
from eagle_rag.ingest.pixelrag_adapter import embed_image_bytes, embed_query
from eagle_rag.telemetry import get_ai_logger, get_logger, trace_span, truncate

__all__ = ["PixelRAGVisualRetriever", "merge_visual_hits", "visual_hit_key"]

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


def visual_hit_key(result: dict[str, Any]) -> str:
    """Stable merge key for a Milvus visual hit."""
    image_id = result.get("image_id")
    if image_id:
        return str(image_id)
    document_id = result.get("document_id") or ""
    page = result.get("page")
    position = result.get("position") or ""
    return f"{document_id}:{page}:{position}"


def merge_visual_hits(
    *hit_lists: list[dict[str, Any]],
    top_k: int,
) -> list[dict[str, Any]]:
    """Merge multiple visual search result lists, keeping max score per hit key."""
    merged: dict[str, dict[str, Any]] = {}
    for hits in hit_lists:
        for hit in hits:
            key = visual_hit_key(hit)
            existing = merged.get(key)
            if existing is None:
                merged[key] = dict(hit)
                continue
            try:
                new_score = float(hit.get("score") or 0.0)
                old_score = float(existing.get("score") or 0.0)
            except (TypeError, ValueError):
                new_score = 0.0
                old_score = 0.0
            if new_score > old_score:
                merged[key] = dict(hit)
    ordered = sorted(
        merged.values(),
        key=lambda r: float(r.get("score") or 0.0),
        reverse=True,
    )
    return ordered[:top_k]


class PixelRAGVisualRetriever(BaseRetriever):
    """Visual retrieval: text/image embedding + ``search_visual`` Milvus query."""

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
        self.kb_names = kb_names or []
        self.document_ids = document_ids or []
        self.year = year
        self.source_type = source_type
        self.parent_section = parent_section
        self.chunk_type = chunk_type

    def _search_params(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "kb_name": self.kb_name,
            "kb_names": self.kb_names or None,
            "document_ids": self.document_ids or None,
            "year": self.year,
            "source_type": self.source_type,
            "parent_section": self.parent_section,
            "chunk_type": self.chunk_type,
        }

    def _fetch_k(self) -> int:
        multiplier = get_settings().attachments.visual_merge_fetch_multiplier
        return max(self.top_k, self.top_k * max(multiplier, 1))

    def _search_with_vector(
        self,
        query_vector: list[float],
        *,
        fetch_k: int,
    ) -> list[dict[str, Any]]:
        return search_visual(query_vector, top_k=fetch_k, **self._search_params())

    def _retrieve_visual_hits(
        self,
        query_str: str,
        *,
        query_image_bytes: bytes | None = None,
    ) -> list[dict[str, Any]]:
        fetch_k = self._fetch_k()
        hit_lists: list[list[dict[str, Any]]] = []
        if query_image_bytes:
            hit_lists.append(
                self._search_with_vector(embed_image_bytes(query_image_bytes), fetch_k=fetch_k)
            )
        if query_str.strip():
            hit_lists.append(self._search_with_vector(embed_query(query_str), fetch_k=fetch_k))
        if not hit_lists:
            return []
        if len(hit_lists) == 1:
            return hit_lists[0][: self.top_k]
        return merge_visual_hits(*hit_lists, top_k=self.top_k)

    def _retrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]:
        query_str = query_bundle.query_str
        query_image_bytes = getattr(query_bundle, "query_image_bytes", None)
        t0 = time.monotonic()
        with trace_span("retrieve.visual") as span:
            try:
                results = self._retrieve_visual_hits(
                    query_str,
                    query_image_bytes=query_image_bytes,
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

    def retrieve(
        self,
        query_str: str,
        *,
        query_image_bytes: bytes | None = None,
    ) -> list[NodeWithScore]:  # type: ignore[override]
        """Convenience sync entry with optional image-query bytes."""
        bundle = QueryBundle(query_str)
        if query_image_bytes is not None:
            bundle.query_image_bytes = query_image_bytes  # type: ignore[attr-defined]
        return self._retrieve(bundle)
