"""Image attachment validation shared by REST upload and MCP inline images."""

from __future__ import annotations

import base64
import binascii
import re

from eagle_rag.config import get_settings

__all__ = [
    "allowed_image_exts",
    "decode_inline_image",
    "file_ext",
    "is_allowed_image_attachment",
    "validate_image_attachment",
]

_DATA_URI_RE = re.compile(r"^data:(?P<mime>[^;]+);base64,(?P<data>.+)$", re.DOTALL)


def file_ext(file_name: str) -> str:
    dot = file_name.rfind(".")
    return file_name[dot:].lower() if dot >= 0 else ""


def allowed_image_exts() -> set[str]:
    return set(get_settings().attachments.allowed_image_exts)


def is_allowed_image_attachment(mime: str, file_name: str) -> bool:
    """Return True when mime/extension matches the configured image whitelist."""
    mime_l = (mime or "").lower().strip()
    ext = file_ext(file_name)
    exts = allowed_image_exts()
    if mime_l.startswith("image/"):
        if ext and ext not in exts:
            return False
        return True
    return ext in exts


def validate_image_attachment(
    *,
    data: bytes,
    mime: str = "",
    file_name: str = "",
) -> None:
    """Raise ``ValueError`` when the payload is not an allowed image or exceeds size."""
    if not data:
        raise ValueError("empty image")
    max_bytes = get_settings().attachments.max_image_bytes
    if len(data) > max_bytes:
        raise ValueError(f"image exceeds max size ({max_bytes} bytes)")
    if not is_allowed_image_attachment(mime, file_name):
        raise ValueError("unsupported image type")


def decode_inline_image(
    image_base64: str,
    *,
    mime: str | None = None,
    file_name: str | None = None,
) -> bytes:
    """Decode base64 (optionally data-URI) and validate as an allowed image."""
    raw = (image_base64 or "").strip()
    if not raw:
        raise ValueError("empty image_base64")
    hint_mime = mime or ""
    if raw.startswith("data:"):
        match = _DATA_URI_RE.match(raw)
        if match is None:
            raise ValueError("invalid data URI")
        hint_mime = match.group("mime")
        raw = match.group("data")
    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("invalid base64 image") from exc
    validate_image_attachment(
        data=data,
        mime=hint_mime,
        file_name=file_name or "",
    )
    return data
