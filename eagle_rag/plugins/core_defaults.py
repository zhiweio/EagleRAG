"""Core built-in plugin: default classifiers, encoders, and hook registrations."""

from __future__ import annotations

from eagle_rag.config import get_settings
from eagle_rag.plugins.classifier import (
    ClassificationContext,
    ClassificationDecision,
)
from eagle_rag.plugins.context import PluginContext
from eagle_rag.plugins.contract import PluginManifest
from eagle_rag.plugins.hookbus import HookBus, HookContext
from eagle_rag.plugins.hooks import Hook
from eagle_rag.plugins.ingest_orchestrator import UpsertPayload
from eagle_rag.plugins.pipeline import VisualChunk
from eagle_rag.plugins.routing import CollectionQueryPlan, QueryRouteDecision

__all__ = ["CoreDefaultsPlugin", "plugin"]


class CoreDefaultsPlugin:
    """Namespace ``core`` built-in plugin (no privileged code paths)."""

    manifest = PluginManifest(
        namespace="core",
        version="1.0.0",
        milvus_db_name="default",
        provides_pipelines=("knowhere", "pixelrag"),
    )

    def register_hooks(self, bus: HookBus) -> None:
        bus.subscribe(
            Hook.CLASSIFY_CHUNK,
            _default_classify_chunk,
            priority=-1000,
            namespace=None,
            plugin_name="core_defaults",
        )
        bus.subscribe(
            Hook.CLASSIFY_VISUAL,
            _default_classify_visual,
            priority=-1000,
            namespace=None,
            plugin_name="core_defaults",
        )
        bus.subscribe(
            Hook.CLASSIFY_QUERY,
            _default_classify_query,
            priority=-1000,
            namespace=None,
            plugin_name="core_defaults",
        )
        bus.subscribe(
            Hook.EMBED_TEXT,
            _default_embed_text,
            priority=-1000,
            namespace=None,
            plugin_name="core_defaults",
        )
        bus.subscribe(
            Hook.EMBED_VISUAL,
            _default_embed_visual,
            priority=-1000,
            namespace=None,
            plugin_name="core_defaults",
        )
        bus.subscribe(
            Hook.UPSERT_VECTORS,
            _default_upsert_vectors,
            priority=-1000,
            namespace=None,
            plugin_name="core_defaults",
        )
        bus.subscribe(
            Hook.INGEST_VISUAL_EXTRACT,
            _default_visual_extract,
            priority=-1000,
            namespace=None,
            plugin_name="core_defaults",
        )

    def on_load(self, ctx: PluginContext) -> None:
        from eagle_rag.ingest.knowhere_adapter import KnowherePipeline
        from eagle_rag.ingest.pixelrag_adapter import PixelragPipeline

        ctx.register_pipeline("knowhere", KnowherePipeline())
        ctx.register_pipeline("pixelrag", PixelragPipeline())

        settings = ctx.settings
        ctx.encoder_registry.register(
            "text-embedding-v4",
            object(),
            dim=settings.embedding.text.dim,
            modality="text",
        )
        ctx.encoder_registry.register(
            "qwen3-vl",
            object(),
            dim=settings.embedding.visual.dim,
            modality="visual",
        )
        ctx.encoder_registry.register_collection(
            settings.milvus.text_collection,
            dim=settings.embedding.text.dim,
            default_encoder="text-embedding-v4",
            hybrid_enabled=True,
        )
        ctx.encoder_registry.register_collection(
            settings.milvus.visual_collection,
            dim=settings.embedding.visual.dim,
            default_encoder="qwen3-vl",
        )

    def on_unload(self) -> None:
        return None

    def ensure_collections(self, ctx: PluginContext) -> None:
        return None


def _default_classify_chunk(
    ctx: HookContext,
    class_ctx: ClassificationContext,
) -> ClassificationDecision:
    settings = get_settings()
    return ClassificationDecision(
        category="general_text",
        target_collection=settings.milvus.text_collection,
        target_encoder="text-embedding-v4",
        chunk_type="text",
        fallback_used=True,
    )


