"""Generic time-series metric sample ORM model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Float, Index, Text
from sqlmodel import Field, SQLModel

from eagle_rag.db.models.base import jsonb_default, timestamptz


class MetricSample(SQLModel, table=True):
    """``metric_sample`` table: generic time-series samples (queue depth, model usage, etc.)."""

    __tablename__ = "metric_sample"
    __table_args__ = (Index("idx_metric_sample_name_time", "metric_name", "sampled_at"),)

    id: str = Field(primary_key=True, sa_type=Text())
    metric_name: str = Field(sa_type=Text())
    labels: dict = Field(default_factory=dict, sa_column=jsonb_default())
    value: float = Field(default=0.0, sa_type=Float())
    sampled_at: datetime = Field(sa_column=timestamptz())
