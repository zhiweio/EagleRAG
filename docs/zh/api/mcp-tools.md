# MCP 工具

Eagle-RAG 通过 **FastMCP**（`eagle_rag/api/mcp_server.py` + `eagle_rag/plugins/mcp_registry.py`）向 LLM Agent 暴露**仅 RAG** 的 MCP 工具。工具**直接**调用服务层 — 不对 `/query` 或 `/ingest` 做 HTTP 自调用。

传输：流式 HTTP 位于 `settings.mcp.streamable_http_path`（默认 `/mcp`），子进程客户端可回退 stdio。

REST 发现：`GET /mcp/tools` 返回 `TOOL_DEFINITIONS` 元数据。

!!! important "命名与范围"
    Core 工具使用 `core_*` 前缀（无遗留别名）。实例仅注册 `core_*` + `default_namespace` 插件工具（G3）。工具必须检索/组装上下文 — 副作用命名被禁止（[ADR-008](../architecture/adr/008-rag-only-plugin-platform.md)）。域示例：匹配 profile 激活时的 `biomed_query_entities`、`lakehouse_bi_query_semantic_context`。

---

## 工具目录（Core）

| 工具 | 服务 | 返回 |
|------|---------|---------|
| `core_ingest` | `runner.ingest` | `{ job_id, status, document_id, dedup_hit }` |
| `core_query` | `EagleRouterQueryEngine.query` | `{ answer, sources, route, steps }` |
| `core_retrieve_text` | `KnowhereGraphRetriever` | `[{ node_id, text, score, metadata }]` |
| `core_retrieve_visual` | `PixelRAGVisualRetriever` | `[{ image_id, document_id, page, position, score }]` |

域示例（匹配 profile 启用时）：`biomed_query_entities`、`lakehouse_bi_query_semantic_context`。

**G3 暴露规则：** MCP `list_tools` / FastMCP 注册包含 `core_*` 以及 `settings.plugins.default_namespace` 的工具 — 非每个已加载插件模块。

失败时工具返回 `{ "error": "…" }`（dict）或 `[{ "error": "…" }]`（list），不终止 MCP 会话。

---

## `core_ingest`

### 参数（`TOOL_DEFINITIONS`）

```json
{
  "type": "object",
  "required": ["source_uri"],
  "properties": {
    "source_uri": {
      "type": "string",
      "description": "File path or web URL (http/https prefix is treated as a URL)"
    },
    "source_type": {
      "type": "string",
      "description": "Free-form metadata hint (not an enum; Core has empty keyword rules by default)"
    },
    "kb_name": {
      "type": "string",
      "description": "Knowledge base id (multi-tenant); optional, defaults to config"
    }
  }
}
```

### 行为

- `http://` / `https://` → `ingest(source_uri=…)`
- 否则 → `ingest(file_path=…)`
- 异步 Celery 分发 — 与 `POST /ingest` 相同
- 包装在 `resilient_call` + 熔断器内

### 错误字符串

| 模式 | 含义 |
|---------|---------|
| `circuit_open: ingest` | 熔断器打开 |
| `timeout: ingest` | 调用超时 |
| `{ExceptionName}: {message}` | 意外失败 |

---

## `core_query`

### 参数

```json
{
  "type": "object",
  "required": ["query"],
  "properties": {
    "query": { "type": "string" },
    "mode": { "type": "string", "enum": ["auto", "text", "visual", "hybrid"] },
    "scope": { "type": "array", "items": { "type": "string" } },
    "kb_name": { "type": "string" },
    "scope_filter": {
      "type": "object",
      "properties": {
        "kb_names": { "type": "array", "items": { "type": "string" } },
        "document_ids": { "type": "array", "items": { "type": "string" } },
        "tags": { "type": "array", "items": { "type": "string" } }
      }
    }
  }
}
```

### 行为

- 无会话持久化（不同于 REST `/query`）
- `scope_filter` 并集语义与 REST 相同 — 见 [查询](query.md#scope-filter--milvus-pushdown)
- 响应裁剪为四键：`answer`、`sources`、`route`、`steps`

### REST vs MCP

| 功能 | REST `/query` | MCP `core_query` |
|---------|---------------|-------------|
| 流式 | SSE `/query/stream` | 否 — 单次响应 |
| 会话 | 是 | 否 |
| 附件 | 是 | 否 |
| 遥测 | `ai_logger` | `record_mcp_call` |

---

## `core_retrieve_text`

### 参数

| 名称 | 类型 | 默认 | 描述 |
|------|------|---------|-------------|
| `query` | string | required | 检索查询 |
| `scope` | string[] | optional | 后过滤 `document_id` |
| `top_k` | integer | 5 | 结果数 |
| `kb_name` | string | optional | Milvus KB 过滤 |

### 返回形状

```json
[
  {
    "node_id": "…",
    "text": "chunk body",
    "score": 0.87,
    "metadata": {
      "path": "/section/3",
      "level": 2,
      "summary": "…",
      "document_id": "doc_abc",
      "source_type": "policy"
    }
  }
]
```

**缓存：** `mcp_cache` 键为 `(tool, query, scope, top_k, kb_name)` — 命中跳过 Milvus。

**Scope filter：** MCP `core_retrieve_text` **不接受** `scope_filter` — 使用 `scope` 文档列表或 REST `/search` 做标签/KB 并集。

---

## `core_retrieve_visual`

### 参数

与 `core_retrieve_text` 相同（`query`、`scope`、`top_k`、`kb_name`）。

### 返回形状

```json
[
  {
    "image_id": "img_abc",
    "document_id": "doc_xyz",
    "page": 3,
    "position": "0.12,0.45,0.88,0.92",
    "score": 0.91
  }
]
```

与 `core_retrieve_text` 类似缓存。

---

## 韧性层

| 机制 | 模块 | 效果 |
|-----------|--------|--------|
| 熔断器 | `mcp_resilience` | `{ error: "circuit_open: …" }` |
| 超时 | `resilient_call` | `{ error: "timeout: …" }` |
| 指标 | `with_metrics` 装饰器 | Prometheus 计数器 |
| 调用日志 | `admin.mcp_log` | `/admin/mcp` 审计轨迹 |

---

## 认证（`configure_mcp_auth`）

当 `settings.auth.enabled`：

| Provider | 机制 |
|----------|-----------|
| `static-token` | `Authorization: Bearer <AUTH_API_KEY>` scope `eagle-rag:tools` |
| `oauth-github` | GitHub OAuth 2.1 代理 |
| `oauth-custom` | 经 JWKS 的 JWT（`issuer_url/.well-known/jwks.json`） |

REST 路由默认无认证，除非单独添加网关规则。

---

## Agent 集成示例

```python
# llama-index-tools-mcp BasicMCPClient (stdio)
from llama_index.tools.mcp import BasicMCPClient

client = BasicMCPClient("python", ["-m", "eagle_rag.api.mcp_server"])
tools = await client.list_tools()
result = await client.call_tool("core_query", {"query": "…", "kb_name": "finance"})
```

HTTP 传输：将 MCP 客户端指向 `http://host:8001/mcp`（端口来自 `settings.mcp.port`）。

---

## 相关文档

- [MCP 服务器（后端）](../backend/mcp-server.md)
- [健康与管理](health-admin.md) — MCP 面板 + 调用日志
- [查询](query.md) — `core_query` 的 REST 对等
- [入库](ingest.md) — `core_ingest` 的 REST 对等
