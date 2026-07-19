"""Tag (keyword) catalog query endpoint.

Powers the *tag* dimension of the Q&A scope filter: lists keyword tags with hit
counts (chunk occurrences), knowledge-base coverage and document coverage. Tags
are derived from Knowhere-extracted chunk keywords aggregated in the
``document_keywords`` catalog.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from eagle_rag.api.schemas.tags import TagListResponse, TagOut
from eagle_rag.index.tag_catalog import list_tags
from eagle_rag.telemetry import get_logger

__all__ = ["router"]

logger = get_logger(__name__)

router = APIRouter(prefix="/tags", tags=["tags"])


@router.get("", response_model=TagListResponse)
async def list_tags_api(
    q: str | None = Query(default=None, description="Fuzzy match on keyword"),
    kb_name: str | None = Query(
        default=None, description="Filter by a single knowledge base (multi-tenant)"
    ),
    kb_names: list[str] | None = Query(
        default=None, description="Filter by multiple knowledge bases (union)"
    ),
    limit: int = Query(default=50, ge=1, le=500),
) -> TagListResponse:
    """List keyword tags ordered by hit count, optionally scoped to KBs / query."""
    names = list(kb_names or [])
    if kb_name:
        names.append(kb_name)
    try:
        rows = await list_tags(kb_names=names or None, q=q, limit=limit, plugin_namespace=None)
    except Exception:  # noqa: BLE001
        logger.exception("list_tags failed; database may be unavailable")
        return TagListResponse(items=[], total=0)
    items = [TagOut(**row) for row in rows]
    return TagListResponse(items=items, total=len(items))
