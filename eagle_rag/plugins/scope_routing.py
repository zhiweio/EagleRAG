"""Scope-aware collection plan union (G21/G23/G29)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from eagle_rag.config import get_settings
from eagle_rag.db.repositories.catalog import get_document_collections, get_kb_collections
from eagle_rag.plugins.routing import CollectionQueryPlan, QueryRouteDecision
from eagle_rag.telemetry import get_logger

if TYPE_CHECKING:
    from eagle_rag.plugins.context import PluginAudit
    from eagle_rag.plugins.encoder_registry import EncoderRegistry

__all__ = ["apply_scope_aware_union"]

_LOGGER = get_logger(__name__)

# Canonical collection -> encoder mapping for specialized (non-Core) collections.
# Prevents dim-collision mismatches: ``pubmedbert`` and ``molformer`` are both
# 768-dim, so the previous dim-only probe could assign ``pubmedbert`` to
# ``eagle_chemical``. These names are stable plugin contracts (ADR-008).
_SPECIALIZED_COLLECTION_ENCODERS: dict[str, str] = {
    "eagle_text_biomed": "pubmedbert",
    "eagle_chemical": "molformer",
    "eagle_medical_radiology": "medimageinsight",
    "eagle_medical_pathology": "uni2",
}


def _encoder_for_collection(
    collection: str,
    encoder_registry: EncoderRegistry,
) -> str | None:
    settings = get_settings()
    defaults = {
        settings.milvus.text_collection: "text-embedding-v4",
        settings.milvus.visual_collection: "qwen3-vl",
    }
    if collection in defaults:
        return defaults[collection]
    canonical = _SPECIALIZED_COLLECTION_ENCODERS.get(collection)
    if canonical is not None:
        try:
            encoder_registry.validate_plan(collection, canonical)
        except (KeyError, ValueError):
            return None
        return canonical
    # Fallback for unknown (future plugin) collections: first dim-matching encoder.
    for name in encoder_registry.names():
        try:
            encoder_registry.validate_plan(collection, name)
        except (KeyError, ValueError):
            continue
        return name
    return None


def apply_scope_aware_union(
    decision: QueryRouteDecision,
    *,
    plugin_namespace: str,
    encoder_registry: EncoderRegistry,
    top_k: int = 5,
    scope_document_ids: tuple[str, ...] | None = None,
    scope_kb_names: tuple[str, ...] | None = None,
    scope_tags: tuple[str, ...] | None = None,
    audit: PluginAudit | None = None,
) -> tuple[QueryRouteDecision, bool]:
    """Merge catalog collections into ``decision.plans`` when scope is set (G21/G23/G29)."""
    catalog_collections: set[str] = set()
    reason: str | None = None

    if scope_document_ids:
        catalog_collections |= get_document_collections(
            list(scope_document_ids),
            plugin_namespace=plugin_namespace,
        )
        reason = "scope_aware_union"

    if scope_kb_names:
        kb_cols = get_kb_collections(list(scope_kb_names), plugin_namespace=plugin_namespace)
        if kb_cols:
            catalog_collections |= kb_cols
            reason = "kb_catalog_union"

    if scope_tags:
        try:
            from eagle_rag.index.tag_catalog import resolve_tags_to_document_ids

            cap = get_settings().router.max_scope_documents
            tag_doc_ids = resolve_tags_to_document_ids(
                list(scope_tags),
                kb_names=list(scope_kb_names) if scope_kb_names else None,
                cap=cap,
                plugin_namespace=plugin_namespace,
            )
            if tag_doc_ids:
                catalog_collections |= get_document_collections(
                    tag_doc_ids,
                    plugin_namespace=plugin_namespace,
                )
                reason = "scope_aware_union"
        except Exception as exc:  # noqa: BLE001
            # Best-effort: tag resolution failure must not break the query.
            # Log + audit so the failure is observable (not silently swallowed).
            _LOGGER.warning(
                "scope tag resolution failed (non-blocking): %s",
                exc,
                extra={
                    "plugin_namespace": plugin_namespace,
                    "tags": list(scope_tags),
                    "error": str(exc),
                },
            )
            if audit is not None:
                audit.log_decision(
                    category="scope_routing_error",
                    reason="tag_resolution_failed",
                    plugin_namespace=plugin_namespace,
                    error=str(exc),
                    extra={"tags": list(scope_tags)},
                )

    if not catalog_collections:
        return decision, False

    existing = {plan.collection for plan in decision.plans}
    added: list[str] = []
    new_plans = list(decision.plans)
    for collection in sorted(catalog_collections):
        if collection in existing:
            continue
        encoder = _encoder_for_collection(collection, encoder_registry)
        if encoder is None:
            continue
        new_plans.append(
            CollectionQueryPlan(
                collection=collection,
                encoder=encoder,
                top_k=top_k,
            )
        )
        added.append(collection)

    if not added:
        return decision, False

    if audit is not None and reason:
        audit.log_decision(
            category="scope_routing",
            reason=reason,
            plugin_namespace=plugin_namespace,
            extra={"added_collections": added},
        )

    return QueryRouteDecision(plans=tuple(new_plans)), True
