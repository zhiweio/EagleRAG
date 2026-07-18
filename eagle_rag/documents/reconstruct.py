"""Cross-collection document reconstruction for structure endpoints."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from typing import Any

from eagle_rag.config import get_settings
from eagle_rag.index.document_structure import _reconstruct_tree
from eagle_rag.index.milvus_pool import get_milvus_pool
from eagle_rag.index.milvus_text_store import (
    _escape_milvus_str,
    _query_nodes_by_expr,
    fetch_text_nodes_by_document_id,
)
from eagle_rag.index.milvus_visual_store import fetch_visual_by_document
from eagle_rag.plugins import get_plugin_manager
from eagle_rag.plugins.milvus_ns import milvus_db_name
from eagle_rag.telemetry import get_logger

__all__ = ["reconstruct_document", "list_document_collections"]

logger = get_logger(__name__)


@lru_cache(maxsize=16)
def list_document_collections(plugin_namespace: str) -> tuple[str, ...]:
    """Return base + specialized Milvus collections for a namespace (cached)."""
    settings = get_settings()
    mgr = get_plugin_manager()
    specialized = mgr.get_specialized_collections(plugin_namespace)
    ordered = (
        settings.milvus.text_collection,
        settings.milvus.visual_collection,
        *specialized,
    )
    seen: set[str] = set()
    out: list[str] = []
    for name in ordered:
        if name not in seen:
            seen.add(name)
            out.append(name)
    return tuple(out)


def _is_visual_collection(collection: str) -> bool:
    """True for Core visual + specialized collections bound to a visual encoder dim."""
    settings = get_settings()
    if collection == settings.milvus.visual_collection:
        return True
    try:
        mgr = get_plugin_manager()
        col_dim = mgr.encoder_registry.collection_dim(collection)
        if col_dim is None:
            return False
        for name in mgr.encoder_registry.names():
            info = mgr.encoder_registry.get(name)
            if info.modality == "visual" and info.dim == col_dim:
                return True
    except Exception:  # noqa: BLE001
        logger.debug("visual collection probe failed for %s", collection, exc_info=True)
    return False


def _normalize_fetched_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for node in nodes:
        meta = dict(node.get("metadata") or {})
        if "type" not in meta and meta.get("chunk_type"):
            meta["type"] = meta["chunk_type"]
        out.append({**node, "metadata": meta})
    return out


def _fetch_specialized_text_nodes(
    document_id: str,
    collection: str,
    *,
    db_name: str,
    kb_name: str | None = None,
    path_prefix: str | None = None,
    types: list[str] | None = None,
) -> list[dict[str, Any]]:
    client = get_milvus_pool().get(db_name)
    if not client.has_collection(collection):
        return []

    safe_id = _escape_milvus_str(document_id)
    nodes: list[dict[str, Any]] = []

    try:
        for field in ("document_id", "doc_id"):
            expr = f'{field} == "{safe_id}"'
            if types:
                joined = ", ".join(f'"{_escape_milvus_str(t)}"' for t in types)
                expr += f" and (type in [{joined}] or chunk_type in [{joined}])"
            nodes = _query_nodes_by_expr(
                client,
                collection,
                expr,
                document_id=document_id,
                types=types,
                limit=None,
                filter_by_node_content=False,
            )
            if nodes:
                return _normalize_fetched_nodes(nodes)

        scope_expr: str | None = None
        if kb_name:
            scope_expr = f'kb_name == "{_escape_milvus_str(kb_name)}"'
        elif path_prefix:
            scope_expr = f'path like "{_escape_milvus_str(path_prefix)}%"'

        if scope_expr is None:
            return []

        nodes = _query_nodes_by_expr(
            client,
            collection,
            scope_expr,
            document_id=document_id,
            types=types,
            limit=None,
            filter_by_node_content=True,
        )
        return _normalize_fetched_nodes(nodes)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "specialized text fetch failed doc=%s collection=%s: %s",
            document_id,
            collection,
            exc,
        )
    return []


def _fetch_specialized_visual_rows(
    document_id: str,
    collection: str,
    *,
    db_name: str,
    limit: int = 4096,
) -> list[dict[str, Any]]:
    client = get_milvus_pool().get(db_name)
    if not client.has_collection(collection):
        return []
    safe_id = document_id.replace('"', '\\"')
    expr = f'document_id == "{safe_id}"'
    try:
        return list(
            client.query(
                collection,
                filter=expr,
                output_fields=[
                    "image_id",
                    "image_path",
                    "document_id",
                    "page",
                    "position",
                    "kb_name",
                    "year",
                    "source_type",
                    "chunk_type",
                    "parent_section",
                    "content_summary",
                    "source_chunk_id",
                ],
                limit=limit,
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "specialized visual fetch failed doc=%s collection=%s: %s",
            document_id,
            collection,
            exc,
        )
        return []


def _fetch_collection(
    collection: str,
    document_id: str,
    *,
    plugin_namespace: str,
    kb_name: str | None,
    path_prefix: str | None,
) -> tuple[str, str, list[dict[str, Any]]]:
    settings = get_settings()
    if collection == settings.milvus.text_collection:
        nodes = fetch_text_nodes_by_document_id(
            document_id,
            kb_name=kb_name,
            path_prefix=path_prefix,
        )
        return collection, "text", nodes

    if collection == settings.milvus.visual_collection:
        rows = fetch_visual_by_document(document_id)
        return collection, "visual", rows

    db_name = milvus_db_name(plugin_namespace)
    if _is_visual_collection(collection):
        rows = _fetch_specialized_visual_rows(document_id, collection, db_name=db_name)
        return collection, "visual", rows

    nodes = _fetch_specialized_text_nodes(
        document_id,
        collection,
        db_name=db_name,
        kb_name=kb_name,
        path_prefix=path_prefix,
    )
    return collection, "text", nodes


def reconstruct_document(document_id: str, doc: dict[str, Any]) -> dict[str, Any]:
    """Fan out across namespace collections and rebuild a document structure payload.

    Prefers persisted ``documents.extra['doc_nav']`` for the section skeleton; otherwise
    reconstructs the tree from ``section_summary`` nodes aggregated across all text
    collections. Visual anchors are merged from every visual collection in the namespace.
    """
    extra = doc.get("extra") or {}
    doc_nav = extra.get("doc_nav") if isinstance(extra, dict) else None

    kb_name = doc.get("kb_name") or "default"
    plugin_namespace = doc.get("plugin_namespace") or get_settings().plugins.default_namespace
    doc_name = (doc.get("name") or "").strip()
    path_prefix = doc_name if doc_name and "/" not in doc_name else None

    collections = list_document_collections(plugin_namespace)
    fetch_results: list[tuple[str, str, list[dict[str, Any]]]] = []

    max_workers = min(len(collections), 8) or 1
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(
                _fetch_collection,
                coll,
                document_id,
                plugin_namespace=plugin_namespace,
                kb_name=kb_name,
                path_prefix=path_prefix,
            ): coll
            for coll in collections
        }
        for future in as_completed(futures):
            try:
                fetch_results.append(future.result())
            except Exception as exc:  # noqa: BLE001
                coll = futures[future]
                logger.warning("collection fetch failed doc=%s coll=%s: %s", document_id, coll, exc)

    section_nodes: list[dict[str, Any]] = []
    fallback_nodes: list[dict[str, Any]] = []
    visuals: list[dict[str, Any]] = []

    for _coll, kind, payload in fetch_results:
        if kind == "visual":
            for row in payload:
                visuals.append(
                    {
                        "image_id": row.get("image_id"),
                        "page": row.get("page"),
                        "position": row.get("position"),
                        "chunk_type": row.get("chunk_type"),
                        "parent_section": row.get("parent_section"),
                        "content_summary": row.get("content_summary"),
                        "source_chunk_id": row.get("source_chunk_id"),
                    }
                )
            continue

        for node in payload:
            meta = node.get("metadata") or {}
            chunk_type = meta.get("type") or meta.get("chunk_type")
            if chunk_type == "section_summary":
                section_nodes.append(node)
            else:
                fallback_nodes.append(node)

    if isinstance(doc_nav, list) and doc_nav:
        sections = doc_nav
        source = "doc_nav"
    else:
        tree_nodes = section_nodes or fallback_nodes
        if not section_nodes and fallback_nodes:
            tree_nodes = (
                fetch_text_nodes_by_document_id(
                    document_id,
                    types=["section_summary"],
                    kb_name=kb_name,
                    path_prefix=path_prefix,
                )
                or fallback_nodes
            )
        sections = _reconstruct_tree(tree_nodes)
        source = "reconstructed" if sections else "empty"

    source_uri = doc.get("source_uri") or ""
    return {
        "document_id": document_id,
        "name": doc.get("name"),
        "source_type": doc.get("source_type"),
        "pipeline": doc.get("pipeline"),
        "kb_name": kb_name,
        "status": doc.get("status"),
        "source": source,
        "sections": sections,
        "visuals": visuals,
        "visual_count": len(visuals),
        "has_source_file": bool(source_uri),
    }
