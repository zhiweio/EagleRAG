"""Health 模块新增表：mcp_call_log / system_setting / metric_sample。

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-02

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from eagle_rag.db.models import metadata

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建 health 模块新增表（checkfirst=True 跳过已存在的表）。"""
    bind = op.get_bind()
    metadata.create_all(
        bind=bind,
        checkfirst=True,
        tables=[
            metadata.tables["mcp_call_log"],
            metadata.tables["system_setting"],
            metadata.tables["metric_sample"],
        ],
    )


def downgrade() -> None:
    """删除 health 模块新增表。"""
    bind = op.get_bind()
    metadata.drop_all(
        bind=bind,
        checkfirst=True,
        tables=[
            metadata.tables["metric_sample"],
            metadata.tables["system_setting"],
            metadata.tables["mcp_call_log"],
        ],
    )
