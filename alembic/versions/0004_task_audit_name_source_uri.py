"""task_audit 表新增 name / source_uri 列。

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-04

为 ``task_audit`` 表增加 ``name`` 和 ``source_uri`` 两列，用于在前端任务列表
中直接展示用户上传的原始文件名，无需额外 JOIN ``documents`` 表。

- ``name``：原始文件名（如 ``report.pdf``），来自上传时的 ``file.filename``。
- ``source_uri``：MinIO object key 或外部 URL，与 ``documents.source_uri`` 一致。

两列均为 ``NULL`` 兼容旧数据；新任务在 ``create_audit`` 时写入。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add name / source_uri when missing (0001 create_all may already have them)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("task_audit")}
    if "name" not in columns:
        op.add_column("task_audit", sa.Column("name", sa.Text(), nullable=True))
    if "source_uri" not in columns:
        op.add_column("task_audit", sa.Column("source_uri", sa.Text(), nullable=True))


def downgrade() -> None:
    """Drop name / source_uri when present."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("task_audit")}
    if "source_uri" in columns:
        op.drop_column("task_audit", "source_uri")
    if "name" in columns:
        op.drop_column("task_audit", "name")
