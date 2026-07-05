"""Document semantic-structure reconstruction.

Serves a document's parsed semantic tree (Knowhere ``doc_nav``) to the API. The
tree is read from the persisted ``documents.extra['doc_nav']`` when present
(written at ingest by ``knowhere_parse``); otherwise it is reconstructed on the
fly from the ``section_summary`` (or, failing that, all) text nodes indexed in
Milvus by nesting them along their ``path`` prefixes.

Also resolves a Knowhere table/visual chunk's HTML for preview: from MinIO
(``{document_id}/visual_chunks/{chunk_id}.html``) with a Milvus table-node
fallback.
"""

from __future__ import annotations

from typing import Any

from eagle_rag.index.milvus_text_store import fetch_text_nodes_by_document_id
from eagle_rag.index.milvus_visual_store import fetch_visual_by_document
from eagle_rag.index.registry import get_document_sync
from eagle_rag.storage.minio_client import get_object_bytes
from eagle_rag.telemetry import get_logger

__all__ = ["build_document_structure", "load_chunk_html"]

logger = get_logger(__name__)


def _reconstruct_tree(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rebuild a nested section tree from flat nodes by ``path`` prefix.

    Intermediate ancestors missing from ``nodes`` are synthesized so the tree is
    fully connected. Leaf metadata (``summary`` / ``chunk_count``) is attached to
    the node whose ``path`` matches exactly.
    """
    roots: list[dict[str, Any]] = []
    index: dict[str, dict[str, Any]] = {}

    def _path(node: dict[str, Any]) -> str:
        return (node.get("metadata") or {}).get("path") or ""

    for node in sorted(nodes, key=_path):
        meta = node.get("metadata") or {}
        path = meta.get("path") or ""
        if not path:
            continue
        segments = [s for s in path.split("/") if s]
        current_path = ""
        siblings = roots
        for depth, segment in enumerate(segments):
            current_path = f"{current_path}/{segment}" if current_path else segment
            existing = index.get(current_path)
            if existing is None:
                existing = {
                    "path": current_path,
                    "level": depth + 1,
                    "title": segment.strip(),
                    "summary": "",
                    "chunk_count": None,
                    "children": [],
                }
                index[current_path] = existing
                siblings.append(existing)
            siblings = existing["children"]
        leaf = index.get(path)
        if leaf is not None:
            summary = (meta.get("summary") or "").strip()
            if summary and not leaf["summary"]:
                leaf["summary"] = summary
            chunk_count = meta.get("chunk_count")
            if isinstance(chunk_count, int):
                leaf["chunk_count"] = chunk_count
            level = meta.get("level")
            if isinstance(level, int):
                leaf["level"] = level
    return roots


def build_document_structure(document_id: str, doc: dict[str, Any]) -> dict[str, Any]:
    """Assemble a document's semantic structure payload.

    Prefers the persisted ``extra['doc_nav']`` tree; falls back to a Milvus
    reconstruction from ``section_summary`` (or all) nodes. Visual tiles are
    attached as a flat list keyed by ``parent_section`` for the UI to anchor.

    Args:
        document_id: The document primary key.
        doc: The document registry row (``get_document`` result).

    Returns:
        A dict matching ``DocumentStructureOut``.
    """
    extra = doc.get("extra") or {}
    doc_nav = extra.get("doc_nav") if isinstance(extra, dict) else None

    kb_name = doc.get("kb_name") or "default"
    doc_name = (doc.get("name") or "").strip()
    path_prefix = doc_name if doc_name and "/" not in doc_name else None
    fetch_scope = {"kb_name": kb_name, "path_prefix": path_prefix}

    if isinstance(doc_nav, list) and doc_nav:
        sections = doc_nav
        source = "doc_nav"
    else:
        section_nodes = fetch_text_nodes_by_document_id(
            document_id, types=["section_summary"], **fetch_scope
        )
        if not section_nodes:
            section_nodes = fetch_text_nodes_by_document_id(document_id, **fetch_scope)
        sections = _reconstruct_tree(section_nodes)
        source = "reconstructed" if sections else "empty"

    visuals: list[dict[str, Any]] = []
    try:
        for row in fetch_visual_by_document(document_id):
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
    except Exception as exc:  # noqa: BLE001
        logger.warning("fetch visuals for structure failed doc=%s: %s", document_id, exc)

    source_uri = doc.get("source_uri") or ""
    has_source_file = bool(source_uri)

    return {
        "document_id": document_id,
        "name": doc.get("name"),
        "source_type": doc.get("source_type"),
        "pipeline": doc.get("pipeline"),
        "kb_name": doc.get("kb_name") or "default",
        "status": doc.get("status"),
        "source": source,
        "sections": sections,
        "visuals": visuals,
        "visual_count": len(visuals),
        "has_source_file": has_source_file,
    }


def load_chunk_html(document_id: str, chunk_id: str) -> bytes | None:
    """Load a Knowhere table/visual chunk's HTML for preview.

    Tries MinIO (``{document_id}/visual_chunks/{chunk_id}.html``) first, then
    falls back to the matching Milvus ``type == "table"`` node's stored HTML.
    Returns ``None`` when neither source has the chunk.
    """
    key = f"{document_id}/visual_chunks/{chunk_id}.html"
    try:
        data = get_object_bytes(key)
        if data:
            return data
    except Exception:  # noqa: BLE001
        logger.debug("chunk html not in MinIO: %s", key, exc_info=True)

    doc = get_document_sync(document_id) or {}
    kb_name = doc.get("kb_name") or "default"
    doc_name = (doc.get("name") or "").strip()
    path_prefix = doc_name if doc_name and "/" not in doc_name else None
    try:
        for node in fetch_text_nodes_by_document_id(
            document_id,
            types=["table"],
            kb_name=kb_name,
            path_prefix=path_prefix,
        ):
            if node.get("id") == chunk_id:
                text = node.get("text") or ""
                if text:
                    return text.encode("utf-8")
    except Exception:  # noqa: BLE001
        logger.debug("chunk html Milvus fallback failed doc=%s chunk=%s", document_id, chunk_id)
    return None
