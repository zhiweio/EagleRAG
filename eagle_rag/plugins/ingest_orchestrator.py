"""Ingest-side encode and upsert orchestration (symmetric to RetrieverOrchestrator)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from eagle_rag.plugins.classifier import ClassificationContext, ClassificationDecision
from eagle_rag.plugins.hookbus import HookContext
from eagle_rag.plugins.hooks import Hook
from eagle_rag.plugins.pipeline import VisualChunk

if TYPE_CHECKING:
    from llama_index.core.schema import TextNode

    from eagle_rag.plugins.encoder_registry import EncoderRegistry
    from eagle_rag.plugins.hookbus import HookBus

__all__ = ["IngestOrchestrator", "UpsertPayload", "get_ingest_orchestrator"]


@dataclass
class UpsertPayload:
    """Payload flowing through the UPSERT_VECTORS transform hook chain."""

    decision: ClassificationDecision
    collection: str
    encoder_name: str
    chunk_type: str
    plugin_namespace: str
    kb_name: str
    document_id: str
    text_node: TextNode | None = None
    visual: dict[str, Any] | None = None
    vector: list[float] | None = None
    anchors: dict[str, str] = field(default_factory=dict)


class IngestOrchestrator:
    """CLASSIFY → EMBED_* → UPSERT_VECTORS ingest path."""

    def __init__(self, bus: HookBus, encoder_registry: EncoderRegistry) -> None:
        self._bus = bus
        self._encoder_registry = encoder_registry

    def classify(
        self,
        hook_ctx: HookContext,
        class_ctx: ClassificationContext,
    ) -> ClassificationDecision:
        """Resolve a chunk/asset classification via CLASSIFY_* hooks."""
        hook = (
            Hook.CLASSIFY_VISUAL
            if class_ctx.modality in ("image", "table", "visual")
            else Hook.CLASSIFY_CHUNK
        )
        decision = self._bus.invoke_first(hook, hook_ctx, class_ctx)
        if decision is None:
            msg = f"no classifier decision for modality={class_ctx.modality!r}"
            raise ValueError(msg)
        if not isinstance(decision, ClassificationDecision):
            msg = f"unexpected classifier result type: {type(decision)!r}"
            raise TypeError(msg)
        return decision

    def embed_and_upsert(
        self,
        chunk: TextNode | VisualChunk | dict[str, Any],
        decision: ClassificationDecision,
        *,
        plugin_namespace: str,
        kb_name: str,
        document_id: str,
        hook_ctx: HookContext | None = None,
    ) -> str:
        """Encode via EMBED_* hooks and persist via UPSERT_VECTORS."""
        ctx = hook_ctx or HookContext(plugin_namespace=plugin_namespace, kb_name=kb_name)
        ctx.document_id = document_id

        self._encoder_registry.validate_plan(decision.target_collection, decision.target_encoder)

        is_visual = decision.chunk_type in ("image", "table", "tile") or isinstance(
            chunk, VisualChunk
        )
        embed_hook = Hook.EMBED_VISUAL if is_visual else Hook.EMBED_TEXT
        embedded = self._bus.invoke_first(
            embed_hook,
            ctx,
            chunk,
            decision=decision,
            kb_name=kb_name,
            document_id=document_id,
        )
        if embedded is None:
            embedded = chunk

        payload = self._build_payload(
            chunk=chunk,
            embedded=embedded,
            decision=decision,
            plugin_namespace=plugin_namespace,
            kb_name=kb_name,
            document_id=document_id,
            is_visual=is_visual,
        )
        node_id = self._bus.invoke(Hook.UPSERT_VECTORS, ctx, payload)
        if node_id is None:
            msg = "UPSERT_VECTORS hook returned no node id"
            raise ValueError(msg)
        if not isinstance(node_id, str):
            return str(node_id)
        return node_id

    def _build_payload(
        self,
        *,
        chunk: TextNode | VisualChunk | dict[str, Any],
        embedded: Any,
        decision: ClassificationDecision,
        plugin_namespace: str,
        kb_name: str,
        document_id: str,
        is_visual: bool,
    ) -> UpsertPayload:
        anchors = {
            "chunk_type": decision.chunk_type,
            "parent_section": "",
            "content_summary": "",
            "source_chunk_id": "",
        }
        if isinstance(chunk, VisualChunk):
            anchors["parent_section"] = chunk.parent_section
            anchors["content_summary"] = chunk.content_summary
            anchors["source_chunk_id"] = chunk.source_chunk_id
            anchors["chunk_type"] = chunk.chunk_type or decision.chunk_type
        elif isinstance(chunk, dict):
            anchors["parent_section"] = str(chunk.get("parent_section") or "")
            summary = chunk.get("content_summary") or chunk.get("summary") or ""
            anchors["content_summary"] = str(summary)
            source_id = chunk.get("source_chunk_id") or chunk.get("chunk_id") or ""
            anchors["source_chunk_id"] = str(source_id)
            anchors["chunk_type"] = str(chunk.get("chunk_type") or decision.chunk_type)

        if is_visual:
            vector = embedded if isinstance(embedded, list) else None
            visual_record = self._visual_record_from_chunk(
                chunk,
                document_id=document_id,
                kb_name=kb_name,
                anchors=anchors,
                vector=vector,
            )
            return UpsertPayload(
                decision=decision,
                collection=decision.target_collection,
                encoder_name=decision.target_encoder,
                chunk_type=anchors["chunk_type"],
                plugin_namespace=plugin_namespace,
                kb_name=kb_name,
                document_id=document_id,
                visual=visual_record,
                vector=vector,
                anchors=anchors,
            )

        text_node = embedded if not isinstance(embedded, list) else chunk
        return UpsertPayload(
            decision=decision,
            collection=decision.target_collection,
            encoder_name=decision.target_encoder,
            chunk_type=decision.chunk_type,
            plugin_namespace=plugin_namespace,
            kb_name=kb_name,
            document_id=document_id,
            text_node=text_node,  # type: ignore[arg-type]
            anchors=anchors,
        )

    @staticmethod
    def _visual_record_from_chunk(
        chunk: VisualChunk | dict[str, Any],
        *,
        document_id: str,
        kb_name: str,
        anchors: dict[str, str],
        vector: list[float] | None,
    ) -> dict[str, Any]:
        if isinstance(chunk, VisualChunk):
            image_id = chunk.chunk_id
            return {
                "image_id": image_id,
                "vector": vector or chunk.vector or [],
                "image_path": chunk.image_path or image_id,
                "document_id": document_id,
                "page": chunk.page,
                "position": chunk.position,
                "kb_name": kb_name,
                "year": chunk.year,
                "source_type": chunk.source_type,
                "chunk_type": anchors["chunk_type"],
                "parent_section": anchors["parent_section"] or None,
                "content_summary": anchors["content_summary"] or None,
                "source_chunk_id": anchors["source_chunk_id"] or None,
            }
        image_id = str(chunk.get("image_id") or chunk.get("chunk_id") or "")
        return {
            "image_id": image_id,
            "vector": vector or chunk.get("vector") or [],
            "image_path": chunk.get("image_path") or image_id,
            "document_id": document_id,
            "page": chunk.get("page"),
            "position": chunk.get("position"),
            "kb_name": kb_name,
            "year": chunk.get("year"),
            "source_type": chunk.get("source_type"),
            "chunk_type": anchors["chunk_type"],
            "parent_section": anchors["parent_section"] or None,
            "content_summary": anchors["content_summary"] or None,
            "source_chunk_id": anchors["source_chunk_id"] or None,
        }


def get_ingest_orchestrator() -> IngestOrchestrator:
    """Process-wide ingest orchestrator bound to the plugin manager singleton."""
    from eagle_rag.plugins import get_plugin_manager

    mgr = get_plugin_manager()
    return IngestOrchestrator(mgr.bus, mgr.encoder_registry)
