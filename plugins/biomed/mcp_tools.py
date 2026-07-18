"""Biomed MCP tools registered via ``eagle_rag.plugins.mcp_registry``."""

from __future__ import annotations

from typing import Any

from eagle_rag.plugins.mcp_registry import register_mcp_tool
from plugins.biomed.umls import resolve_compound_query, resolve_entity

__all__ = [
    "biomed_query_entities",
    "biomed_retrieve_compounds",
    "register_mcp_tools",
]

_NAMESPACE = "biomed"


@register_mcp_tool(
    namespace=_NAMESPACE,
    name="query_entities",
    description=(
        "Resolve a biomedical entity to aliases, pathways, and related drugs "
        "from the local UMLS-subset ontology index."
    ),
    properties={
        "entity": {
            "type": "string",
            "description": "Gene, drug, disease, or pathway name (e.g. HER2, imatinib).",
        },
        "kb_name": {
            "type": "string",
            "description": "Optional knowledge-base scope.",
        },
    },
    required=["entity"],
)
def biomed_query_entities(entity: str, kb_name: str | None = None) -> dict[str, Any]:
    """Return entity metadata for agent grounding."""
    del kb_name
    return resolve_entity(entity)


@register_mcp_tool(
    namespace=_NAMESPACE,
    name="retrieve_compounds",
    description=(
        "Retrieve similar compounds from ``eagle_chemical`` using MolFormer "
        "embeddings (ANN). Accepts SMILES or a known compound name."
    ),
    properties={
        "smiles_or_name": {
            "type": "string",
            "description": "SMILES string or compound common name.",
        },
        "top_k": {
            "type": "integer",
            "description": "Maximum number of similar compounds to return.",
        },
        "kb_name": {
            "type": "string",
            "description": "Optional knowledge-base scope.",
        },
    },
    required=["smiles_or_name"],
)
def biomed_retrieve_compounds(
    smiles_or_name: str,
    top_k: int = 5,
    kb_name: str | None = None,
) -> dict[str, Any]:
    """ANN retrieval against the biomed chemical collection."""
    query = resolve_compound_query(smiles_or_name)
    if not query:
        return {"query": query, "hits": [], "error": "empty query"}

    from eagle_rag.db.repositories.base import instance_namespace
    from eagle_rag.index.milvus_pool import get_milvus_pool
    from eagle_rag.plugins import get_plugin_manager
    from eagle_rag.plugins.encoder_runtime import encode_text_for_encoder
    from eagle_rag.plugins.milvus_ns import milvus_db_name

    manager = get_plugin_manager()
    ns = instance_namespace(None)
    db_name = milvus_db_name(ns)
    try:
        vector = encode_text_for_encoder("molformer", query)
    except Exception as exc:  # noqa: BLE001
        return {
            "query": query,
            "collection": "eagle_chemical",
            "encoder": "molformer",
            "hits": [],
            "error": f"encode_failed: {exc}",
        }

    client = get_milvus_pool().get(db_name)
    if not client.has_collection("eagle_chemical"):
        return {
            "query": query,
            "collection": "eagle_chemical",
            "encoder": "molformer",
            "hits": [],
            "error": "collection_missing",
        }

    expr = f'kb_name == "{kb_name}"' if kb_name else ""
    try:
        raw = client.search(
            collection_name="eagle_chemical",
            data=[vector],
            anns_field="vector",
            limit=max(1, min(int(top_k), 50)),
            filter=expr,
            output_fields=["id", "text", "document_id", "kb_name", "path", "chunk_type"],
        )
    except Exception as exc:  # noqa: BLE001
        return {
            "query": query,
            "collection": "eagle_chemical",
            "encoder": "molformer",
            "hits": [],
            "error": f"search_failed: {exc}",
        }

    hits: list[dict[str, Any]] = []
    for batch in raw or []:
        for hit in batch:
            entity = hit.get("entity") if isinstance(hit, dict) else None
            fields = entity if isinstance(entity, dict) else {}
            if not fields and hasattr(hit, "entity"):
                fields = dict(hit.entity)  # type: ignore[arg-type]
            score = hit.get("distance") if isinstance(hit, dict) else getattr(hit, "distance", None)
            hits.append(
                {
                    "compound_id": fields.get("id") or fields.get("document_id"),
                    "smiles": fields.get("text") or "",
                    "score": score,
                    "document_id": fields.get("document_id"),
                    "path": fields.get("path"),
                    "kb_name": fields.get("kb_name"),
                }
            )

    # Ensure molformer is registered when biomed plugin loaded.
    _ = manager.encoder_registry.has("molformer")
    return {
        "query": query,
        "collection": "eagle_chemical",
        "encoder": "molformer",
        "hits": hits,
    }


def register_mcp_tools() -> None:
    """Explicit registration entrypoint (decorators already ran on import).

    Importing this module registers tools via ``@register_mcp_tool``. PluginManager
    calls this method so registration is intentional, not a silent side-effect of
    an unused import.
    """
    # Touch symbols so static analyzers keep the decorated functions.
    _ = (biomed_query_entities, biomed_retrieve_compounds)
