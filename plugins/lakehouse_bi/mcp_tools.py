"""Lakehouse BI MCP tools (read-only semantic retrieval)."""

from __future__ import annotations

from typing import Any

from eagle_rag.config import get_settings
from eagle_rag.index.milvus_text_store import search_text
from eagle_rag.plugins.mcp_registry import register_mcp_tool
from plugins.lakehouse_bi.query_assemble import assemble_semantic_context

__all__ = [
    "lakehouse_bi_query_semantic_context",
    "lakehouse_bi_retrieve_historical_analysis",
    "register_mcp_tools",
]

_NAMESPACE = "lakehouse-bi"


@register_mcp_tool(
    namespace=_NAMESPACE,
    name="query_semantic_context",
    description=(
        "Retrieve structured semantic context for Agentic BI: tables, metrics, "
        "business rules, join rules, fewshots, and enum mappings."
    ),
    properties={
        "question": {
            "type": "string",
            "description": "Natural-language BI question or metric intent.",
        },
        "kb_name": {
            "type": "string",
            "description": "Optional knowledge-base scope.",
        },
    },
    required=["question"],
)
def lakehouse_bi_query_semantic_context(
    question: str,
    kb_name: str | None = None,
) -> dict[str, Any]:
    """Return a semantic context pack for downstream SQL generation."""
    effective_kb = kb_name or get_settings().kb_name
    return assemble_semantic_context(question, kb_name=effective_kb, top_k=5)


@register_mcp_tool(
    namespace=_NAMESPACE,
    name="retrieve_historical_analysis",
    description=(
        "Retrieve historical analysis reports and attribution notes previously "
        "ingested as unstructured business documents."
    ),
    properties={
        "topic": {
            "type": "string",
            "description": "Analysis topic or business question to match.",
        },
        "kb_name": {
            "type": "string",
            "description": "Optional knowledge-base scope.",
        },
    },
    required=["topic"],
)
def lakehouse_bi_retrieve_historical_analysis(
    topic: str,
    kb_name: str | None = None,
) -> list[dict[str, Any]]:
    """Return ranked historical analysis chunks."""
    effective_kb = kb_name or get_settings().kb_name
    hits = search_text(topic, top_k=8, kb_name=effective_kb)
    out: list[dict[str, Any]] = []
    for hit in hits:
        meta = hit.get("metadata") or {}
        chunk_type = meta.get("type") or meta.get("chunk_type") or ""
        if chunk_type not in ("business_context", "fewshot", "text", ""):
            continue
        out.append(
            {
                "document_id": meta.get("document_id"),
                "chunk_id": hit.get("node_id"),
                "path": meta.get("path"),
                "score": hit.get("score"),
                "summary": meta.get("summary") or "",
                "text": hit.get("text") or "",
            }
        )
    return out


def register_mcp_tools() -> None:
    """Explicit registration entrypoint (decorators already ran on import).

    Importing this module registers tools via ``@register_mcp_tool``. PluginManager
    calls this method so registration is intentional, not a silent side-effect of
    an unused import.
    """
    _ = (lakehouse_bi_query_semantic_context, lakehouse_bi_retrieve_historical_analysis)
