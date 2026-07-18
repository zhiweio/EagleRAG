"""Document and image query endpoints.

Exposes two ``APIRouter`` instances:

- ``router`` (``/documents``): document list / detail / delete.
- ``images_router`` (``/images``): Tile PNG raw bytes and metadata.
"""

from __future__ import annotations

import asyncio
import mimetypes
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import RedirectResponse

from eagle_rag.api.schemas.common import DeletedResponse
from eagle_rag.api.schemas.documents import (
    DocumentListResponse,
    DocumentOut,
    DocumentStructureOut,
    ImageMetaOut,
)
from eagle_rag.documents.reconstruct import reconstruct_document
from eagle_rag.images.store import get_image_bytes, get_image_meta
from eagle_rag.index.document_structure import load_chunk_html
from eagle_rag.index.registry import count_documents, delete_document, get_document, list_documents
from eagle_rag.storage.minio_client import get_object_bytes

__all__ = ["router", "images_router"]

router = APIRouter(prefix="/documents", tags=["documents"])
images_router = APIRouter(prefix="/images", tags=["images"])


@router.get("", response_model=DocumentListResponse)
async def list_documents_api(
    q: str | None = Query(default=None, description="Fuzzy match on document name"),
    kb_name: str | None = Query(
        default=None, description="Filter by knowledge base (multi-tenant)"
    ),
    source_type: str | None = Query(
        default=None, description="policy|financial|business|bidding|tax|other"
    ),
    pipeline: str | None = Query(default=None, description="knowhere|pixelrag"),
    status: str | None = Query(default=None, description="pending|indexing|ready|failed"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> DocumentListResponse:
    """List documents with filtering and pagination."""
    filters = {
        "q": q,
        "kb_name": kb_name,
        "source_type": source_type,
        "pipeline": pipeline,
        "status": status,
    }
    items, total = await asyncio.gather(
        list_documents(**filters, limit=limit, offset=offset),
        count_documents(**filters),
    )
    return DocumentListResponse(
        items=[DocumentOut.from_store(d) for d in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{document_id}", response_model=DocumentOut)
async def get_document_api(document_id: str) -> DocumentOut:
    """Get a single document by id."""
    doc = await get_document(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"document not found: {document_id}")
    return DocumentOut.from_store(doc)


@router.get("/{document_id}/structure", response_model=DocumentStructureOut)
async def get_document_structure_api(document_id: str) -> DocumentStructureOut:
    """Return a document's parsed semantic tree (section hierarchy + visual anchors)."""
    doc = await get_document(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"document not found: {document_id}")
    result = await asyncio.to_thread(reconstruct_document, document_id, doc)
    return DocumentStructureOut.model_validate(result)


@router.get("/{document_id}/file")
async def get_document_file_api(document_id: str) -> Response:
    """Return (or redirect to) the original ingested file for inline preview.

    Resolves ``source_uri``: an ``http(s)`` URL is redirected to; anything else
    is treated as a MinIO object key and streamed back with a guessed MIME type.
    """
    doc = await get_document(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"document not found: {document_id}")
    source_uri = doc.get("source_uri")
    if not source_uri:
        raise HTTPException(status_code=404, detail="document has no stored source file")
    if source_uri.startswith(("http://", "https://")):
        return RedirectResponse(url=source_uri, status_code=307)
    try:
        data = await asyncio.to_thread(get_object_bytes, source_uri)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"file read failed: {exc}") from exc
    name = doc.get("name") or document_id
    media_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
    headers = {"Content-Disposition": f"inline; filename*=UTF-8''{quote(name)}"}
    return Response(content=data, media_type=media_type, headers=headers)


@router.get("/{document_id}/chunks/{chunk_id}")
async def get_document_chunk_html_api(document_id: str, chunk_id: str) -> Response:
    """Return a Knowhere table/visual chunk's HTML for inline preview."""
    doc = await get_document(document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"document not found: {document_id}")
    data = await asyncio.to_thread(load_chunk_html, document_id, chunk_id)
    if data is None:
        raise HTTPException(status_code=404, detail=f"chunk not found: {chunk_id}")
    return Response(content=data, media_type="text/html; charset=utf-8")


@router.delete("/{document_id}", response_model=DeletedResponse)
async def delete_document_api(document_id: str) -> DeletedResponse:
    """Delete a document record."""
    deleted = await delete_document(document_id)
    return DeletedResponse(deleted=deleted)


@images_router.get("/{image_id}")
async def get_image_bytes_api(image_id: str) -> Response:
    """Return raw Tile PNG bytes."""
    meta = await get_image_meta(image_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"image not found: {image_id}")
    try:
        data = await asyncio.to_thread(get_image_bytes, image_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"image read failed: {exc}") from exc
    return Response(content=data, media_type="image/png")


@images_router.get("/{image_id}/meta", response_model=ImageMetaOut)
async def get_image_meta_api(image_id: str) -> ImageMetaOut:
    """Return image metadata."""
    meta = await get_image_meta(image_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"image not found: {image_id}")
    return ImageMetaOut.from_store(meta)
