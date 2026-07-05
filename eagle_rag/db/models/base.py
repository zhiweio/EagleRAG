"""ORM base helpers and Alembic metadata entry point."""

from __future__ import annotations

from sqlalchemy import Column, DateTime, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import SQLModel

metadata = SQLModel.metadata


def timestamptz() -> Column:
    """A ``TIMESTAMPTZ`` column with a ``NOW()`` server default."""
    return Column(DateTime(timezone=True), server_default=text("NOW()"), nullable=False)


def jsonb_default(expr: str = "'{}'::jsonb") -> Column:
    """A ``JSONB`` column with a default JSON object value."""
    return Column(JSONB, nullable=False, server_default=text(expr))
