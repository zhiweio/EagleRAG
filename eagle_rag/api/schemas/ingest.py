"""Ingestion and task API models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from eagle_rag.api.schemas._helpers import model_from_row
from eagle_rag.api.schemas.common import PaginatedMeta


class TaskLogEntry(BaseModel):
    """Single task audit log entry (loose JSONB structure, extra fields allowed)."""

    model_config = ConfigDict(extra="allow")

    ts: str | None = None
    time: str | None = None
    timestamp: str | None = None
    level: str | None = None
    severity: str | None = None
    message: str | None = None
    msg: str | None = None
    event: str | None = None
    text: str | None = None


class IngestResponse(BaseModel):
    job_id: str
    status: str = Field(description="pending | success")
    dedup_hit: bool = False
    document_id: str | None = None


class UrlValidationErrorDetail(BaseModel):
    """Structured detail returned with 422 when URL prefetch fails."""

    code: str = Field(description="Machine-readable error code, e.g. url_unreachable")
    reason: str = Field(description="Human-readable reason")
    suggestion: str | None = Field(default=None, description="Optional corrective suggestion")


class IngestLimitErrorDetail(BaseModel):
    """Structured detail returned with 422 when ingest size/page limits fail."""

    code: str = Field(
        description=("Machine-readable error code, e.g. file_too_large / pdf_too_many_pages")
    )
    reason: str = Field(description="Human-readable reason")
    suggestion: str | None = Field(default=None, description="Optional corrective suggestion")


_STATUS_PHASE_MAP: dict[str, str] = {
    "pending": "pending",
    "queued": "pending",
    "rendering": "running",
    "embedding": "running",
    "indexing": "running",
    "processing": "running",
    "parsing": "running",
    "retrying": "running",
    "success": "success",
    "done": "success",
    "ready": "success",
    "failed": "failed",
    "error": "failed",
}


def _normalize_status_phase(status: str | None) -> str:
    """Normalize a backend raw status into one of 4 phases (pending/running/success/failed).

    Aligns with ``normalizeStatus`` in the frontend ``status.ts``: unknown non-empty
    statuses default to ``running``; empty values fall back to ``pending``.
    """
    if not status:
        return "pending"
    return _STATUS_PHASE_MAP.get(status, "running")


class TaskAuditOut(BaseModel):
    """Task audit output.

    ``status`` is the backend raw status (pending/rendering/embedding/indexing/success/
    failed/retrying, etc.); ``status_phase`` is the normalized 4-phase value consumed
    directly by the frontend ``status.ts``:

    - ``pending``: pending / queued
    - ``running``: rendering / embedding / indexing / processing / parsing / retrying
    - ``success``: success / done / ready
    - ``failed``: failed / error
    """

    job_id: str
    document_id: str | None = None
    name: str | None = None
    source_uri: str | None = None
    pipeline: str
    status: str
    status_phase: str = Field(
        default="pending",
        description="Normalized four-phase status: pending | running | success | failed",
    )
    progress: int = 0
    current: int | None = None
    total: int | None = None
    error: str | None = None
    logs: list[TaskLogEntry] = Field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None
    kb_name: str = "default"

    @model_validator(mode="after")
    def _compute_status_phase(self) -> TaskAuditOut:
        self.status_phase = _normalize_status_phase(self.status)
        return self

    @classmethod
    def from_store(cls, row: dict[str, Any]) -> TaskAuditOut:
        return model_from_row(cls, row)


class TaskListResponse(PaginatedMeta):
    items: list[TaskAuditOut]
    error: str | None = Field(
        default=None, description="Degraded hint when the database is unavailable"
    )


class TaskLogsResponse(BaseModel):
    job_id: str
    logs: list[TaskLogEntry] = Field(default_factory=list)


class TaskRetryResponse(BaseModel):
    job_id: str
    status: str
    retried: bool = True


class QueueMetricItem(BaseModel):
    """Concurrency config and live backlog for a single Celery queue."""

    name: str
    concurrency: int
    size: int | None = Field(
        default=None, description="Redis LLEN queue depth; null when unavailable"
    )


class IngestQueueMetricsResponse(BaseModel):
    """Ingestion queue metrics: concurrency cap and backlog length per Celery queue."""

    queues: list[QueueMetricItem]
