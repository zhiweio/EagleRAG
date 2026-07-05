"""Eagle-RAG configuration loading.

Loads layered configuration from ``settings.yaml`` and environment variables. YAML
values may use ``${VAR:-default}`` placeholders (shell-style), recursively expanded
to the referenced environment variable or the supplied default at load time. The
top-level ``Settings`` uses ``pydantic-settings`` ``BaseSettings`` and additionally
supports ``EAGLE_RAG_<SECTION>__<FIELD>`` environment variable overrides.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = [
    "Settings",
    "AppSettings",
    "MilvusSettings",
    "KnowhereSettings",
    "PixelRAGSettings",
    "PdfProbeSettings",
    "VLMSettings",
    "LLMSettings",
    "EmbeddingSettings",
    "TextEmbeddingSettings",
    "VisualEmbeddingSettings",
    "RerankSettings",
    "RerankTextSettings",
    "RerankVisualSettings",
    "RouterSettings",
    "HeuristicRule",
    "RouterHeuristicSettings",
    "RouterLLMSettings",
    "ContentTypeRule",
    "IngestRoutingSettings",
    "SourceTypeRule",
    "IngestSourceTypeSettings",
    "IngestSettings",
    "UrlPrefetchConfig",
    "CelerySettings",
    "QueueConfig",
    "MinIOSettings",
    "PostgresSettings",
    "StorageSettings",
    "TelemetrySettings",
    "McpSettings",
    "McpOAuthSettings",
    "McpMtlsSettings",
    "get_settings",
]

# Match ${VAR} and ${VAR:-default} (os.path.expandvars does not support :- defaults).
_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-(.*))?\}")

# Default settings.yaml path: resolved relative to this module to avoid CWD dependence.
_DEFAULT_SETTINGS_PATH = Path(__file__).resolve().parent / "settings.yaml"


class AppSettings(BaseModel):
    name: str
    env: str
    host: str
    port: int


class MilvusSettings(BaseModel):
    host: str
    port: int
    text_collection: str
    visual_collection: str
    dim_text: int
    dim_visual: int
    visual_index_type: str  # hnsw | diskann


class KnowhereSettings(BaseModel):
    base_url: str
    api_key: str = ""
    timeout: float = 60.0
    upload_timeout: float = 600.0
    max_retries: int = 5
    poll_interval: float = 10.0
    poll_timeout: float = 1800.0
    # Passthrough SDK ParsingParams (optional): model / ocr_enabled /
    # doc_type / smart_title_parse, etc.
    parsing_params: dict[str, Any] = {}


class PixelRAGSettings(BaseModel):
    chunk_size: int
    top_k: int
    tile_height: int
    quality: int
    viewport_width: int
    backend: str  # cdp | playwright
    pdf_dpi: int
    embed_device: str  # auto | cuda | mps | cpu (device for the local Qwen3-VL encoder)
    embed_instruction: str  # Encoding instruction (system prompt), shared by image and text


class PdfProbeSettings(BaseModel):
    text_page_ratio: float
    avg_chars_per_page: int


class VLMSettings(BaseModel):
    provider: str
    model: str
    api_key: str
    base_url: str


class LLMSettings(BaseModel):
    provider: str
    model: str
    api_key: str
    base_url: str


class TextEmbeddingSettings(BaseModel):
    provider: str
    model: str
    api_key: str
    base_url: str
    dim: int


class VisualEmbeddingSettings(BaseModel):
    provider: str
    model: str
    dim: int


class EmbeddingSettings(BaseModel):
    text: TextEmbeddingSettings
    visual: VisualEmbeddingSettings


class RerankTextSettings(BaseModel):
    provider: str
    model: str
    api_key: str


class RerankVisualSettings(BaseModel):
    provider: str
    model: str


class RerankSettings(BaseModel):
    text: RerankTextSettings
    visual: RerankVisualSettings


class HeuristicRule(BaseModel):
    """Heuristic routing keyword rule: matching any keyword routes to ``route``."""

    keywords: list[str]
    route: str  # text | visual | hybrid


class RouterHeuristicSettings(BaseModel):
    """Heuristic routing config: ordered rules (first match wins) plus a default route."""

    rules: list[HeuristicRule] = [
        HeuristicRule(
            keywords=[
                "架构图",
                "结构图",
                "示意图",
                "流程图",
                "展示图",
                "原理图",
                "插图",
                "图片",
                "diagram",
                "figure",
                "architecture",
            ],
            route="hybrid",
        ),
        HeuristicRule(
            keywords=[
                "表格",
                "报表",
                "图表",
                "截图",
                "利润",
                "资产负债",
                "收入",
                "成本",
                "看图",
                "读数",
                "table",
                "chart",
                "report",
            ],
            route="visual",
        ),
        HeuristicRule(
            keywords=[
                "政策",
                "法规",
                "条例",
                "规定",
                "第几条",
                "依据",
                "policy",
                "law",
                "regulation",
            ],
            route="text",
        ),
        HeuristicRule(
            keywords=["工商", "招投标", "中标", "企业信息", "business", "bid", "tender"],
            route="visual",
        ),
    ]
    default: str = "text"


class RouterLLMSettings(BaseModel):
    """LLM intent classification config. ``{query}`` in ``prompt_template`` is a placeholder."""

    enabled: bool = True
    prompt_template: str = (
        "判断以下查询应使用哪种检索方式，只回复一个单词：text、visual 或 hybrid。\n"
        "- text：政策/法规/条例等纯文本问题\n"
        "- visual：报表/表格/图表/截图/看图读数/工商招投标等需要图片的问题\n"
        "- hybrid：同时需要文本与图片\n\n"
        "查询：{query}\n"
        "回答："
    )


class RouterSettings(BaseModel):
    mode: str = "auto"
    llm: RouterLLMSettings = RouterLLMSettings()
    heuristic: RouterHeuristicSettings = RouterHeuristicSettings()
    # Upper bound on document_ids folded into the advanced scope filter's Milvus
    # ``document_id in [...]`` predicate (bounds tag-resolved document lists).
    max_scope_documents: int = 500
    # Max chars of chunk body echoed back on each retrieval source (bounds the
    # ``/search`` and ``/query`` payload while still surfacing the evidence text).
    source_content_max_chars: int = 4000
    # Upper bound on section nodes persisted / served for a document's semantic tree.
    structure_max_nodes: int = 2000


class QueueConfig(BaseModel):
    concurrency: int


class CelerySettings(BaseModel):
    broker_url: str
    result_backend: str
    task_routes: dict[str, str]
    queues: dict[str, QueueConfig]
    max_retries: int
    retry_backoff: int


class MinIOSettings(BaseModel):
    endpoint: str
    access_key: str
    secret_key: str
    secure: bool
    bucket: str


class PostgresSettings(BaseModel):
    dsn: str


class StorageSettings(BaseModel):
    data_dir: str
    image_store: str


class KbCapacitySettings(BaseModel):
    text_entity_limit: int
    visual_entity_limit: int


class AttachmentsParseSettings(BaseModel):
    max_bytes: int
    max_chunks: int
    timeout_sec: int
    cache_enabled: bool
    chunk_size: int


class AttachmentsSettings(BaseModel):
    ttl_hours: int
    parse: AttachmentsParseSettings


class ContentTypeRule(BaseModel):
    """content_type fallback rule (``mode`` is startswith/contains; routes to ``pipeline``)."""

    match: str
    mode: str = "contains"  # startswith | contains
    pipeline: str  # knowhere | pixelrag


class IngestRoutingSettings(BaseModel):
    """Ingest routing config: extension sets / prefix map / content_type rules.

    Defaults match the prior hardcoded values.
    """

    prefix_force: dict[str, str] = {"knowhere:": "knowhere", "pixelrag:": "pixelrag"}
    knowhere_exts: list[str] = [
        ".docx",
        ".doc",
        ".md",
        ".markdown",
        ".txt",
        ".xlsx",
        ".xls",
        ".csv",
        ".pptx",
        ".json",
    ]
    pixelrag_exts: list[str] = [
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".gif",
        ".bmp",
        ".tiff",
        ".tif",
        ".htm",
        ".html",
    ]
    pdf_exts: list[str] = [".pdf"]
    content_type_rules: list[ContentTypeRule] = [
        ContentTypeRule(match="text/", mode="startswith", pipeline="knowhere"),
        ContentTypeRule(match="markdown", mode="contains", pipeline="knowhere"),
        ContentTypeRule(match="msword", mode="contains", pipeline="knowhere"),
        ContentTypeRule(match="wordprocessing", mode="contains", pipeline="knowhere"),
        ContentTypeRule(match="image/", mode="startswith", pipeline="pixelrag"),
        ContentTypeRule(match="spreadsheet", mode="contains", pipeline="pixelrag"),
        ContentTypeRule(match="excel", mode="contains", pipeline="pixelrag"),
    ]
    default_pipeline: str = "knowhere"


class SourceTypeRule(BaseModel):
    """source_type inference keyword rule (metadata tag only; does not affect routing)."""

    keywords: list[str]
    source_type: str


class IngestSourceTypeSettings(BaseModel):
    """source_type inference config: ordered rules (first match wins) plus a default value."""

    rules: list[SourceTypeRule] = [
        SourceTypeRule(
            keywords=[
                "财报",
                "报表",
                "资产负债",
                "利润表",
                "现金流量",
                "审计报告",
                "financial",
                "balance",
                "income",
                "cashflow",
                "table",
            ],
            source_type="financial",
        ),
        SourceTypeRule(
            keywords=[
                "政策",
                "法规",
                "条例",
                "办法",
                "通知",
                "公告",
                "policy",
                "law",
                "regulation",
                "act",
            ],
            source_type="policy",
        ),
        SourceTypeRule(
            keywords=["招标", "中标", "投标", "采购", "bidding", "tender"],
            source_type="bidding",
        ),
        SourceTypeRule(
            keywords=["税", "税务", "个税", "增值税", "tax", "vat"],
            source_type="tax",
        ),
        SourceTypeRule(
            keywords=["工商", "企业信息", "营业执照", "公司简介", "business", "company"],
            source_type="business",
        ),
    ]
    default: str = "other"


class UrlPrefetchConfig(BaseModel):
    """URL preflight config (validate/ssrf/prefetch before dispatching ingest-by-URL)."""

    timeout_sec: float = 10.0
    max_redirects: int = 3


class IngestSettings(BaseModel):
    """Aggregate config for ingest routing and source_type inference."""

    routing: IngestRoutingSettings = IngestRoutingSettings()
    source_type: IngestSourceTypeSettings = IngestSourceTypeSettings()
    url_prefetch: UrlPrefetchConfig = UrlPrefetchConfig()


class AuthSettings(BaseModel):
    enabled: bool
    api_key: str


class TelemetrySettings(BaseModel):
    """Telemetry and observability config.

    structlog (AI event JSONL) + loguru (ops logs) + OpenTelemetry tracing.
    All fields carry defaults so older settings.yaml files without a
    ``telemetry`` section still load.
    """

    enabled: bool = True
    service_name: str = "eagle-rag"
    environment: str = "dev"
    ai_log_file: str = "logs/ai_telemetry.jsonl"
    ai_log_level: str = "INFO"
    ai_log_max_bytes: int = 10485760
    ai_log_backup_count: int = 10
    prompt_truncate: int = 512
    completion_truncate: int = 1024
    op_log_file: str = "logs/eagle_rag.log"
    op_log_level: str = "INFO"
    op_log_rotation: str = "10 MB"
    op_log_retention: str = "30 days"
    tracing_enabled: bool = False
    otlp_endpoint: str = ""
    otlp_insecure: bool = True
    redis_log_channel: str = "logs"


class McpOAuthSettings(BaseModel):
    """MCP OAuth 2.1 auth config (optional, disabled by default).

    Integrates an external Authorization Server (GitHub or self-hosted); handled by fastmcp.
    """

    enabled: bool = False
    issuer_url: str = ""
    client_id: str = ""
    client_secret: str = ""
    required_scopes: list[str] = []


class McpMtlsSettings(BaseModel):
    """MCP inter-pod mTLS config (optional, disabled by default; provided by the Service Mesh)."""

    enabled: bool = False


class McpSettings(BaseModel):
    """MCP cloud HTTP deployment config (fastmcp streamable HTTP, stateless + JSON-only).

    All fields carry defaults; without an ``mcp`` section the cloud HTTP mode is used.
    When ``redis_url`` is empty the runtime falls back to ``celery.broker_url``.
    """

    transport: Literal["stdio", "http"] = "http"
    streamable_http_path: str = "/mcp"
    stateless_http: bool = True
    json_response: bool = True
    standalone: bool = False
    host: str = "0.0.0.0"
    port: int = 8081
    workers: int = 4
    tool_timeout: float = 30.0
    max_retries: int = 3
    circuit_fail_threshold: int = 5
    cache_ttl: int = 300
    event_store_enabled: bool = False
    redis_url: str = ""
    auth_provider: Literal["static-token", "oauth-github", "oauth-custom"] = "static-token"
    oauth: McpOAuthSettings = McpOAuthSettings()
    mtls: McpMtlsSettings = McpMtlsSettings()


class Settings(BaseSettings):
    """Top-level config aggregate; YAML loading + environment variable overrides."""

    model_config = SettingsConfigDict(
        env_prefix="EAGLE_RAG_",
        env_nested_delimiter="__",
        extra="ignore",
    )

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
    ingest: IngestSettings = IngestSettings()
    auth: AuthSettings
    telemetry: TelemetrySettings = TelemetrySettings()
    mcp: McpSettings = McpSettings()


def _expand_vars(value: Any) -> Any:
    """Recursively expand ``${VAR:-default}`` placeholders in dict/list/str values.

    Standard ``$VAR``/``${VAR}`` forms are first handled by ``os.path.expandvars``,
    then a regex fills in the ``${VAR:-default}`` default-value syntax.
    """
    if isinstance(value, str):
        # Standard shell variables (no default-value syntax).
        value = os.path.expandvars(value)
        # Repeat until stable to support nested references
        # (max 10 rounds to guard against infinite loops).
        previous: str | None = None
        for _ in range(10):
            if previous == value:
                break
            previous = value
            value = _VAR_PATTERN.sub(_replace_var, value)
        return value
    if isinstance(value, dict):
        return {k: _expand_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_vars(v) for v in value]
    return value


def _replace_var(match: re.Match[str]) -> str:
    var_name = match.group(1)
    default = match.group(2) if match.group(2) is not None else ""
    return os.environ.get(var_name, default)


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("rb") as fp:
        raw = yaml.safe_load(fp)
    if not isinstance(raw, dict):
        raise ValueError(f"settings.yaml root must be a mapping, got {type(raw).__name__}: {path}")
    return _expand_vars(raw)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton ``Settings``.

    Reads the YAML file pointed to by ``EAGLE_RAG_SETTINGS_PATH`` first, falling back
    to the in-package ``settings.yaml``. After YAML placeholder expansion, ``Settings``
    is constructed and may still be overridden by ``EAGLE_RAG_<SECTION>__<FIELD>``
    environment variables.
    """
    path_str = os.environ.get("EAGLE_RAG_SETTINGS_PATH", str(_DEFAULT_SETTINGS_PATH))
    path = Path(path_str)
    data = _load_yaml(path)
    return Settings(**data)
