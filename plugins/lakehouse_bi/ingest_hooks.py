"""Lakehouse BI ingest hooks: DDL and YAML asset parsing."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from eagle_rag.plugins.hookbus import HookContext

__all__ = [
    "LAKEHOUSE_CHUNK_TYPES",
    "lakehouse_chunk_transform",
    "lakehouse_parse_transform",
]

LAKEHOUSE_CHUNK_TYPES = frozenset(
    {
        "table_schema",
        "metric",
        "business_rule",
        "join_rule",
        "fewshot",
        "business_context",
        "semantic_model",
    }
)

_CREATE_TABLE_RE = re.compile(
    r"create\s+table\s+(?:(?P<db>\w+)\.)?(?:(?P<schema>\w+)\.)?(?P<table>\w+)",
    re.IGNORECASE,
)


def _asset_kind_from_path(file_path: str) -> str | None:
    suffix = Path(file_path).suffix.lower()
    if suffix in {".sql", ".ddl"}:
        return "ddl"
    if suffix in {".yaml", ".yml"}:
        return "yaml"
    return None


def _ddl_table_name(ddl: str) -> str | None:
    match = _CREATE_TABLE_RE.search(ddl)
    if match is None:
        return None
    return match.group("table")


def _ddl_columns(ddl: str) -> list[str]:
    """Best-effort column name extraction from a CREATE TABLE body."""
    match = re.search(r"\((.*)\)", ddl, re.IGNORECASE | re.DOTALL)
    if not match:
        return []
    body = match.group(1)
    cols: list[str] = []
    for line in body.split(","):
        token = line.strip().split()
        if not token:
            continue
        name = token[0].strip('`"[]')
        if name.upper() in {"PRIMARY", "FOREIGN", "UNIQUE", "CONSTRAINT", "KEY", "INDEX"}:
            continue
        cols.append(name)
    return cols


def _annotate_nodes(
    nodes: list[Any],
    *,
    chunk_type: str,
    title: str,
    source_path: str,
) -> list[Any]:
    for node in nodes:
        meta = dict(getattr(node, "metadata", None) or {})
        meta["type"] = chunk_type
        meta["chunk_type"] = chunk_type
        meta["path"] = meta.get("path") or f"lakehouse/{title}"
        meta["file_path"] = source_path
        meta.setdefault("asset_version", "v1")
        meta.setdefault("source_export_id", source_path)
        node.metadata = meta
        if hasattr(node, "text") and chunk_type == "table_schema":
            text = getattr(node, "text", "") or ""
            table = _ddl_table_name(text)
            if table:
                meta["table_name"] = table
            cols = _ddl_columns(text)
            if cols:
                meta["columns"] = cols
            node.metadata = meta
    return nodes


def _yaml_nodes_from_text(text: str, *, source_path: str) -> list[dict[str, Any]]:
    try:
        payload = yaml.safe_load(text)
    except yaml.YAMLError:
        return []
    if not isinstance(payload, dict):
        return []

    chunks: list[dict[str, Any]] = []
    mapping = {
        "semantic_models": "semantic_model",
        "metrics": "metric",
        "business_rules": "business_rule",
        "join_rules": "join_rule",
        "fewshots": "fewshot",
        "business_context": "business_context",
    }
    for key, chunk_type in mapping.items():
        entries = payload.get(key)
        if not entries:
            continue
        if not isinstance(entries, list):
            entries = [entries]
        for idx, entry in enumerate(entries):
            name = ""
            if isinstance(entry, dict):
                name = str(entry.get("name") or entry.get("title") or idx)
            body = yaml.safe_dump(entry, sort_keys=False, allow_unicode=True)
            chunks.append(
                {
                    "text": body,
                    "metadata": {
                        "type": chunk_type,
                        "chunk_type": chunk_type,
                        "path": f"lakehouse/{key}/{name}",
                        "file_path": source_path,
                        "asset_key": key,
                        "asset_name": name,
                    },
                }
            )
    return chunks


def lakehouse_parse_transform(ctx: HookContext, parse_result: Any, **kwargs: Any) -> Any:
    """Tag parse results for lakehouse DDL/YAML assets."""
    file_path = str(kwargs.get("file_path") or kwargs.get("file_name") or "")
    kind = _asset_kind_from_path(file_path)
    if kind is None:
        return parse_result

    manifest = getattr(parse_result, "manifest", None)
    if manifest is not None and hasattr(manifest, "metadata"):
        meta = dict(getattr(manifest, "metadata", None) or {})
        meta["lakehouse_asset_kind"] = kind
        manifest.metadata = meta
    return parse_result


def lakehouse_chunk_transform(ctx: HookContext, nodes: list[Any], **kwargs: Any) -> list[Any]:
    """Rewrite chunks for lakehouse DDL/YAML assets with typed metadata."""
    file_path = str(kwargs.get("file_path") or kwargs.get("file_name") or "")
    kind = _asset_kind_from_path(file_path)
    if kind is None:
        return nodes

    if kind == "ddl":
        return _annotate_nodes(
            nodes,
            chunk_type="table_schema",
            title=Path(file_path).stem or "ddl",
            source_path=file_path,
        )

    out: list[Any] = []
    for node in nodes:
        text = getattr(node, "text", "") or ""
        yaml_chunks = _yaml_nodes_from_text(text, source_path=file_path)
        if not yaml_chunks:
            out.append(node)
            continue
        from llama_index.core.schema import TextNode

        for chunk in yaml_chunks:
            out.append(
                TextNode(
                    text=chunk["text"],
                    metadata=chunk["metadata"],
                )
            )
    return out or nodes
