"""新增 document_keywords 标签目录表 + sessions.scope_filter 列。

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-04

支撑 Q&A 高级作用域筛选（作用域筛选）：

- ``document_keywords``：由 Knowhere 抽取的 chunk ``keywords`` 聚合而成的
  「文档-关键词」目录，用于标签列表（命中节点数 / 覆盖知识库数）与检索时把
  选中标签解析回文档集合。随文档删除自动级联清理。
- ``sessions.scope_filter``：JSONB，可空，持久化会话最近一次的作用域选择
  （知识库 / 文档 / 标签），供前端切换会话时恢复。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建 document_keywords 表并为 sessions 增加 scope_filter 列。"""
    op.create_table(
        "document_keywords",
        sa.Column("document_id", sa.Text(), nullable=False),
        sa.Column("keyword", sa.Text(), nullable=False),
        sa.Column("kb_name", sa.Text(), nullable=False, server_default="default"),
        sa.Column("node_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.document_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("document_id", "keyword"),
    )
    op.create_index(
        "idx_document_keywords_kb_keyword",
        "document_keywords",
        ["kb_name", "keyword"],
    )
    op.create_index(
        "idx_document_keywords_keyword",
        "document_keywords",
        ["keyword"],
    )
    op.add_column(
        "sessions",
        sa.Column("scope_filter", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    """回滚：删除 scope_filter 列与 document_keywords 表。"""
    op.drop_column("sessions", "scope_filter")
    op.drop_index("idx_document_keywords_keyword", table_name="document_keywords")
    op.drop_index("idx_document_keywords_kb_keyword", table_name="document_keywords")
    op.drop_table("document_keywords")
