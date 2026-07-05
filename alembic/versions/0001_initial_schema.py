"""初始 PostgreSQL 表结构。

Revision ID: 0001
Revises:
Create Date: 2026-07-01

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from eagle_rag.db.models import metadata

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建全部应用表。"""
    bind = op.get_bind()
    metadata.create_all(bind=bind)


def downgrade() -> None:
    """删除全部应用表（逆序由 SQLAlchemy 处理外键）。"""
    bind = op.get_bind()
    metadata.drop_all(bind=bind)
