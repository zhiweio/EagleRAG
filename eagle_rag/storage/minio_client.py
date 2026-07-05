"""MinIO object storage client wrapper.

Built on the official ``minio`` Python SDK; provides a lazily-initialized
singleton client plus common upload/download/presigned-URL helpers. The
recommended ``object_key`` convention is ``{source_type}/{document_id}/{filename}``,
but this module only offers generic upload primitives — the caller chooses
the key.

MinIO is not contacted at import time; connections are established lazily on
first method call.
"""

from __future__ import annotations

import io
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from minio import Minio

__all__ = [
    "get_minio_client",
    "ensure_bucket",
    "upload_file",
    "upload_bytes",
    "download_file",
    "get_object_bytes",
    "get_object_url",
    "delete_object",
]


_client: Minio | None = None


def get_minio_client() -> Minio:
    """Return the global ``Minio`` client singleton (lazy, reading ``settings.minio``)."""
    global _client  # noqa: PLW0603
    if _client is None:
        from minio import Minio

        from eagle_rag.config import get_settings

        cfg = get_settings().minio
        _client = Minio(
            endpoint=cfg.endpoint,
            access_key=cfg.access_key,
            secret_key=cfg.secret_key,
            secure=cfg.secure,
        )
    return _client


def ensure_bucket() -> None:
    """Create the configured bucket if it does not exist."""
    from eagle_rag.config import get_settings

    bucket = get_settings().minio.bucket
    client = get_minio_client()
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)


def upload_file(
    object_key: str,
    file_path: str | Path,
    content_type: str = "application/octet-stream",
) -> str:
    """Upload a local file to MinIO and return the ``object_key``."""
    from eagle_rag.config import get_settings

    bucket = get_settings().minio.bucket
    ensure_bucket()
    client = get_minio_client()
    client.fput_object(bucket, object_key, str(file_path), content_type=content_type)
    return object_key


def upload_bytes(
    object_key: str,
    data: bytes,
    content_type: str = "application/octet-stream",
    length: int | None = None,
) -> str:
    """Upload a byte stream to MinIO and return the ``object_key``.

    ``length`` defaults to ``len(data)``; the MinIO SDK's ``put_object`` requires
    an explicit length.
    """
    from eagle_rag.config import get_settings

    bucket = get_settings().minio.bucket
    ensure_bucket()
    client = get_minio_client()
    body = io.BytesIO(data)
    client.put_object(
        bucket,
        object_key,
        body,
        length=length if length is not None else len(data),
        content_type=content_type,
    )
    return object_key


def download_file(object_key: str, dest_path: str | Path) -> Path:
    """Download an object to a local path and return the destination ``Path``."""
    from eagle_rag.config import get_settings

    bucket = get_settings().minio.bucket
    client = get_minio_client()
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    client.fget_object(bucket, object_key, str(dest))
    return dest


def get_object_bytes(object_key: str) -> bytes:
    """Read an object's full contents into memory and return the raw bytes.

    Unlike :func:`download_file` this avoids the local temp-file round-trip, which
    suits API handlers that stream the payload straight back to the client.
    """
    from eagle_rag.config import get_settings

    bucket = get_settings().minio.bucket
    client = get_minio_client()
    response = None
    try:
        response = client.get_object(bucket, object_key)
        return response.read()
    finally:
        if response is not None:
            response.close()
            response.release_conn()


def get_object_url(object_key: str, expires: int = 3600) -> str:
    """Generate a presigned GET URL; default expiry is 1 hour."""
    from eagle_rag.config import get_settings

    bucket = get_settings().minio.bucket
    client = get_minio_client()
    return client.presigned_get_object(bucket, object_key, expires=timedelta(seconds=expires))


def delete_object(object_key: str) -> None:
    """Delete the specified object."""
    from eagle_rag.config import get_settings

    bucket = get_settings().minio.bucket
    client = get_minio_client()
    client.remove_object(bucket, object_key)
