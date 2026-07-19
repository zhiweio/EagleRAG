"""Biomed domain plugin (M6): classifiers, encoders, routing, and MCP tools."""

from __future__ import annotations

from pymilvus import DataType, MilvusClient

from eagle_rag.index.milvus_pool import get_milvus_pool
from eagle_rag.plugins.classifier import ClassificationContext
from eagle_rag.plugins.context import PluginContext
from eagle_rag.plugins.contract import PluginManifest
from eagle_rag.plugins.hookbus import HookBus, HookContext
from eagle_rag.plugins.hooks import Hook
from eagle_rag.plugins.milvus_ns import milvus_db_name
from eagle_rag.plugins.routing import QueryRouteDecision
from eagle_rag.telemetry import get_logger
from plugins.biomed.classifiers import BiomedImageClassifier, BiomedTextClassifier
from plugins.biomed.encoders import COLLECTION_DIMS, register_encoders
from plugins.biomed.query_route import BiomedQueryRouteClassifier

__all__ = ["BiomedPlugin", "plugin"]

logger = get_logger(__name__)

_TEXT_COLLECTIONS = frozenset({"eagle_text_biomed", "eagle_chemical"})


def _index_params(client: MilvusClient, *, metric: str) -> object:
    params = client.prepare_index_params()
    params.add_index(
        field_name="vector",
        index_type="HNSW",
        metric_type=metric,
        params={"M": 16, "efConstruction": 256},
    )
    for field_name in ("kb_name", "document_id", "chunk_type", "source_type"):
        params.add_index(field_name=field_name, index_type="INVERTED")
    return params


def _ensure_text_collection(
    client: MilvusClient,
    coll_name: str,
    *,
    dim: int,
) -> None:
    if client.has_collection(coll_name):
        return
    schema = client.create_schema()
    schema.add_field("id", DataType.VARCHAR, max_length=64, is_primary=True)
    schema.add_field("vector", DataType.FLOAT_VECTOR, dim=dim)
    schema.add_field("text", DataType.VARCHAR, max_length=65535)
    schema.add_field("document_id", DataType.VARCHAR, max_length=64)
    schema.add_field("kb_name", DataType.VARCHAR, max_length=64, default_value="default")
    schema.add_field("path", DataType.VARCHAR, max_length=512, nullable=True)
    schema.add_field("chunk_type", DataType.VARCHAR, max_length=32, default_value="text")
    schema.add_field("source_type", DataType.VARCHAR, max_length=32, nullable=True)
    schema.add_field("source_chunk_id", DataType.VARCHAR, max_length=128, nullable=True)
    schema.add_field("primary_drugs", DataType.VARCHAR, max_length=2048, nullable=True)
    client.create_collection(
        coll_name,
        schema=schema,
        index_params=_index_params(client, metric="COSINE"),
    )
    logger.info("created biomed text collection", extra={"collection": coll_name, "dim": dim})


def _ensure_visual_collection(
    client: MilvusClient,
    coll_name: str,
    *,
    dim: int,
    chunk_type_default: str,
) -> None:
    if client.has_collection(coll_name):
        return
    schema = client.create_schema()
    schema.add_field("id", DataType.VARCHAR, max_length=64, is_primary=True)
    schema.add_field("vector", DataType.FLOAT_VECTOR, dim=dim)
    schema.add_field("image_path", DataType.VARCHAR, max_length=512)
    schema.add_field("image_id", DataType.VARCHAR, max_length=64)
    schema.add_field("document_id", DataType.VARCHAR, max_length=64)
    schema.add_field("kb_name", DataType.VARCHAR, max_length=64, default_value="default")
    schema.add_field(
        "chunk_type",
        DataType.VARCHAR,
        max_length=32,
        default_value=chunk_type_default,
    )
    schema.add_field("parent_section", DataType.VARCHAR, max_length=512, nullable=True)
    schema.add_field("content_summary", DataType.VARCHAR, max_length=2048, nullable=True)
    schema.add_field("source_chunk_id", DataType.VARCHAR, max_length=128, nullable=True)
    schema.add_field("source_type", DataType.VARCHAR, max_length=32, nullable=True)
    client.create_collection(
        coll_name,
        schema=schema,
        index_params=_index_params(client, metric="IP"),
    )
    logger.info("created biomed visual collection", extra={"collection": coll_name, "dim": dim})


def ensure_biomed_collections(ctx: PluginContext) -> None:
    """Create specialized Milvus collections in the biomed database."""
    db_name = milvus_db_name(ctx.plugin_namespace)
    client = get_milvus_pool().get(db_name)

    for coll_name, dim in COLLECTION_DIMS.items():
        if coll_name in _TEXT_COLLECTIONS:
            _ensure_text_collection(client, coll_name, dim=dim)
        elif coll_name == "eagle_medical_radiology":
            _ensure_visual_collection(
                client,
                coll_name,
                dim=dim,
                chunk_type_default="medical_image",
            )
        elif coll_name == "eagle_medical_pathology":
            _ensure_visual_collection(
                client,
                coll_name,
                dim=dim,
                chunk_type_default="medical_image",
            )
        else:
            _ensure_text_collection(client, coll_name, dim=dim)

        try:
            client.load_collection(coll_name)
        except Exception:  # noqa: BLE001
            logger.debug("load_collection skipped for %s", coll_name, exc_info=True)


