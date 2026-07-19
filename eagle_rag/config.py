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
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = [
    "Settings",
    "AppSettings",
    "MilvusSettings",
    "KnowhereSettings",
    "KnowhereParserSettings",
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
    "PluginSettings",
    "get_settings",
    "plugin_options",
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
    db_name: str = "default"
    text_collection: str
    visual_collection: str
    dim_text: int
    dim_visual: int
    visual_index_type: str  # hnsw | diskann
    auto_create_db: bool = True


class KnowhereParserSettings(BaseModel):
    mineru_api_keys: str = ""
    mineru_url: str = "https://mineru.net/api/v4"
    tmp_path: str = ""
    use_llm_nav_summary: bool = True
    llm_mock_enabled: bool = False
    llm_api_key: str = ""
    llm_url: str = ""
    llm_model: str = ""
    hierarchy_llm_model: str = ""
    image_model: str = ""
    image_model_max: str = ""


class KnowhereSettings(BaseModel):
    mode: Literal["api", "parser"] = "api"
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
    parser: KnowhereParserSettings = Field(default_factory=KnowhereParserSettings)


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
    """Core visual embedding (PixelRAG tiles / image queries).

    ``provider``:
    - ``pixelrag`` — local Hugging Face Qwen3-VL-Embedding (torch/transformers)
    - ``dashscope`` — Bailian ``qwen3-vl-embedding`` via DashScope MultiModalEmbedding

    Ingest and query must use the same provider; switching requires rebuilding
    ``eagle_visual`` (vectors are not mixed across backends).
    """

    provider: str
    model: str
    dim: int
    api_key: str = ""
    base_url: str = ""  # native DashScope API base (not OpenAI-compatible)
    batch_size: int = 5
    timeout_s: float = 60.0
    max_retries: int = 3


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
    # Two-stage parent-document retrieval on ``eagle_text`` (G5).
    parent_doc_retrieval: bool = True
    # RRF fusion constant for multi-collection merge (G8).
    rrf_k: int = 60
    # ANN recall width before rerank; final response is capped at ``final_top_k``.
    recall_top_k: int = 30
    final_top_k: int = 5
    # Dense vs sparse weight for in-process hybrid fusion (1.0 = dense only).
    hybrid_alpha: float = 0.6
    # Enable dense+sparse hybrid fusion on biomed text collections.
    hybrid_text_enabled: bool = True


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
    max_image_bytes: int = 5_242_880
    allowed_image_exts: list[str] = Field(
        default_factory=lambda: [
            ".png",
            ".jpg",
            ".jpeg",
            ".webp",
            ".gif",
            ".bmp",
            ".tiff",
            ".tif",
        ]
    )
    max_count: int = 1
    image_only_query: str = "请根据上传的图片，结合知识库相关内容回答。"
    visual_merge_fetch_multiplier: int = 2
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
    """source_type inference: optional keyword rules; default is free-form ``other``.

    Industry-specific keyword lists belong in domain plugins / deployment YAML —
    Core ships an empty rule list so finance/tax/policy are not hard-coded.
    """

    rules: list[SourceTypeRule] = []
    default: str = "other"


class UrlPrefetchConfig(BaseModel):
    """URL preflight config for ``POST /ingest/validate/url`` (and enqueue SSRF)."""

    dns_timeout_sec: float = 3.0
    timeout_sec: float = 5.0
    max_redirects: int = 3
    pdf_download_timeout_sec: float = 30.0
    verify_ssl: bool = True
    # After SSRF passes, retry once with verify=False when the peer sends an
    # incomplete certificate chain (common on some corporate sites).
    ssl_verify_fallback: bool = True


class IngestLimitsConfig(BaseModel):
    """Early size/page guards aligned with MinerU Precision Extract API caps.

    Defaults match mineru.net Precision Extract: 200 MiB / 200 pages per file.
    """

    enabled: bool = True
    max_file_bytes: int = 209_715_200  # 200 MiB
    max_pdf_pages: int = 200


class IngestSettings(BaseModel):
    """Aggregate config for ingest routing and source_type inference."""

    routing: IngestRoutingSettings = IngestRoutingSettings()
    source_type: IngestSourceTypeSettings = IngestSourceTypeSettings()
    url_prefetch: UrlPrefetchConfig = UrlPrefetchConfig()
    limits: IngestLimitsConfig = Field(default_factory=IngestLimitsConfig)


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
    # PluginAudit multi-sink knobs (memory ring + Redis recent + AI JSONL + metrics).
    plugin_audit_enabled: bool = True
    plugin_audit_ring_cap: int = 1000
    plugin_audit_redis_enabled: bool = True
    plugin_audit_health_limit: int = 50


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


class PluginSettings(BaseModel):
    """In-process plugin loading and instance namespace binding.

    Per-plugin knobs live under ``options`` keyed by plugin namespace (e.g.
    ``options.biomed.default_dual_text_search``), not as Core-typed fields.
    """

    enabled: list[str] = ["eagle_rag.plugins.core_defaults"]
    default_namespace: str = "core"
    allow_namespace_override: bool = False
    query_assemble_enabled: bool = True
    options: dict[str, Any] = Field(default_factory=dict)


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
    plugins: PluginSettings = Field(default_factory=PluginSettings)
    # Deployment profile name (P2-4); applied in ``get_settings`` from YAML ``profiles:``.
    active_profile: str | None = None


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


def _apply_profile(data: dict[str, Any]) -> dict[str, Any]:
    """Merge ``profiles.<name>`` overlays when ``EAGLE_RAG_PROFILE`` / ``active_profile`` is set.

    Profile keys overlay top-level settings (deep-merge for nested mappings). Env
    ``EAGLE_RAG_PROFILE`` wins over YAML ``active_profile``.
    """
    profile_name = (
        os.environ.get("EAGLE_RAG_PROFILE")
        or os.environ.get("PLUGIN_PROFILE")
        or data.get("active_profile")
        or ""
    )
    profile_name = str(profile_name).strip()
    if not profile_name:
        return data

    profiles = data.get("profiles")
    if not isinstance(profiles, dict) or profile_name not in profiles:
        raise ValueError(
            f"unknown deployment profile {profile_name!r}; "
            f"known={sorted(profiles) if isinstance(profiles, dict) else []}"
        )
    overlay = profiles[profile_name]
    if not isinstance(overlay, dict):
        raise ValueError(f"profile {profile_name!r} must be a mapping")

    merged = dict(data)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            nested = dict(merged[key])
            nested.update(value)
            merged[key] = nested
        else:
            merged[key] = value
    merged["active_profile"] = profile_name
    return merged


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton ``Settings``.

    Reads the YAML file pointed to by ``EAGLE_RAG_SETTINGS_PATH`` first, falling back
    to the in-package ``settings.yaml``. After YAML placeholder expansion and optional
    profile merge (``EAGLE_RAG_PROFILE``), ``Settings`` is constructed and may still be
    overridden by ``EAGLE_RAG_<SECTION>__<FIELD>`` environment variables.
    """
    path_str = os.environ.get("EAGLE_RAG_SETTINGS_PATH", str(_DEFAULT_SETTINGS_PATH))
    path = Path(path_str)
    data = _apply_profile(_load_yaml(path))
    return Settings(**data)


def plugin_options(namespace: str, settings: Settings | None = None) -> dict[str, Any]:
    """Return ``settings.plugins.options[namespace]`` (empty dict when absent)."""
    cfg = settings or get_settings()
    raw = cfg.plugins.options.get(namespace) if cfg.plugins.options else None
    return dict(raw) if isinstance(raw, dict) else {}
