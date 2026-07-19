"""Targeted drug-document ANN supplement for biomed retrieval."""

from __future__ import annotations

from typing import Any

from llama_index.core.schema import NodeWithScore, TextNode

from eagle_rag.index.milvus_pool import get_milvus_pool
from eagle_rag.plugins.milvus_ns import milvus_db_name
from eagle_rag.plugins.routing import CollectionQueryPlan

__all__ = ["supplement_drug_document_hits"]

_TEXT_OUTPUT_FIELDS = [
    "text",
    "path",
    "document_id",
    "kb_name",
    "source_type",
    "source_chunk_id",
    "chunk_type",
    "primary_drugs",
]


def _hits_to_nodes(raw: Any) -> list[NodeWithScore]:
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
        text = entity.get("text") or ""
        node = TextNode(text=text, metadata=metadata)
        nodes.append(NodeWithScore(node=node, score=score))
    return nodes


def _encode_query(encoder_name: str, query: str) -> list[float]:
    from eagle_rag.plugins.encoder_runtime import encode_text_for_encoder

    return encode_text_for_encoder(encoder_name, query)


def _search_collection(
    plan: CollectionQueryPlan,
    query: str,
    *,
    plugin_namespace: str,
    kb_name: str | None,
    doc_ids: list[str],
    top_k: int,
) -> list[NodeWithScore]:
    query_vector = _encode_query(plan.encoder, query)
    if not query_vector:
        return []

    quoted = ", ".join(f'"{doc_id}"' for doc_id in doc_ids)
    expr_parts = [f"document_id in [{quoted}]"]
    if kb_name is not None:
        expr_parts.insert(0, f'kb_name == "{kb_name}"')
    expr = " and ".join(expr_parts)

    client = get_milvus_pool().get(milvus_db_name(plugin_namespace))
    raw = client.search(
        collection_name=plan.collection,
        data=[query_vector],
        anns_field="vector",
        limit=top_k,
        filter=expr,
        output_fields=_TEXT_OUTPUT_FIELDS,
    )
    return _hits_to_nodes(raw)


def supplement_drug_document_hits(
    query: str,
    *,
    kb_name: str | None,
    plugin_namespace: str,
    recall_top_k: int,
) -> list[NodeWithScore]:
    """ANN within registry documents whose names match query drug entities."""
    from eagle_rag.index.registry import lookup_document_ids_by_name_terms
    from plugins.biomed.umls import match_drug_entities, match_entities, resolve_entity

    terms = list(match_drug_entities(query))
    if not terms:
        for entity in match_entities(query):
            resolved = resolve_entity(entity)
            related = [str(d) for d in (resolved.get("related_drugs") or [])[:4]]
            if related:
                terms = related
                break
    terms = list(dict.fromkeys(terms))
    if not terms:
        return []

    doc_ids = lookup_document_ids_by_name_terms(
        terms,
        kb_name=kb_name,
        plugin_namespace=plugin_namespace,
    )
    if not doc_ids:
        return []

    nodes: list[NodeWithScore] = []
    limit = min(recall_top_k, max(len(doc_ids) * 4, 8))
    for collection, encoder in (
        ("eagle_text_biomed", "pubmedbert"),
        ("eagle_chemical", "molformer"),
    ):
        plan = CollectionQueryPlan(collection=collection, encoder=encoder, top_k=recall_top_k)
        try:
            nodes.extend(
                _search_collection(
                    plan,
                    query,
                    plugin_namespace=plugin_namespace,
                    kb_name=kb_name,
                    doc_ids=doc_ids,
                    top_k=limit,
                )
            )
        except Exception:  # noqa: BLE001
            continue
    return nodes
