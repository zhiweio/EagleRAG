"""Composite unique constraints for namespace-scoped child tables (G18).

Revision ID: 0008
Revises: 0007
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_images_document_namespace",
        "images",
        ["document_id", "plugin_namespace", "image_id"],
    )
    op.create_unique_constraint(
        "uq_document_keywords_doc_namespace_keyword",
        "document_keywords",
        ["document_id", "plugin_namespace", "keyword"],
    )
    op.create_unique_constraint(
        "uq_messages_id_namespace",
        "messages",
        ["message_id", "plugin_namespace"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_messages_id_namespace", "messages", type_="unique")
    op.drop_constraint(
        "uq_document_keywords_doc_namespace_keyword",
        "document_keywords",
        type_="unique",
    )
    op.drop_constraint("uq_images_document_namespace", "images", type_="unique")
