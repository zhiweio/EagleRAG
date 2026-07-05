"""MCP tool call log ORM model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Index, Integer, Text
from sqlmodel import Field, SQLModel

from eagle_rag.db.models.base import jsonb_default, timestamptz


class McpCallLog(SQLModel, table=True):
    """``mcp_call_log`` table: MCP tool call records, shown in the /admin/mcp console."""

    __tablename__ = "mcp_call_log"
    __table_args__ = (Index("idx_mcp_call_log_called_at", "called_at"),)

    id: str = Field(primary_key=True, sa_type=Text())
    tool_name: str = Field(sa_type=Text())
    arguments: dict = Field(default_factory=dict, sa_column=jsonb_default())
    result_summary: str = Field(default="", sa_type=Text())
    caller: str = Field(default="", sa_type=Text())
    latency_ms: int = Field(default=0, sa_type=Integer())
    called_at: datetime = Field(sa_column=timestamptz())
