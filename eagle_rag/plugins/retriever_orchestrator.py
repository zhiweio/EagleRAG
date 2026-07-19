"""Multi-collection retrieval orchestration (M3.5)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from llama_index.core.schema import ImageNode, NodeWithScore, TextNode

from eagle_rag.config import get_settings
from eagle_rag.index.milvus_pool import get_milvus_pool
from eagle_rag.plugins.hookbus import HookContext
from eagle_rag.plugins.hooks import Hook
from eagle_rag.plugins.milvus_ns import milvus_db_name
from eagle_rag.plugins.routing import CollectionQueryPlan, QueryRouteDecision
from eagle_rag.retrievers.knowhere_graph_retriever import KnowhereGraphRetriever
from eagle_rag.retrievers.pixelrag_visual_retriever import PixelRAGVisualRetriever
from eagle_rag.router.rerank_fusion import (
    dedupe_cross_collection,
    merge_rrf,
    rerank_merged,
)
from eagle_rag.telemetry import get_logger, trace_span

if TYPE_CHECKING:
    from eagle_rag.plugins.manager import PluginManager

__all__ = ["RetrieverOrchestrator"]

logger = get_logger(__name__)

_TEXT_OUTPUT_FIELDS = [
    "text",
    "path",
    "document_id",
    "kb_name",
    "source_type",
    "year",
    "type",
    "source_chunk_id",
    "chunk_type",
    "parent_section",
]
_VISUAL_OUTPUT_FIELDS = [
    "image_id",
    "image_path",
    "document_id",
    "page",
    "position",
    "kb_name",
    "year",
    "source_type",
    "chunk_type",
    "parent_section",
    "content_summary",
    "source_chunk_id",
]


class RetrieverOrchestrator:
    """Execute multi-collection ANN per ``QueryRouteDecision``."""

    def __init__(
        self,
        *,
        plugin_manager: PluginManager | None = None,
        text_retriever: Any = None,
        visual_retriever: Any = None,
    ) -> None:
        if plugin_manager is None:
            from eagle_rag.plugins import get_plugin_manager

            plugin_manager = get_plugin_manager()
        self._manager = plugin_manager
        self._text_retriever = text_retriever
        self._visual_retriever = visual_retriever

    def retrieve(
        self,
        query: str,
        *,
        plugin_namespace: str,
        route_decision: QueryRouteDecision,
        kb_name: str | None = None,
        scope_filter: dict[str, Any] | None = None,
        query_image_bytes: bytes | None = None,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
        scope_kb_names: list[str] | None = None,
        scope_doc_ids: list[str] | None = None,
        use_scope_filter: bool = False,
        visual_query: str | None = None,
    ) -> list[NodeWithScore]:
        settings = get_settings()
        source_type = filters.get("source_type") if filters else None
        year = filters.get("year") if filters else None
        recall_top_k = settings.router.recall_top_k
        final_top_k = top_k or settings.router.final_top_k
        plan_results: list[list[NodeWithScore]] = []
        visual_query_text = visual_query if visual_query is not None else query
        retrieval_hints = dict(route_decision.retrieval_hints or {})

        hook_ctx = HookContext(
            plugin_namespace=plugin_namespace,
            extra={"kb_name": kb_name},
        )
        expanded = self._manager.bus.invoke_first(
            Hook.QUERY_DENSE_EXPAND,
            hook_ctx,
            query,
            encoder=None,
        )
        if expanded is not None:
            if expanded.intent is not None:
                hook_ctx.extra["retrieval_intent"] = expanded.intent
            if expanded.sparse_terms:
                hook_ctx.extra["sparse_terms"] = list(expanded.sparse_terms)
        retrieval_hints["retrieval_intent"] = hook_ctx.extra.get("retrieval_intent")
        if hook_ctx.extra.get("sparse_terms"):
            retrieval_hints["sparse_terms"] = hook_ctx.extra["sparse_terms"]

        for plan in route_decision.plans:
            plan_top_k = plan.top_k or recall_top_k
            try:
                with trace_span(f"retrieve.{plan.collection}"):
                    nodes = self._retrieve_plan(
                        plan,
                        query,
                        kb_name=kb_name,
                        source_type=source_type,
                        year=year,
                        scope_kb_names=scope_kb_names,
                        scope_doc_ids=scope_doc_ids,
                        use_scope_filter=use_scope_filter,
                        query_image_bytes=query_image_bytes,
                        visual_query=visual_query_text,
                        top_k=plan_top_k,
                        plugin_namespace=plugin_namespace,
                        recall_top_k=recall_top_k,
                        retrieval_hints=retrieval_hints,
                    )
                    nodes = self._apply_rerank(
                        nodes,
                        query=query,
                        plan=plan,
                        plugin_namespace=plugin_namespace,
                        retrieval_hints=retrieval_hints,
                    )
                    plan_results.append(nodes)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "collection retrieval failed; skipping plan (G14): %s",
                    exc,
                    extra={"collection": plan.collection, "encoder": plan.encoder},
                )
                self._manager.audit.log_decision(
                    category="retrieve_plan",
                    target_collection=plan.collection,
                    plugin_namespace=plugin_namespace,
                    error=str(exc),
                    reason="plan_failed",
                )
                continue

        supplement_nodes: list[NodeWithScore] = []
        for item in self._manager.bus.invoke_all(
            Hook.RETRIEVE_SUPPLEMENT,
            hook_ctx,
            query,
            kb_name=kb_name,
            recall_top_k=recall_top_k,
        ):
            if isinstance(item, NodeWithScore):
                supplement_nodes.append(item)
            elif isinstance(item, list):
                supplement_nodes.extend(n for n in item if isinstance(n, NodeWithScore))

        merged = merge_rrf(plan_results, k=settings.router.rrf_k)
        successful_plans = sum(1 for lst in plan_results if lst)
        if successful_plans > 1:
            merged = dedupe_cross_collection(merged, audit=self._manager.audit)

        rrf_ctx = HookContext(
            plugin_namespace=plugin_namespace,
            extra={
                **hook_ctx.extra,
                "supplement_nodes": supplement_nodes,
            },
        )
        post_merged = self._manager.bus.invoke_first(
            Hook.RRF_POST_MERGE,
            rrf_ctx,
            merged,
            query=query,
            supplement_nodes=supplement_nodes,
            kb_name=kb_name,
        )
        if post_merged is not None:
            merged = list(post_merged)

        merged = rerank_merged(
            merged,
            query=query,
            top_n=final_top_k,
            plugin_namespace=plugin_namespace,
            audit=self._manager.audit,
            hook_bus=self._manager.bus,
        )
        return merged

    def _apply_rerank(
        self,
        nodes: list[NodeWithScore],
        *,
        query: str,
        plan: CollectionQueryPlan,
        plugin_namespace: str,
        retrieval_hints: dict[str, Any] | None = None,
    ) -> list[NodeWithScore]:
        if not nodes:
            return nodes
        extra: dict[str, Any] = {"collection": plan.collection, "encoder": plan.encoder}
        if retrieval_hints:
            if retrieval_hints.get("retrieval_intent") is not None:
                extra["retrieval_intent"] = retrieval_hints["retrieval_intent"]
            if retrieval_hints.get("sparse_terms"):
                extra["sparse_terms"] = retrieval_hints["sparse_terms"]
        hook_ctx = HookContext(
            plugin_namespace=plugin_namespace,
            extra=extra,
        )
        reranked = self._manager.bus.invoke_first(
            Hook.RERANK,
            hook_ctx,
            nodes,
            query=query,
            collection=plan.collection,
            encoder=plan.encoder,
        )
        return nodes if reranked is None else reranked

    def _retrieve_plan(
        self,
        plan: CollectionQueryPlan,
        query: str,
        *,
        kb_name: str | None,
        source_type: str | None,
        year: int | None,
        scope_kb_names: list[str] | None,
        scope_doc_ids: list[str] | None,
        use_scope_filter: bool,
        query_image_bytes: bytes | None,
        visual_query: str,
        top_k: int,
        plugin_namespace: str,
        recall_top_k: int | None = None,
        retrieval_hints: dict[str, Any] | None = None,
    ) -> list[NodeWithScore]:
        settings = get_settings()
        self._manager.encoder_registry.validate_plan(plan.collection, plan.encoder)
        effective_recall = recall_top_k or settings.router.recall_top_k

        if plan.collection == settings.milvus.text_collection:
            return self._retrieve_core_text(
                query,
                kb_name=kb_name,
                source_type=source_type,
                year=year,
                scope_kb_names=scope_kb_names,
                scope_doc_ids=scope_doc_ids,
                use_scope_filter=use_scope_filter,
                top_k=effective_recall,
                plugin_namespace=plugin_namespace,
                parent_doc_retrieval=(retrieval_hints or {}).get("parent_doc_retrieval"),
            )

        if plan.collection == settings.milvus.visual_collection:
            return self._retrieve_core_visual(
                visual_query,
                kb_name=kb_name,
                source_type=source_type,
                year=year,
                scope_kb_names=scope_kb_names,
                scope_doc_ids=scope_doc_ids,
                use_scope_filter=use_scope_filter,
                query_image_bytes=query_image_bytes,
                top_k=top_k,
                plugin_namespace=plugin_namespace,
            )

        db_name = milvus_db_name(plugin_namespace)
        if self._manager.collection_registry.has(db_name, plan.collection):
            store = self._manager.collection_registry.get(db_name, plan.collection)
            if hasattr(store, "retrieve"):
                return list(store.retrieve(query) or [])
            if hasattr(store, "as_retriever"):
                retriever = store.as_retriever(similarity_top_k=top_k)
                return list(retriever.retrieve(query) or [])

        return self._retrieve_generic_milvus(
            plan,
            query,
            plugin_namespace=plugin_namespace,
            kb_name=kb_name,
            source_type=source_type,
            year=year,
            scope_kb_names=scope_kb_names,
            scope_doc_ids=scope_doc_ids,
            use_scope_filter=use_scope_filter,
            query_image_bytes=query_image_bytes,
            top_k=top_k,
            recall_top_k=effective_recall,
            retrieval_hints=retrieval_hints,
        )

    def _retrieve_core_text(
        self,
        query: str,
        *,
        kb_name: str | None,
        source_type: str | None,
        year: int | None,
        scope_kb_names: list[str] | None,
        scope_doc_ids: list[str] | None,
        use_scope_filter: bool,
        top_k: int,
        plugin_namespace: str | None = None,
        parent_doc_retrieval: bool | None = None,
    ) -> list[NodeWithScore]:
        if use_scope_filter:
            retriever = KnowhereGraphRetriever(
                top_k=top_k,
                kb_names=scope_kb_names,
                document_ids=scope_doc_ids,
                source_type=source_type,
                year=year,
                plugin_namespace=plugin_namespace,
                parent_doc_retrieval=parent_doc_retrieval,
            )
        elif kb_name or source_type is not None or year is not None:
            retriever = KnowhereGraphRetriever(
                top_k=top_k,
                kb_name=kb_name,
                source_type=source_type,
                year=year,
                plugin_namespace=plugin_namespace,
                parent_doc_retrieval=parent_doc_retrieval,
            )
        elif self._text_retriever is not None:
            retriever = self._text_retriever
        else:
            retriever = KnowhereGraphRetriever(
                top_k=top_k,
                kb_name=kb_name,
                plugin_namespace=plugin_namespace,
                parent_doc_retrieval=parent_doc_retrieval,
            )

        return list(retriever.retrieve(query) or [])

    def _retrieve_core_visual(
        self,
        query: str,
        *,
        kb_name: str | None,
        source_type: str | None,
        year: int | None,
        scope_kb_names: list[str] | None,
        scope_doc_ids: list[str] | None,
        use_scope_filter: bool,
        query_image_bytes: bytes | None,
        top_k: int,
        plugin_namespace: str | None = None,
    ) -> list[NodeWithScore]:
        if use_scope_filter:
            retriever = PixelRAGVisualRetriever(
                top_k=top_k,
                kb_names=scope_kb_names,
                document_ids=scope_doc_ids,
                source_type=source_type,
                year=year,
                plugin_namespace=plugin_namespace,
            )
        elif kb_name or source_type is not None or year is not None:
            retriever = PixelRAGVisualRetriever(
                top_k=top_k,
                kb_name=kb_name,
                source_type=source_type,
                year=year,
                plugin_namespace=plugin_namespace,
            )
        elif self._visual_retriever is not None:
            retriever = self._visual_retriever
        else:
            retriever = PixelRAGVisualRetriever(
                top_k=top_k, kb_name=kb_name, plugin_namespace=plugin_namespace
            )

        return list(
            retriever.retrieve(
                query,
                query_image_bytes=query_image_bytes,
            )
            or []
        )

    @staticmethod
    def _collection_field_names(client: Any, collection: str) -> set[str]:
        """Return scalar/vector field names for ``collection`` (best-effort)."""
        try:
            desc = client.describe_collection(collection)
        except Exception:  # noqa: BLE001
            return set()
        fields = desc.get("fields") if isinstance(desc, dict) else None
        if fields is None and hasattr(desc, "fields"):
            fields = desc.fields
        names: set[str] = set()
        for field in fields or []:
            if isinstance(field, dict):
                name = field.get("name")
            else:
                name = getattr(field, "name", None)
            if name:
                names.add(str(name))
        return names

    def _hybrid_enabled_for_collection(self, collection: str) -> bool:
        settings = get_settings()
        configured = settings.router.hybrid_text_collections
        if configured:
            return collection in configured
        if self._manager.encoder_registry.hybrid_enabled_for_collection(collection):
            return True
        return collection == settings.milvus.text_collection

    def _text_output_fields(self, collection: str) -> list[str]:
        fields = list(_TEXT_OUTPUT_FIELDS)
        extra = self._manager.encoder_registry.extra_output_fields_for_collection(collection)
        for name in extra:
            if name not in fields:
                fields.append(name)
        return fields

    def _retrieve_generic_milvus(
        self,
        plan: CollectionQueryPlan,
        query: str,
        *,
        plugin_namespace: str,
        kb_name: str | None,
        source_type: str | None,
        year: int | None,
        scope_kb_names: list[str] | None,
        scope_doc_ids: list[str] | None,
        use_scope_filter: bool,
        query_image_bytes: bytes | None,
        top_k: int,
        recall_top_k: int | None = None,
        retrieval_hints: dict[str, Any] | None = None,
    ) -> list[NodeWithScore]:
        settings = get_settings()
        enc_info = self._manager.encoder_registry.get(plan.encoder)
        dense_query = query
        extra_sparse_terms: list[str] = []
        hook_ctx = HookContext(
            plugin_namespace=plugin_namespace,
            extra={"collection": plan.collection, "encoder": plan.encoder},
        )
        expanded = self._manager.bus.invoke_first(
            Hook.QUERY_DENSE_EXPAND,
            hook_ctx,
            query,
            encoder=plan.encoder,
        )
        if expanded is not None:
            dense_query = expanded.dense_query
            extra_sparse_terms = list(expanded.sparse_terms)
        elif retrieval_hints and retrieval_hints.get("sparse_terms"):
            extra_sparse_terms = list(retrieval_hints["sparse_terms"])

        query_vector = self._encode_query(
            plan.encoder,
            dense_query,
            query_image_bytes=query_image_bytes,
        )
        if not query_vector:
            return []

        db_name = milvus_db_name(plugin_namespace)
        client = get_milvus_pool().get(db_name)
        schema_fields = self._collection_field_names(client, plan.collection)
        year_filter = year if (not schema_fields or "year" in schema_fields) else None
        expr = self._build_milvus_expr(
            kb_name=kb_name,
            source_type=source_type
            if (not schema_fields or "source_type" in schema_fields)
            else None,
            year=year_filter,
            scope_kb_names=scope_kb_names,
            scope_doc_ids=scope_doc_ids,
            use_scope_filter=use_scope_filter,
        )
        if enc_info.modality == "visual":
            wanted = _VISUAL_OUTPUT_FIELDS
        else:
            wanted = self._text_output_fields(plan.collection)
        output_fields = [f for f in wanted if not schema_fields or f in schema_fields]
        if not output_fields:
            output_fields = ["document_id", "kb_name"]
        raw = client.search(
            collection_name=plan.collection,
            data=[query_vector],
            anns_field="vector",
            limit=top_k or (recall_top_k or settings.router.recall_top_k),
            filter=expr or "",
            output_fields=output_fields,
        )
        nodes = self._hits_to_nodes(raw, modality=enc_info.modality)
        if (
            enc_info.modality == "text"
            and settings.router.hybrid_text_enabled
            and self._hybrid_enabled_for_collection(plan.collection)
        ):
            from eagle_rag.retrievers.hybrid_text_retriever import hybrid_fuse_dense_sparse

            nodes = hybrid_fuse_dense_sparse(
                nodes,
                query,
                alpha=settings.router.hybrid_alpha,
                extra_sparse_terms=extra_sparse_terms or None,
                rrf_k=settings.router.rrf_k,
            )
        return nodes

    def _encode_query(
        self,
        encoder_name: str,
        query: str,
        *,
        query_image_bytes: bytes | None,
    ) -> list[float]:
        if encoder_name == "text-embedding-v4":
            from eagle_rag.index.milvus_text_store import _build_embed_model

            return _build_embed_model().get_query_embedding(query)
        if encoder_name == "qwen3-vl":
            from eagle_rag.ingest.pixelrag_adapter import embed_image_bytes, embed_query

            if query_image_bytes and not query.strip():
                return embed_image_bytes(query_image_bytes)
            return embed_query(query)

        enc_info = self._manager.encoder_registry.get(encoder_name)
        encoder = enc_info.encoder
        # Domain visual encoders (e.g. BiomedCLIP via open_clip): image query
        # uses the vision tower; text query uses the CLIP text tower.
        if query_image_bytes and hasattr(encoder, "encode_image"):
            if not query.strip() or enc_info.modality == "visual":
                return list(encoder.encode_image(query_image_bytes))
        if hasattr(encoder, "encode_text"):
            return list(encoder.encode_text(query))
        if hasattr(encoder, "get_query_embedding"):
            return list(encoder.get_query_embedding(query))
        msg = f"encoder {encoder_name} cannot encode queries"
        raise TypeError(msg)

    @staticmethod
    def _build_milvus_expr(
        *,
        kb_name: str | None,
        source_type: str | None,
        year: int | None,
        scope_kb_names: list[str] | None,
        scope_doc_ids: list[str] | None,
        use_scope_filter: bool,
    ) -> str | None:
        conditions: list[str] = []
        if use_scope_filter and (scope_kb_names or scope_doc_ids):
            scope_parts: list[str] = []
            if scope_kb_names:
                quoted = ", ".join(f'"{name}"' for name in scope_kb_names)
                scope_parts.append(f"kb_name in [{quoted}]")
            if scope_doc_ids:
                quoted = ", ".join(f'"{doc_id}"' for doc_id in scope_doc_ids)
                scope_parts.append(f"document_id in [{quoted}]")
            if len(scope_parts) == 1:
                conditions.append(scope_parts[0])
            else:
                conditions.append(f"({' or '.join(scope_parts)})")
        elif kb_name is not None:
            conditions.append(f'kb_name == "{kb_name}"')
        if source_type is not None:
            conditions.append(f'source_type == "{source_type}"')
        if year is not None:
            conditions.append(f"year == {year}")
        if not conditions:
            return None
        return " and ".join(conditions)

    @staticmethod
    def _hits_to_nodes(raw: Any, *, modality: str) -> list[NodeWithScore]:
        if not raw:
            return []
        hits = raw[0] if isinstance(raw, list) and raw else []
        nodes: list[NodeWithScore] = []
        for hit in hits:
            entity = hit.get("entity") or {}
            score = hit.get("distance")
            if score is None:
                score = hit.get("score", 1.0)
            try:
                score = float(score)
            except (TypeError, ValueError):
                score = 1.0

            metadata = {k: entity.get(k) for k in entity if k != "text"}
            if modality == "visual":
                image_path = entity.get("image_path")
                node = ImageNode(
                    image_url=image_path,
                    image_path=image_path,
                    metadata=metadata,
                )
            else:
                text = entity.get("text") or ""
                node = TextNode(text=text, metadata=metadata)
            nodes.append(NodeWithScore(node=node, score=score))
        return nodes
