"""Attachment validation unit tests."""

from __future__ import annotations

import base64

import pytest

from eagle_rag.attachments.validation import (
    decode_inline_image,
    is_allowed_image_attachment,
    validate_image_attachment,
)


def test_is_allowed_image_attachment_png():
    assert is_allowed_image_attachment("image/png", "photo.png") is True
    assert is_allowed_image_attachment("application/pdf", "doc.pdf") is False


def test_validate_image_attachment_rejects_oversize():
    with pytest.raises(ValueError, match="max size"):
        validate_image_attachment(
            data=b"x" * (5 * 1024 * 1024 + 1),
            mime="image/png",
            file_name="big.png",
        )


def test_decode_inline_image_accepts_base64_png():
    payload = base64.b64encode(b"\x89PNG\r\n\x1a\n").decode("ascii")
    data = decode_inline_image(payload, mime="image/png")
    assert data.startswith(b"\x89PNG")
