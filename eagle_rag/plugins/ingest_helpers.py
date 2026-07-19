"""Batch ingest helpers wiring adapters through IngestOrchestrator (G22/G26)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from eagle_rag.config import get_settings
from eagle_rag.plugins.classifier import ClassificationContext
from eagle_rag.plugins.hookbus import HookContext
from eagle_rag.plugins.ingest_orchestrator import get_ingest_orchestrator
from eagle_rag.plugins.ingest_tracker import record_ingest_collection

if TYPE_CHECKING:
    from llama_index.core.schema import TextNode

__all__ = ["ingest_text_nodes", "ingest_visual_record"]

# Keep in sync with ``DASHSCOPE_TEXT_EMBED_BATCH_MAX`` in milvus_text_store.
_DASHSCOPE_EMBED_BATCH_MAX = 10


def ingest_text_nodes(
    nodes: list[TextNode],
    *,
    plugin_namespace: str,
    kb_name: str,
    document_id: str,
) -> list[str]:
    """Classify and upsert text nodes; batch default-collection writes when possible."""
    if not nodes:
        return []
    orchestrator = get_ingest_orchestrator()
    hook_ctx = HookContext(
        plugin_namespace=plugin_namespace,
        kb_name=kb_name,
        document_id=document_id,
    )
    settings = get_settings()
    default_coll = settings.milvus.text_collection
    node_ids: list[str] = []
    default_batch: list[TextNode] = []
    exclusive_primary: dict[str, str] = {}
    chunk_primary: dict[str, str] = {}

    def _flush_default() -> None:
        nonlocal default_batch
        if not default_batch:
            return
        from eagle_rag.index.milvus_text_store import upsert_text_nodes

        record_ingest_collection(default_coll)
        for offset in range(0, len(default_batch), _DASHSCOPE_EMBED_BATCH_MAX):
            chunk = default_batch[offset : offset + _DASHSCOPE_EMBED_BATCH_MAX]
            node_ids.extend(
                upsert_text_nodes(
                    chunk,
                    plugin_namespace=plugin_namespace,
                    collection=default_coll,
                )
            )
        default_batch = []

    for node in nodes:
        meta = node.metadata or {}
        source_id = str(node.node_id or meta.get("chunk_id") or meta.get("source_chunk_id") or "")
        class_ctx = ClassificationContext(
            content=node.get_content(),
            modality="text",
            document_id=document_id,
            kb_name=kb_name,
            plugin_namespace=plugin_namespace,
            parent_section=str(meta.get("path") or ""),
            source_chunk_id=source_id,
            file_ext=str(meta.get("file_path") or ""),
            extra={
                "section": meta.get("biomed_section") or meta.get("section") or "",
                "doc_type": meta.get("biomed_doc_type") or meta.get("doc_type") or "",
                "text_profile": meta.get("biomed_text_profile") or "biomedical",
                "text_profile_rule": meta.get("biomed_text_profile_rule") or "",
                "text_profile_confidence": meta.get("biomed_text_profile_confidence"),
                "text_profile_tier": meta.get("biomed_text_profile_tier") or "",
            },
        )
        decision = orchestrator.classify(hook_ctx, class_ctx)

        if decision.exclusive_group:
            prior_coll = exclusive_primary.get(decision.exclusive_group)
            if prior_coll and prior_coll != decision.target_collection:
                _log_exclusive_skip(
                    hook_ctx,
                    source_id=source_id,
                    group=decision.exclusive_group,
                    collection=decision.target_collection,
                )
                continue
            exclusive_primary[decision.exclusive_group] = decision.target_collection

        if source_id and source_id in chunk_primary:
            if chunk_primary[source_id] != decision.target_collection:
                _log_exclusive_skip(
                    hook_ctx,
                    source_id=source_id,
                    group=decision.exclusive_group or "chunk",
                    collection=decision.target_collection,
                )
                continue
        if source_id:
            chunk_primary[source_id] = decision.target_collection

        if (
            decision.target_collection == default_coll
            and decision.target_encoder == "text-embedding-v4"
            and decision.exclusive_group is None
        ):
            default_batch.append(node)
            continue
        _flush_default()
        record_ingest_collection(decision.target_collection)
        node_ids.append(
            orchestrator.embed_and_upsert(
                node,
                decision,
                plugin_namespace=plugin_namespace,
                kb_name=kb_name,
                document_id=document_id,
                hook_ctx=hook_ctx,
            )
        )
    _flush_default()
    return node_ids


def ingest_visual_record(
    record: dict[str, Any],
    *,
    plugin_namespace: str,
    kb_name: str,
    document_id: str,
) -> str:
    """Classify and upsert one visual vector record via the orchestrator."""
    orchestrator = get_ingest_orchestrator()
    hook_ctx = HookContext(
        plugin_namespace=plugin_namespace,
        kb_name=kb_name,
        document_id=document_id,
    )
    # PixelRAG uses chunk_type="tile". That must classify as visual — never as text.
    # Passing the raw chunk_type as modality used to route tiles through CLASSIFY_CHUNK
    # and then treat the visual dict as a TextNode (AttributeError on .embedding/.get_content).
    chunk_type = str(record.get("chunk_type") or "tile")
    modality = "visual" if chunk_type in {"tile", "image", "table", "medical_image"} else chunk_type
    class_ctx = ClassificationContext(
        content=b"",
        modality=modality,
        document_id=document_id,
        kb_name=kb_name,
        plugin_namespace=plugin_namespace,
        parent_section=str(record.get("parent_section") or ""),
        source_chunk_id=str(record.get("source_chunk_id") or record.get("image_id") or ""),
        extra={"chunk_type": chunk_type},
    )
    decision = orchestrator.classify(hook_ctx, class_ctx)
    record_ingest_collection(decision.target_collection)
    return orchestrator.embed_and_upsert(
        record,
        decision,
        plugin_namespace=plugin_namespace,
        kb_name=kb_name,
        document_id=document_id,
        hook_ctx=hook_ctx,
    )


def _log_exclusive_skip(
    hook_ctx: HookContext,
    *,
    source_id: str,
    group: str,
    collection: str,
) -> None:
    try:
        from eagle_rag.plugins import get_plugin_manager

        get_plugin_manager().audit.log_decision(
            category="ingest_exclusive_skip",
            reason=group,
            target_collection=collection,
            extra={
                "source_chunk_id": source_id,
                "exclusive_group": group,
                "document_id": hook_ctx.document_id,
                "kb_name": hook_ctx.kb_name,
            },
        )
    except Exception:  # noqa: BLE001
        return
