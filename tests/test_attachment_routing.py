"""Attachment routing selector tests."""

from __future__ import annotations

from eagle_rag.router.models import RouteContext
from eagle_rag.router.selectors import AttachmentSelector


def test_attachment_selector_image_only_visual():
    decision = AttachmentSelector().select(
        RouteContext(query="", has_image_attachment=True),
    )
    assert decision is not None
    assert decision.selected == ["visual"]


def test_attachment_selector_image_and_text_hybrid():
    decision = AttachmentSelector().select(
        RouteContext(query="find similar charts", has_image_attachment=True),
    )
    assert decision is not None
    assert decision.selected == ["text", "visual"]
