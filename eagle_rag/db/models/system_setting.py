"""System runtime config override ORM model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Text
from sqlmodel import Field, SQLModel

from eagle_rag.db.models.base import jsonb_default, timestamptz


class SystemSetting(SQLModel, table=True):
    """``system_setting`` table: key-value runtime config overrides (e.g. model routing toggles)."""

    __tablename__ = "system_setting"

    key: str = Field(primary_key=True, sa_type=Text())
    value: dict = Field(default_factory=dict, sa_column=jsonb_default())
    updated_at: datetime = Field(sa_column=timestamptz())
