"""Tile PNG storage and metadata.

Write strategy prefers MinIO when available, otherwise falls back to local
``settings.storage.image_store``. ``store_tile`` / ``get_image_bytes`` are
synchronous (Celery / internal calls) and use ``sync_execute`` / ``sync_fetchone``;
query interfaces (``get_image_meta`` / ``list_images_by_document`` /
``get_image_url``) are asynchronous (FastAPI uses ``acquire_async``).

Table schema is managed by Alembic + SQLModel, see ``eagle_rag.db.models.images``.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from eagle_rag.config import get_settings
from eagle_rag.db import (
    async_fetch,
    async_fetchrow,
    sync_execute,
    sync_fetchone,
)

__all__ = [
    "ensure_image_dir",
    "store_tile",
    "get_image_meta",
    "get_image_bytes",
    "list_images_by_document",
    "get_image_url",
]


def _resolve_kb(kb_name: str | None) -> str:
    """Fall back to global ``settings.kb_name`` when ``kb_name`` is None."""
    return kb_name if kb_name is not None else get_settings().kb_name


def ensure_image_dir() -> Path:
    """Ensure ``settings.storage.image_store`` exists and return its ``Path``."""
    image_store = Path(get_settings().storage.image_store)
    image_store.mkdir(parents=True, exist_ok=True)
    return image_store


# ---------------------------------------------------------------------------
# Writes (synchronous, called by Celery / PixelRAG adapter)
# ---------------------------------------------------------------------------


def store_tile(
    image_id: str,
    document_id: str,
    *,
    data: bytes,
    kb_name: str | None = None,
    page: int | None = None,
    position: str | None = None,
    width: int | None = None,
    height: int | None = None,
    object_key: str | None = None,
) -> dict[str, Any]:
    """Store a Tile PNG and register its metadata.

    Write strategy: when ``object_key`` is provided or MinIO is available,
    upload to MinIO and record ``object_key``; otherwise persist locally to
    ``{image_store}/{document_id}/{image_id}.png`` and record ``local_path``.
    Finally insert a row into the ``images`` table.

    Returns ``{"image_id":..., "object_key":..., "local_path":..., "url":...}``
    where ``url`` prefers a presigned URL and falls back to the local path.
    """
    ensure_image_dir()
    obj_key: str | None = None
    local_path: str | None = None
    url: str | None = None

    # Prefer MinIO: an explicit object_key forces MinIO; otherwise attempt upload.
    try:
        from eagle_rag.storage.minio_client import ensure_bucket, get_object_url, upload_bytes

        key = object_key or f"{document_id}/{image_id}.png"
        ensure_bucket()
        upload_bytes(key, data, content_type="image/png")
        obj_key = key
        try:
            url = get_object_url(obj_key)
        except Exception:
            url = None
    except Exception:
        # MinIO unavailable -> fall back to local storage; clear object_key.
        obj_key = None
        doc_dir = Path(get_settings().storage.image_store) / document_id
        doc_dir.mkdir(parents=True, exist_ok=True)
        local_file = doc_dir / f"{image_id}.png"
        local_file.write_bytes(data)
        local_path = str(local_file)
        url = local_path

    kb = _resolve_kb(kb_name)
    sync_execute(
        "INSERT INTO images "
        "(image_id, document_id, page, position, object_key, local_path, width, height, kb_name) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (image_id) DO UPDATE SET "
        "page = EXCLUDED.page, "
        "position = EXCLUDED.position, "
        "object_key = EXCLUDED.object_key, "
        "local_path = EXCLUDED.local_path, "
        "width = EXCLUDED.width, "
        "height = EXCLUDED.height, "
        "kb_name = EXCLUDED.kb_name",
        (image_id, document_id, page, position, obj_key, local_path, width, height, kb),
    )
    return {
        "image_id": image_id,
        "object_key": obj_key,
        "local_path": local_path,
        "url": url,
    }


# ---------------------------------------------------------------------------
# Queries (asynchronous, used by FastAPI)
# ---------------------------------------------------------------------------


_IMAGE_COLUMNS = (
    "image_id, document_id, page, position, object_key, local_path, "
    "width, height, created_at, kb_name"
)


def _image_from_row(row: Any) -> dict[str, Any]:
    return {
        "image_id": row["image_id"],
        "document_id": row["document_id"],
        "page": row["page"],
        "position": row["position"],
        "object_key": row["object_key"],
        "local_path": row["local_path"],
        "width": row["width"],
        "height": row["height"],
        "created_at": row["created_at"],
        "kb_name": row["kb_name"],
    }


async def get_image_meta(image_id: str) -> dict[str, Any] | None:
    """Fetch image metadata by ``image_id``; return ``None`` if not found."""
    row = await async_fetchrow(f"SELECT {_IMAGE_COLUMNS} FROM images WHERE image_id = $1", image_id)
    return _image_from_row(row) if row is not None else None


async def list_images_by_document(
    document_id: str, *, page: int | None = None
) -> list[dict[str, Any]]:
    """List image metadata by ``document_id``, optionally filtered by ``page``.

    Results are ordered by page then image_id.
    """
    if page is None:
        rows = await async_fetch(
            f"SELECT {_IMAGE_COLUMNS} FROM images WHERE document_id = $1 "
            f"ORDER BY page NULLS LAST, image_id",
            document_id,
        )
    else:
        rows = await async_fetch(
            f"SELECT {_IMAGE_COLUMNS} FROM images WHERE document_id = $1 AND page = $2 "
            f"ORDER BY image_id",
            document_id,
            page,
        )
    return [_image_from_row(r) for r in rows]


async def get_image_url(image_id: str) -> str | None:
    """Return a presigned URL (MinIO) or local path; ``None`` if not found."""
    row = await async_fetchrow(
        "SELECT object_key, local_path FROM images WHERE image_id = $1", image_id
    )
    if row is None:
        return None
    object_key = row["object_key"]
    local_path = row["local_path"]
    if object_key:
        try:
            from eagle_rag.storage.minio_client import get_object_url

            return get_object_url(object_key)
        except Exception:
            return local_path
    return local_path


# ---------------------------------------------------------------------------
# Byte reads (synchronous, used by Celery / internals)
# ---------------------------------------------------------------------------


def get_image_bytes(image_id: str) -> bytes:
    """Read raw image bytes: prefer MinIO download, fall back to local file."""
    row = sync_fetchone(
        "SELECT object_key, local_path FROM images WHERE image_id = %s", (image_id,)
    )
    if row is None:
        raise KeyError(f"image not found: {image_id}")
    object_key, local_path = row
    if object_key:
        from eagle_rag.storage.minio_client import download_file

        with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
            tmp_path = tmp.name
        try:
            download_file(object_key, tmp_path)
            return Path(tmp_path).read_bytes()
        finally:
            Path(tmp_path).unlink(missing_ok=True)
    if local_path:
        return Path(local_path).read_bytes()
    raise ValueError(f"image {image_id} has neither object_key nor local_path")
