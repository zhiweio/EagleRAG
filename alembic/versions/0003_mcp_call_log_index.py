"""mcp_call_log 表新增复合索引 (tool_name, called_at)。

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-04

为 ``/admin/mcp`` 控制台按工具名 + 时间范围查询 MCP 调用日志提供索引支撑。
原 ``idx_mcp_call_log_called_at`` 仅索引 ``called_at``，按 ``tool_name`` 过滤
时仍需全表扫描。复合索引 ``(tool_name, called_at)`` 覆盖最常见的
``WHERE tool_name = ? ORDER BY called_at DESC`` 查询模式。

Note:
    spec 提及 ``kb_name`` 列，但 ``mcp_call_log`` 表无此列（``kb_name`` 在
    ``arguments`` JSONB 中）。此处改为 ``(tool_name, called_at)`` 复合索引，
    覆盖实际查询模式。如需按 ``kb_name`` 查询，可通过 JSONB 表达式索引
    ``((arguments->>'kb_name')::text)`` 扩展，但当前无此查询需求。
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """新增 (tool_name, called_at) 复合索引。"""
    op.create_index(
        "idx_mcp_call_log_tool_called_at",
        "mcp_call_log",
        ["tool_name", "called_at"],
        unique=False,
    )


def downgrade() -> None:
    """删除复合索引。"""
    op.drop_index("idx_mcp_call_log_tool_called_at", table_name="mcp_call_log")
