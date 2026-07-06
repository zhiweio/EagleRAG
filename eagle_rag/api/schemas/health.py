"""Health probe and admin API models."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from eagle_rag.config import (
    AppSettings,
    AttachmentsSettings,
    AuthSettings,
    CelerySettings,
    EmbeddingSettings,
    KbCapacitySettings,
    KnowhereSettings,
    LLMSettings,
    MilvusSettings,
    MinIOSettings,
    PdfProbeSettings,
    PixelRAGSettings,
    PostgresSettings,
    RerankSettings,
    RouterSettings,
    StorageSettings,
    VLMSettings,
)


class DependencyStatus(StrEnum):
    up = "up"
    down = "down"
    unknown = "unknown"


class DependencySummary(BaseModel):
    status: DependencyStatus
    detail: str = ""
    uptime: str = Field(
        default="",
        description=(
            "Continuous uptime (human-readable, e.g. '14d 5h'; empty when service is down)"
        ),
    )


class HealthResponse(BaseModel):
    status: str = Field(description="ok | degraded")
    app: str
    version: str
    dependencies: dict[str, DependencySummary]


class ProbeDetail(BaseModel):
    status: DependencyStatus
    detail: str = ""
    latency_ms: int = 0
    uptime: str = Field(
        default="",
        description=(
            "Continuous uptime (human-readable, e.g. '14d 5h'; empty when service is down)"
        ),
    )


class AdminProbesResponse(BaseModel):
    status: str = Field(description="ok | degraded")
    dependencies: dict[str, ProbeDetail]
    resource_limits: ResourceLimitsOut | None = None
    probe_config: ProbeConfigOut | None = None


class McpToolDefinition(BaseModel):
    """MCP tool metadata (matches ``TOOL_DEFINITIONS`` entries)."""

    model_config = ConfigDict(extra="allow")

    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class McpToolsResponse(BaseModel):
    tools: list[McpToolDefinition] = Field(default_factory=list)
    error: str | None = None


class AdminMcpResponse(BaseModel):
    registered: bool
    tools: list[McpToolDefinition] = Field(default_factory=list)
    sse_connections: int | None = None
    console_logs: list[McpCallLogOut] = Field(default_factory=list)
    # Runtime transport metadata (sourced from McpSettings + mcp library).
    transport: str | None = None
    protocol_version: str | None = None
    stateless_http: bool | None = None
    json_response: bool | None = None
    endpoint_path: str | None = None
    port: int | None = None


class CeleryActiveTaskOut(BaseModel):
    """Single Celery ``inspect.active()`` task (fields vary across Celery versions)."""

    model_config = ConfigDict(extra="allow")

    worker: str


class CeleryQueueInfo(BaseModel):
    queue: str | None = None
    size: int | None = None
    error: str | None = None


class AdminCeleryResponse(BaseModel):
    workers: list[str] = Field(default_factory=list)
    active_tasks: list[CeleryActiveTaskOut] = Field(default_factory=list)
    queues: list[CeleryQueueInfo] = Field(default_factory=list)
    worker_details: list[WorkerDetailOut] = Field(default_factory=list)
    pending: int | None = None
    succeeded: int | None = None
    queue_backlog_series: list[QueueSeriesPoint] = Field(default_factory=list)


class MilvusCollectionOut(BaseModel):
    name: str
    num_entities: int | None = None
    error: str | None = None


class AdminMilvusResponse(BaseModel):
    collections: list[MilvusCollectionOut] = Field(default_factory=list)
    collection_details: list[CollectionDetailOut] = Field(default_factory=list)
    index_size: str | None = None
    memory: float | None = None


class AdminPixelragResponse(BaseModel):
    status: DependencyStatus | str
    detail: str = ""
    visual_vectors: int | None = None
    error: str | None = None
    render_count: int | None = None
    embed_count: int | None = None


class AdminKnowhereResponse(BaseModel):
    mode: str = "api"
    base_url: str
    status: DependencyStatus | str
    detail: str = ""
    parsed: int | None = None
    chunks: int | None = None
    partitions: list[KbPartitionOut] = Field(default_factory=list)


class MinioBucketOut(BaseModel):
    """MinIO bucket overview (from ``client.list_buckets()`` with best-effort object count)."""

    name: str
    creation_date: str | None = None  # ISO-8601 string
    object_count: int | None = None  # Best-effort; None when list_objects is too costly
    is_default: bool = False  # Default bucket (settings.minio.bucket)


class AdminMinioResponse(BaseModel):
    endpoint: str
    secure: bool
    bucket: str  # Configured default bucket
    buckets: list[MinioBucketOut] = Field(default_factory=list)
    status: DependencyStatus | str
    detail: str = ""
    latency_ms: int = 0
    error: str | None = None


class RedisInfoOut(BaseModel):
    """Trimmed view of key Redis INFO fields (avoids exposing full info to the frontend)."""

    version: str | None = None
    uptime_days: int | None = None
    connected_clients: int | None = None
    used_memory_human: str | None = None
    used_memory_peak_human: str | None = None
    role: str | None = None  # master | slave
    maxmemory_human: str | None = None


class AdminRedisResponse(BaseModel):
    broker_url: str
    db_size: int | None = None  # dbsize() — total key count
    info: RedisInfoOut | None = None
    status: DependencyStatus | str
    detail: str = ""
    latency_ms: int = 0
    error: str | None = None


class AdminVlmResponse(BaseModel):
    provider: str
    model: str
    api_key_set: bool
    base_url: str
    latency: float | None = None
    tokens: int | None = None
    error_rate: float | None = None
    model_router: list[ModelRouterOut] = Field(default_factory=list)


class AdminConfigOut(BaseModel):
    """Sanitized runtime config snapshot (sensitive fields like api_key are ``***``)."""

    app: AppSettings
    kb_name: str
    milvus: MilvusSettings
    knowhere: KnowhereSettings
    pixelrag: PixelRAGSettings
    pdf_probe: PdfProbeSettings
    vlm: VLMSettings
    llm: LLMSettings
    embedding: EmbeddingSettings
    rerank: RerankSettings
    router: RouterSettings
    celery: CelerySettings
    minio: MinIOSettings
    postgres: PostgresSettings
    storage: StorageSettings
    kb: KbCapacitySettings
    attachments: AttachmentsSettings
    auth: AuthSettings


class WorkerDetailOut(BaseModel):
    """Celery worker details (from inspect.stats / inspect.active)."""

    name: str
    pid: int | None = None
    state: str = "unknown"  # "active" | "idle" | "unknown"
    current: str | None = None  # Name of currently executing task
    memory: float | None = None  # MB


class QueueSeriesPoint(BaseModel):
    """Single point in the queue backlog time series."""

    sampled_at: str
    knowhere: float = 0.0
    pixelrag: float = 0.0
    router: float = 0.0


class CollectionFieldOut(BaseModel):
    """Milvus collection field info."""

    name: str
    dtype: str = ""
    is_primary: bool = False


class CollectionDetailOut(BaseModel):
    """Milvus collection details."""

    name: str
    num_entities: int | None = None
    dim: int | None = None
    metric_type: str | None = None
    index_type: str | None = None
    fields: list[CollectionFieldOut] = Field(default_factory=list)
    error: str | None = None


class KbPartitionOut(BaseModel):
    """Knowledge-base partition stats (per-KB document/chunk counts)."""

    kb_name: str
    document_count: int = 0
    chunk_count: int | None = None


class ModelRouterOut(BaseModel):
    """Model router toggle state."""

    key: str  # "vlm" | "text_llm" | "embedding"
    name: str  # Display name
    enabled: bool = True


class ModelRouterUpdate(BaseModel):
    """Request body for PATCH /admin/model-router."""

    vlm: bool | None = None
    text_llm: bool | None = None
    embedding: bool | None = None


class ResourceLimitOut(BaseModel):
    """Single resource usage (CPU/memory)."""

    used: float
    limit: float | None = None
    unit: str = ""  # "%" | "MB" | "cores"
    percent: float | None = None


class ResourceLimitsOut(BaseModel):
    """Resource limits overview (from psutil)."""

    cpu: ResourceLimitOut | None = None
    memory: ResourceLimitOut | None = None


class ProbeConfigOut(BaseModel):
    """Probe config (liveness/readiness/startup timing strings)."""

    liveness: str = "30s"
    readiness: str = "10s"
    startup: str = "5s"
    failure_threshold: int = 3


class McpCallLogOut(BaseModel):
    """MCP call log entry (console display)."""

    time: str  # called_at iso str
    level: str = "INFO"
    message: str  # Tool call summary


class AdminActionDetail(BaseModel):
    """Single collection maintenance operation result."""

    collection: str
    action: str  # "flush" | "compact"
    success: bool
    detail: str = ""


class AdminActionResult(BaseModel):
    """Aggregated maintenance operation result."""

    success: bool
    message: str
    details: list[AdminActionDetail] = Field(default_factory=list)


# Models defined later in this file are referenced via forward refs by response
# models above (annotations are strings thanks to `from __future__ import annotations`);
# rebuild them here to resolve the cross-order dependencies.
for _mdl in (
    AdminProbesResponse,
    AdminMcpResponse,
    AdminCeleryResponse,
    AdminMilvusResponse,
    AdminPixelragResponse,
    AdminKnowhereResponse,
    AdminVlmResponse,
    AdminMinioResponse,
    AdminRedisResponse,
    AdminActionResult,
):
    _mdl.model_rebuild()