class BiomedPlugin:
    """In-process biomed plugin."""

    manifest = PluginManifest(
        namespace="biomed",
        version="0.1.0",
        milvus_db_name="biomed",
        provides_specialized_collections=(
            "eagle_text_biomed",
            "eagle_chemical",
            "eagle_medical_radiology",
            "eagle_medical_pathology",
        ),
        provides_mcp_tools=("query_entities", "retrieve_compounds"),
        resource_hints={"gpu_mb": 8192, "load_order": 20},
    )

    def __init__(self) -> None:
        self._text_classifier = BiomedTextClassifier()
        self._image_classifier = BiomedImageClassifier()
        self._query_router = BiomedQueryRouteClassifier()

    def register_hooks(self, bus: HookBus) -> None:
        from plugins.biomed.hooks_extra import biomed_format_selector, biomed_rerank
        from plugins.biomed.retrieval_hooks import (
            biomed_dense_expand,
            biomed_rerank_merged,
            biomed_retrieve_supplement,
        )

        bus.subscribe(
            Hook.INGEST_ROUTE_SELECTORS,
            biomed_format_selector,
            priority=100,
            namespace="biomed",
            plugin_name="biomed",
        )
        bus.subscribe(
            Hook.CLASSIFY_CHUNK,
            self._classify_chunk,
            priority=100,
            namespace="biomed",
            plugin_name="biomed",
        )
        bus.subscribe(
            Hook.CLASSIFY_VISUAL,
            self._classify_visual,
            priority=100,
            namespace="biomed",
            plugin_name="biomed",
        )
        bus.subscribe(
            Hook.CLASSIFY_QUERY,
            self._classify_query,
            priority=100,
            namespace="biomed",
            plugin_name="biomed",
        )
        bus.subscribe(
            Hook.CHUNK,
            self._chunk_transform,
            priority=100,
            namespace="biomed",
            plugin_name="biomed",
        )
        bus.subscribe(
            Hook.QUERY_ASSEMBLE,
            self._query_assemble,
            priority=100,
            namespace="biomed",
            plugin_name="biomed",
        )
        bus.subscribe(
            Hook.EMBED_TEXT,
            self._embed_text,
            priority=100,
            namespace="biomed",
            plugin_name="biomed",
        )
        bus.subscribe(
            Hook.EMBED_VISUAL,
            self._embed_visual,
            priority=100,
            namespace="biomed",
            plugin_name="biomed",
        )
        bus.subscribe(
            Hook.RERANK,
            biomed_rerank,
            priority=100,
            namespace="biomed",
            plugin_name="biomed",
        )
        bus.subscribe(
            Hook.QUERY_DENSE_EXPAND,
            biomed_dense_expand,
            priority=100,
            namespace="biomed",
            plugin_name="biomed",
        )
        bus.subscribe(
            Hook.RETRIEVE_SUPPLEMENT,
            biomed_retrieve_supplement,
            priority=100,
            namespace="biomed",
            plugin_name="biomed",
        )
        bus.subscribe(
            Hook.RERANK_MERGED,
            biomed_rerank_merged,
            priority=100,
            namespace="biomed",
            plugin_name="biomed",
        )

    def on_load(self, ctx: PluginContext) -> None:
        register_encoders(ctx)

    def register_mcp_tools(self) -> None:
        """Import MCP tool module so ``@register_mcp_tool`` decorators run."""
        from plugins.biomed import mcp_tools as _mcp_tools

        _mcp_tools.register_mcp_tools()

    def on_unload(self) -> None:
        return None

    def ensure_collections(self, ctx: PluginContext) -> None:
        ensure_biomed_collections(ctx)

    def _classify_chunk(
        self,
        hook_ctx: HookContext,
        class_ctx: ClassificationContext,
    ):
        del hook_ctx
        decision = self._text_classifier.classify(class_ctx)
        return decision

    def _classify_visual(
        self,
        hook_ctx: HookContext,
        class_ctx: ClassificationContext,
    ):
        del hook_ctx
        return self._image_classifier.classify(class_ctx)

    def _classify_query(
        self,
        hook_ctx: HookContext,
        query: str,
        *,
        has_image: bool = False,
        route_mode: str = "text",
        **kwargs: object,
    ) -> QueryRouteDecision | None:
        del hook_ctx, kwargs
        return self._query_router.route(
            query,
            "biomed",
            has_image=has_image,
            route_mode=route_mode,
        )

    def _chunk_transform(self, hook_ctx: HookContext, nodes: list[object], **kwargs: object):
        from plugins.biomed.chunker import biomed_chunk_transform

        return biomed_chunk_transform(hook_ctx, nodes, **kwargs)

    def _query_assemble(
        self,
        hook_ctx: HookContext,
        query: str,
        *,
        kb_name: str | None = None,
        **kwargs: object,
    ) -> str | None:
        from plugins.biomed.entity_expand import biomed_query_assemble

        return biomed_query_assemble(hook_ctx, query, kb_name=kb_name, **kwargs)

    def _embed_text(
        self,
        hook_ctx: HookContext,
        chunk: object,
        *,
        decision: object,
        **_kwargs: object,
    ) -> object | None:
        del hook_ctx
        enc = getattr(decision, "target_encoder", "")
        if enc in ("text-embedding-v4", ""):
            return None
        from eagle_rag.plugins.encoder_runtime import encode_text_chunk

        return encode_text_chunk(chunk, str(enc))

    def _embed_visual(
        self,
        hook_ctx: HookContext,
        chunk: object,
        *,
        decision: object,
        **_kwargs: object,
    ) -> list[float] | None:
        del hook_ctx
        enc = getattr(decision, "target_encoder", "")
        if enc in ("qwen3-vl", ""):
            return None
        from eagle_rag.plugins.encoder_runtime import encode_visual_bytes_for_encoder

        if isinstance(chunk, dict):
            image_bytes = chunk.get("image_bytes")
            if isinstance(image_bytes, bytes):
                return encode_visual_bytes_for_encoder(str(enc), image_bytes)
        return None


plugin = BiomedPlugin()
