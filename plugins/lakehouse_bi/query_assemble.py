"""Lakehouse BI semantic context assembly for query-time enrichment."""

from __future__ import annotations

from typing import Any

from llama_index.core.vector_stores import FilterOperator, MetadataFilter

from eagle_rag.config import get_settings
from eagle_rag.index.milvus_text_store import search_text
from eagle_rag.plugins.hookbus import HookContext

__all__ = ["assemble_semantic_context", "lakehouse_query_assemble"]

_DATA_QUERY_KEYWORDS = (
    "metric",
    "kpi",
    "revenue",
    "table",
    "schema",
    "column",
    "join",
    "sql",
    "dashboard",
    "指标",
    "口径",
    "表结构",
    "字段",
    "关联",
)


def _looks_like_data_query(query: str) -> bool:
    lowered = query.lower()
    return any(token in lowered for token in _DATA_QUERY_KEYWORDS)


def _search_typed(
    question: str,
    *,
    kb_name: str | None,
    chunk_type: str,
    top_k: int = 4,
) -> list[dict[str, Any]]:
    filters = [MetadataFilter(key="type", value=chunk_type, operator=FilterOperator.EQ)]
    return search_text(question, top_k=top_k, kb_name=kb_name, filters=filters)


def assemble_semantic_context(
    question: str,
    *,
    kb_name: str | None = None,
    top_k: int = 4,
) -> dict[str, Any]:
    """Hybrid recall of lakehouse semantic assets from ``eagle_text``."""
    effective_kb = kb_name or get_settings().kb_name
    tables = _search_typed(question, kb_name=effective_kb, chunk_type="table_schema", top_k=top_k)
    metrics = _search_typed(question, kb_name=effective_kb, chunk_type="metric", top_k=top_k)
    business_rules = _search_typed(
        question, kb_name=effective_kb, chunk_type="business_rule", top_k=top_k
    )
    join_rules = _search_typed(question, kb_name=effective_kb, chunk_type="join_rule", top_k=top_k)
    fewshots = _search_typed(question, kb_name=effective_kb, chunk_type="fewshot", top_k=top_k)
    enums = _search_typed(
        question, kb_name=effective_kb, chunk_type="business_context", top_k=top_k
    )

    sources: list[dict[str, str]] = []
    for bucket in (tables, metrics, business_rules, join_rules, fewshots, enums):
        for hit in bucket:
            meta = hit.get("metadata") or {}
            sources.append(
                {
                    "document_id": str(meta.get("document_id") or ""),
                    "chunk_id": str(hit.get("node_id") or ""),
                    "path": str(meta.get("path") or ""),
                }
            )

    return {
        "tables": [
            {
                "name": (hit.get("metadata") or {}).get("table_name")
                or (hit.get("metadata") or {}).get("asset_name")
                or "",
                "schema": (hit.get("metadata") or {}).get("schema"),
                "columns": list((hit.get("metadata") or {}).get("columns") or []),
                "ddl": hit.get("text") or "",
            }
            for hit in tables
        ],
        "metrics": [
            {
                "name": (hit.get("metadata") or {}).get("asset_name") or "",
                "type": (hit.get("metadata") or {}).get("type") or "metric",
                "formula": hit.get("text") or "",
                "description": (hit.get("metadata") or {}).get("summary") or "",
            }
            for hit in metrics
        ],
        "business_rules": [hit.get("text") or "" for hit in business_rules],
        "join_rules": [hit.get("text") or "" for hit in join_rules],
        "fewshots": [hit.get("text") or "" for hit in fewshots],
        "enums": [hit.get("text") or "" for hit in enums],
        "sources": sources,
    }


def lakehouse_query_assemble(
    ctx: HookContext,
    query: str,
    *,
    kb_name: str | None = None,
    **kwargs: Any,
) -> str | None:
    """Append a compact semantic-context hint when the query looks data-oriented."""
    del kwargs
    if ctx.plugin_namespace != "lakehouse-bi":
        return None
    if not _looks_like_data_query(query):
        return None

    pack = assemble_semantic_context(query, kb_name=kb_name or ctx.kb_name, top_k=3)
    table_names = [t["name"] for t in pack["tables"] if t.get("name")]
    metric_names = [m["name"] for m in pack["metrics"] if m.get("name")]
    if not table_names and not metric_names:
        return None

    parts: list[str] = []
    if table_names:
        parts.append(f"tables={', '.join(table_names[:5])}")
    if metric_names:
        parts.append(f"metrics={', '.join(metric_names[:5])}")
    return "Lakehouse semantic context: " + "; ".join(parts)
