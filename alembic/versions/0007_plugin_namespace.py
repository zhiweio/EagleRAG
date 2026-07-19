"""Add plugin_namespace isolation columns and composite PKs (G9/G18/G28).

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    return table in inspect(bind).get_table_names()


def _add_namespace(table: str) -> None:
    if not _table_exists(table):
        return
    if _column_exists(table, "plugin_namespace"):
        return
    op.add_column(
        table,
        sa.Column("plugin_namespace", sa.Text(), nullable=False, server_default="core"),
    )
    op.create_index(f"idx_{table}_namespace", table, ["plugin_namespace"])


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    return column in {col["name"] for col in inspect(bind).get_columns(table)}


def upgrade() -> None:
    _add_namespace("documents")
    if _table_exists("documents") and not _index_exists("documents", "idx_documents_ns_kb"):
        op.create_index("idx_documents_ns_kb", "documents", ["plugin_namespace", "kb_name"])

    _add_namespace("knowledge_bases")
    if _table_exists("knowledge_bases") and not _column_exists(
        "knowledge_bases", "collections_used"
    ):
        op.add_column(
            "knowledge_bases",
            sa.Column(
                "collections_used",
                postgresql.JSONB(),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
        )
    if _table_exists("knowledge_bases"):
        op.drop_constraint("knowledge_bases_pkey", "knowledge_bases", type_="primary")
        op.create_primary_key(
            "knowledge_bases_pkey",
            "knowledge_bases",
            ["kb_name", "plugin_namespace"],
        )

    _add_namespace("document_dedup")
    if _table_exists("document_dedup"):
        op.drop_constraint("document_dedup_pkey", "document_dedup", type_="primary")
        op.create_primary_key(
            "document_dedup_pkey",
            "document_dedup",
            ["sha256", "kb_name", "plugin_namespace"],
        )

    for table in (
        "sessions",
        "messages",
        "images",
        "document_keywords",
        "task_audit",
        "notifications",
        "mcp_call_log",
    ):
        _add_namespace(table)

    if _table_exists("document_keywords") and not _index_exists(
        "document_keywords",
        "idx_document_keywords_namespace_kb_keyword",
    ):
        op.create_index(
            "idx_document_keywords_namespace_kb_keyword",
            "document_keywords",
            ["plugin_namespace", "kb_name", "keyword"],
        )


def _index_exists(table: str, index_name: str) -> bool:
    bind = op.get_bind()
    return index_name in {idx["name"] for idx in inspect(bind).get_indexes(table)}


def downgrade() -> None:
    if _table_exists("document_keywords"):
        if _index_exists("document_keywords", "idx_document_keywords_namespace_kb_keyword"):
            op.drop_index(
                "idx_document_keywords_namespace_kb_keyword",
                table_name="document_keywords",
            )

    for table in (
        "mcp_call_log",
        "notifications",
        "task_audit",
        "document_keywords",
        "images",
        "messages",
        "sessions",
    ):
        if not _table_exists(table):
            continue
        if _index_exists(table, f"idx_{table}_namespace"):
            op.drop_index(f"idx_{table}_namespace", table_name=table)
        if _column_exists(table, "plugin_namespace"):
            op.drop_column(table, "plugin_namespace")

    if _table_exists("document_dedup"):
        op.drop_constraint("document_dedup_pkey", "document_dedup", type_="primary")
        if _column_exists("document_dedup", "plugin_namespace"):
            op.drop_column("document_dedup", "plugin_namespace")
        op.create_primary_key("document_dedup_pkey", "document_dedup", ["sha256", "kb_name"])

    if _table_exists("knowledge_bases"):
        op.drop_constraint("knowledge_bases_pkey", "knowledge_bases", type_="primary")
        if _column_exists("knowledge_bases", "collections_used"):
            op.drop_column("knowledge_bases", "collections_used")
        if _column_exists("knowledge_bases", "plugin_namespace"):
            op.drop_column("knowledge_bases", "plugin_namespace")
        op.create_primary_key("knowledge_bases_pkey", "knowledge_bases", ["kb_name"])

    if _table_exists("documents"):
        if _index_exists("documents", "idx_documents_ns_kb"):
            op.drop_index("idx_documents_ns_kb", table_name="documents")
        if _index_exists("documents", "idx_documents_namespace"):
            op.drop_index("idx_documents_namespace", table_name="documents")
        if _column_exists("documents", "plugin_namespace"):
            op.drop_column("documents", "plugin_namespace")
