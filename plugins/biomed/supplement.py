"""Entity-anchored ANN supplement for biomed retrieval (filename-agnostic)."""

from __future__ import annotations

from typing import Any

from llama_index.core.schema import NodeWithScore, TextNode

from eagle_rag.index.milvus_pool import get_milvus_pool
from eagle_rag.plugins.milvus_ns import milvus_db_name
from eagle_rag.plugins.routing import CollectionQueryPlan, QueryRetrievalIntent
from eagle_rag.retrievers.hybrid_text_retriever import sparse_score
from plugins.biomed.scoring import entity_boost_score

__all__ = ["supplement_drug_document_hits", "supplement_entity_anchored_hits"]

_TEXT_OUTPUT_FIELDS = [
    "text",
    "path",
    "document_id",
    "kb_name",
    "source_type",
    "source_chunk_id",
    "chunk_type",
    "primary_drugs",
    "biomed_section",
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
    if not client.has_collection(plan.collection):
        return []
    raw = client.search(
        collection_name=plan.collection,
        data=[query_vector],
        anns_field="vector",
        limit=top_k,
        filter=expr,
        output_fields=_TEXT_OUTPUT_FIELDS,
    )
    return _hits_to_nodes(raw)


def _rerank_entity_hits(
    nodes: list[NodeWithScore],
    query: str,
    drug_terms: list[str],
) -> list[NodeWithScore]:
    if not nodes:
        return []
    scored: list[tuple[float, NodeWithScore]] = []
    for nws in nodes:
        meta = nws.node.metadata or {}
        if hasattr(nws.node, "get_content"):
            text = nws.node.get_content()
        else:
            text = str(getattr(nws.node, "text", ""))
        entity = entity_boost_score(meta, drug_terms)
        lexical = sparse_score(query, str(text or ""), extra_terms=drug_terms)
        dense = float(nws.score or 0.0)
        combined = entity * 2.0 + lexical + dense * 0.1
        scored.append((combined, NodeWithScore(node=nws.node, score=combined)))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [nws for _, nws in scored]


def _resolve_drug_terms(query: str) -> list[str]:
    from plugins.biomed.umls import match_drug_entities, match_entities, resolve_entity

    terms = list(match_drug_entities(query))
    if not terms:
        for entity in match_entities(query):
            resolved = resolve_entity(entity)
            related = [str(d) for d in (resolved.get("related_drugs") or [])[:4]]
            if related:
                terms = related
                break
    return list(dict.fromkeys(terms))


def _collections_for_intent(intent: QueryRetrievalIntent | None) -> list[tuple[str, str]]:
    workflow = intent.workflow if intent else "general"
    if workflow == "chemical":
        return [("eagle_chemical", "molformer")]
    suppress = set(intent.suppress_collections if intent else ())
    collections: list[tuple[str, str]] = [("eagle_text_biomed", "pubmedbert")]
    if "eagle_chemical" not in suppress:
        collections.append(("eagle_chemical", "molformer"))
    return collections


def supplement_entity_anchored_hits(
    query: str,
    *,
    kb_name: str | None,
    plugin_namespace: str,
    recall_top_k: int,
    intent: QueryRetrievalIntent | None = None,
) -> list[NodeWithScore]:
    """ANN within registry documents that match query drug entities (any filename)."""
    from eagle_rag.index.registry import lookup_document_ids_by_name_terms
    from plugins.biomed.query_intent import detect_retrieval_intent

    if intent is None:
        intent = detect_retrieval_intent(query)

    terms = _resolve_drug_terms(query)
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
    for collection, encoder in _collections_for_intent(intent):
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
    return _rerank_entity_hits(nodes, query, terms)


def supplement_drug_document_hits(
    query: str,
    *,
    kb_name: str | None,
    plugin_namespace: str,
    recall_top_k: int,
    intent: QueryRetrievalIntent | None = None,
) -> list[NodeWithScore]:
    """Backward-compatible alias for entity-anchored supplement."""
    return supplement_entity_anchored_hits(
        query,
        kb_name=kb_name,
        plugin_namespace=plugin_namespace,
        recall_top_k=recall_top_k,
        intent=intent,
    )
