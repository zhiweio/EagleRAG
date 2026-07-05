"""Purge legacy non-image session attachments.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-05
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from eagle_rag.attachments.store import purge_non_image_attachments_sync

    purge_non_image_attachments_sync()


def downgrade() -> None:
    pass
