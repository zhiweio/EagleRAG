"""Attachments API."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from eagle_rag.api.schemas.attachments import AttachmentOut, AttachmentUploadResponse
from eagle_rag.api.schemas.common import DeletedResponse
from eagle_rag.attachments.store import (
    delete_attachment_sync,
    get_attachment,
    get_attachment_bytes_sync,
    store_attachment_sync,
)
from eagle_rag.attachments.validation import validate_image_attachment

router = APIRouter(tags=["attachments"])


@router.post("/attachments", response_model=AttachmentUploadResponse, status_code=201)
async def upload_attachment(
    file: UploadFile = File(...),
    session_id: str | None = Form(None),
) -> AttachmentUploadResponse:
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="empty file")
    mime = file.content_type or "application/octet-stream"
    file_name = file.filename or "upload"
    try:
        validate_image_attachment(data=data, mime=mime, file_name=file_name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result = await asyncio.to_thread(
        store_attachment_sync,
        data=data,
        file_name=file.filename or "upload",
        mime=mime,
        session_id=session_id,
    )
    return AttachmentUploadResponse.from_store(result)


@router.get("/attachments/{attachment_id}", response_model=AttachmentOut)
async def get_attachment_meta(attachment_id: str) -> AttachmentOut:
    meta = await get_attachment(attachment_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="attachment not found")
    return AttachmentOut.from_store(meta)


@router.get("/attachments/{attachment_id}/content")
async def get_attachment_content(attachment_id: str) -> Response:
    meta = await get_attachment(attachment_id)
    if meta is None:
        raise HTTPException(status_code=404, detail="attachment not found")
    data = await asyncio.to_thread(get_attachment_bytes_sync, attachment_id)
    if data is None:
        raise HTTPException(status_code=404, detail="attachment content not found")
    return Response(content=data, media_type=meta.get("mime", "application/octet-stream"))


@router.delete("/attachments/{attachment_id}", response_model=DeletedResponse)
async def delete_attachment(attachment_id: str) -> DeletedResponse:
    ok = await asyncio.to_thread(delete_attachment_sync, attachment_id)
    if not ok:
        raise HTTPException(status_code=404, detail="attachment not found")
    return DeletedResponse(deleted=True)
