"""Example RAG-only MCP tools for the industry plugin template."""

from __future__ import annotations

from typing import Any

from eagle_rag.config import get_settings
from eagle_rag.index.milvus_text_store import search_text
from eagle_rag.plugins.mcp_registry import register_mcp_tool

__all__ = ["template_retrieve_assets", "register_mcp_tools"]

_NAMESPACE = "stub-template"


@register_mcp_tool(
    namespace=_NAMESPACE,
    name="retrieve_assets",
    description=(
        "Retrieve ranked text chunks for a domain question. "
        "Returns structured context for a downstream Agent — never executes SQL or side effects."
    ),
    properties={
        "question": {
            "type": "string",
            "description": "Natural-language retrieval question.",
        },
        "kb_name": {
            "type": "string",
            "description": "Optional knowledge-base scope.",
        },
        "top_k": {
            "type": "integer",
            "description": "Maximum number of chunks to return.",
        },
    },
    required=["question"],
)
def template_retrieve_assets(
    question: str,
    kb_name: str | None = None,
    top_k: int = 5,
) -> dict[str, Any]:
    """ANN retrieve against Core ``eagle_text`` (template default)."""
    effective_kb = kb_name or get_settings().kb_name
    hits = search_text(question, top_k=max(1, min(int(top_k), 50)), kb_name=effective_kb)
    return {
        "question": question,
        "kb_name": effective_kb,
        "hits": [
            {
                "document_id": (hit.get("metadata") or {}).get("document_id"),
                "chunk_id": hit.get("node_id"),
                "score": hit.get("score"),
                "path": (hit.get("metadata") or {}).get("path"),
                "text": hit.get("text") or "",
            }
            for hit in hits
        ],
    }


def register_mcp_tools() -> None:
    """Explicit registration entrypoint (decorators already ran on import)."""
    _ = (template_retrieve_assets,)