def _default_classify_visual(
    ctx: HookContext,
    class_ctx: ClassificationContext,
) -> ClassificationDecision:
    settings = get_settings()
    return ClassificationDecision(
        category="document_visual",
        target_collection=settings.milvus.visual_collection,
        target_encoder="qwen3-vl",
        chunk_type="image",
        fallback_used=True,
    )


def _default_classify_query(
    ctx: HookContext,
    query: str,
    *,
    has_image: bool = False,
    route_mode: str = "text",
    **_kwargs: object,
) -> QueryRouteDecision:
    """G4: never auto-query specialized collections."""
    settings = get_settings()
    plans: list[CollectionQueryPlan] = []
    mode = (route_mode or "text").lower()
    if mode in ("text", "hybrid"):
        plans.append(
            CollectionQueryPlan(
                collection=settings.milvus.text_collection,
                encoder="text-embedding-v4",
            )
        )
    if mode in ("visual", "hybrid") or has_image:
        plans.append(
            CollectionQueryPlan(
                collection=settings.milvus.visual_collection,
                encoder="qwen3-vl",
            )
        )
    return QueryRouteDecision(plans=tuple(plans))


def _default_embed_text(
    ctx: HookContext,
    chunk: object,
    *,
    decision: ClassificationDecision,
    **_kwargs: object,
) -> object:
    if decision.target_encoder == "text-embedding-v4":
        return chunk
    from eagle_rag.plugins.encoder_runtime import encode_text_chunk

    return encode_text_chunk(chunk, decision.target_encoder)


def _default_embed_visual(
    ctx: HookContext,
    chunk: object,
    *,
    decision: ClassificationDecision,
    **_kwargs: object,
) -> list[float]:
    if decision.target_encoder != "qwen3-vl":
        from eagle_rag.plugins.encoder_runtime import encode_visual_bytes_for_encoder

        if isinstance(chunk, VisualChunk) and chunk.image_bytes:
            return encode_visual_bytes_for_encoder(decision.target_encoder, chunk.image_bytes)
        if isinstance(chunk, dict):
            image_bytes = chunk.get("image_bytes")
            if isinstance(image_bytes, bytes):
                return encode_visual_bytes_for_encoder(decision.target_encoder, image_bytes)
    if isinstance(chunk, VisualChunk):
        if chunk.vector is not None:
            return chunk.vector
        if chunk.image_bytes:
            from eagle_rag.ingest.pixelrag_adapter import embed_image_bytes

            return embed_image_bytes(chunk.image_bytes)
    if isinstance(chunk, dict):
        vector = chunk.get("vector")
        if isinstance(vector, list):
            return vector
        image_bytes = chunk.get("image_bytes")
        if isinstance(image_bytes, bytes):
            from eagle_rag.ingest.pixelrag_adapter import embed_image_bytes

            return embed_image_bytes(image_bytes)
    msg = "visual chunk missing image_bytes or vector"
    raise ValueError(msg)


def _default_visual_extract(ctx: HookContext, parse_result: object) -> list[dict]:
    """Core default: Knowhere visual chunk extraction with four anchor fields."""
    del ctx
    from eagle_rag.ingest.knowhere_adapter import extract_visual_chunks

    return extract_visual_chunks(parse_result)


def _default_upsert_vectors(ctx: HookContext, payload: UpsertPayload) -> str:
    if payload.text_node is not None:
        from eagle_rag.index.milvus_text_store import upsert_text_nodes

        ids = upsert_text_nodes(
            [payload.text_node],
            plugin_namespace=payload.plugin_namespace,
            collection=payload.collection,
        )
        return ids[0]
    if payload.visual is not None:
        from eagle_rag.index.milvus_visual_store import upsert_visual

        record = dict(payload.visual)
        if payload.vector is not None:
            record["vector"] = payload.vector
        upsert_visual(**record, plugin_namespace=payload.plugin_namespace)
        return str(record["image_id"])
    msg = "upsert payload missing text_node or visual record"
    raise ValueError(msg)


plugin = CoreDefaultsPlugin()
