"""Session-level attachment storage."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from eagle_rag.attachments.validation import is_allowed_image_attachment
from eagle_rag.config import get_settings
from eagle_rag.db import async_fetchrow, sync_execute, sync_fetchone

__all__ = [
    "store_attachment_sync",
    "get_attachment_sync",
    "get_attachment_bytes_sync",
    "delete_attachment_sync",
    "purge_expired_sync",
    "purge_non_image_attachments_sync",
]


def _attachment_dir() -> Path:
    base = Path(get_settings().storage.data_dir) / "attachments"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _ttl_hours() -> int:
    return get_settings().attachments.ttl_hours


def store_attachment_sync(
    *,
    data: bytes,
    file_name: str,
    mime: str,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Write the attachment file and metadata, returning the attachment record."""
    attachment_id = str(uuid.uuid4())
    dest = _attachment_dir() / attachment_id
    dest.write_bytes(data)
    expires = datetime.now(UTC) + timedelta(hours=_ttl_hours())
    sync_execute(
        """
        INSERT INTO attachments
          (attachment_id, session_id, file_name, mime, size_bytes, storage_path, expires_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (attachment_id, session_id, file_name, mime, len(data), str(dest), expires),
    )
    return {
        "attachment_id": attachment_id,
        "file_name": file_name,
        "mime": mime,
        "size_bytes": len(data),
        "expires_at": expires.isoformat(),
    }


def get_attachment_sync(attachment_id: str) -> dict[str, Any] | None:
    row = sync_fetchone(
        """
        SELECT attachment_id, session_id, file_name, mime, size_bytes,
               storage_path, expires_at, created_at
        FROM attachments WHERE attachment_id = %s
        """,
        (attachment_id,),
    )
    if row is None:
        return None
    cols = [
        "attachment_id",
        "session_id",
        "file_name",
        "mime",
        "size_bytes",
        "storage_path",
        "expires_at",
        "created_at",
    ]
    d = dict(zip(cols, row, strict=False))
    for k in ("expires_at", "created_at"):
        if d.get(k) is not None and hasattr(d[k], "isoformat"):
            d[k] = d[k].isoformat()
    return d


def get_attachment_bytes_sync(attachment_id: str) -> bytes | None:
    meta = get_attachment_sync(attachment_id)
    if meta is None:
        return None
    path = Path(meta["storage_path"])
    if not path.exists():
        return None
    return path.read_bytes()


def delete_attachment_sync(attachment_id: str) -> bool:
    meta = get_attachment_sync(attachment_id)
    if meta is None:
        return False
    path = Path(meta["storage_path"])
    if path.exists():
        path.unlink(missing_ok=True)
    sync_execute("DELETE FROM attachments WHERE attachment_id = %s", (attachment_id,))
    return True


def purge_expired_sync() -> int:
    from eagle_rag.db import sync_fetchall

    expired = sync_fetchall(
        "SELECT attachment_id, storage_path FROM attachments WHERE expires_at < NOW() LIMIT 500"
    )
    count = 0
    for aid, spath in expired:
        Path(spath).unlink(missing_ok=True)
        Path(f"{spath}.parsed.json").unlink(missing_ok=True)
        sync_execute("DELETE FROM attachments WHERE attachment_id = %s", (aid,))
        count += 1
    return count


def _is_stored_image_attachment(mime: str, file_name: str) -> bool:
    return is_allowed_image_attachment(mime, file_name)


def purge_non_image_attachments_sync() -> int:
    """Delete legacy non-image attachments and scrub message references."""
    from eagle_rag.db import sync_fetchall

    rows = sync_fetchall(
        """
        SELECT attachment_id, storage_path, mime, file_name
        FROM attachments
        """
    )
    removed_ids: list[str] = []
    for attachment_id, storage_path, mime, file_name in rows:
        if _is_stored_image_attachment(str(mime or ""), str(file_name or "")):
            continue
        path = Path(str(storage_path))
        path.unlink(missing_ok=True)
        Path(f"{path}.parsed.json").unlink(missing_ok=True)
        sync_execute("DELETE FROM attachments WHERE attachment_id = %s", (attachment_id,))
        removed_ids.append(str(attachment_id))

    if not removed_ids:
        return 0

    msg_rows = sync_fetchall(
        "SELECT message_id, attachments FROM messages WHERE attachments IS NOT NULL"
    )
    for message_id, attachments in msg_rows:
        if not attachments:
            continue
        if isinstance(attachments, list):
            filtered = [aid for aid in attachments if str(aid) not in removed_ids]
            if filtered == attachments:
                continue
            new_value = filtered or None
        else:
            continue
        sync_execute(
            "UPDATE messages SET attachments = %s::jsonb WHERE message_id = %s",
            (json.dumps(new_value) if new_value is not None else None, message_id),
        )
    return len(removed_ids)


async def get_attachment(attachment_id: str) -> dict[str, Any] | None:
    row = await async_fetchrow(
        """
        SELECT attachment_id, session_id, file_name, mime, size_bytes,
               storage_path, expires_at, created_at
        FROM attachments WHERE attachment_id = $1
        """,
        attachment_id,
    )
    if row is None:
        return None
    d = dict(row)
    for k in ("expires_at", "created_at"):
        if d.get(k) is not None and hasattr(d[k], "isoformat"):
            d[k] = d[k].isoformat()
    return d
