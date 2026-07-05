# MCP 工具

Eagle-RAG 通过 **FastMCP**（`eagle_rag/api/mcp_server.py`）向 LLM Agent 暴露四个 MCP 工具。工具**直接**调用服务层 —— 不对 `/query` 或 `/ingest` 做 HTTP 往返。

传输：可流式 HTTP，位于 `settings.mcp.streamable_http_path`（默认 `/mcp`）；子进程客户端可回退 stdio。

REST 发现：`GET /mcp/tools` 返回 `TOOL_DEFINITIONS` 元数据。

---

## 工具目录

| 工具 | 服务 | 返回 |
|------|---------|---------|
| `ingest` | `runner.ingest` | `{ job_id, status, document_id, dedup_hit }` |
| `query` | `EagleRouterQueryEngine.query` | `{ answer, sources, route, steps }` |
| `retrieve_text` | `KnowhereGraphRetriever` | `[{ node_id, text, score, metadata }]` |
| `retrieve_visual` | `PixelRAGVisualRetriever` | `[{ image_id, document_id, page, position, score }]` |

失败时工具返回 `{ "error": "…" }`（dict）或 `[{ "error": "…" }]`（list），不终止 MCP 会话。

---

## `ingest`

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
      "enum": ["policy", "financial", "business", "bidding", "tax", "other"]
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
- 异步 Celery 派发 —— 与 `POST /ingest` 相同
- 包装于 `resilient_call` + 熔断器

### 错误字符串

| 模式 | 含义 |
|---------|---------|
| `circuit_open: ingest` | 熔断器打开 |
| `timeout: ingest` | 调用超时 |
| `{ExceptionName}: {message}` | 意外失败 |

---

## `query`

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

- 无会话持久化（与 REST `/query` 不同）
- `scope_filter` 并集语义与 REST 相同 —— 见 [查询](query.md#scope-filter--milvus-pushdown)
- 响应裁剪为四键：`answer`、`sources`、`route`、`steps`

### REST 与 MCP

| 特性 | REST `/query` | MCP `query` |
|---------|---------------|-------------|
| 流式 | SSE `/query/stream` | 否 —— 单次响应 |
| 会话 | 是 | 否 |
| 附件 | 是 | 否 |
| 遥测 | `ai_logger` | `record_mcp_call` |

---

## `retrieve_text`

### 参数

| 名称 | 类型 | 默认 | 说明 |
|------|------|---------|-------------|
| `query` | string | 必填 | 检索查询 |
| `scope` | string[] | 可选 | 检索后过滤 `document_id` |
| `top_k` | integer | 5 | 结果数量 |
| `kb_name` | string | 可选 | Milvus KB 过滤 |

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

**缓存：** `mcp_cache` 键为 `(tool, query, scope, top_k, kb_name)` —— 命中跳过 Milvus。

**范围过滤：** MCP `retrieve_text` **不接受** `scope_filter` —— 使用 `scope` 文档列表或 REST `/search` 做标签/KB 并集。

---

## `retrieve_visual`

### 参数

与 `retrieve_text` 相同（`query`、`scope`、`top_k`、`kb_name`）。

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

与 `retrieve_text` 类似缓存。

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

| 提供方 | 机制 |
|----------|-----------|
| `static-token` | `Authorization: Bearer <AUTH_API_KEY>`，scope `eagle-rag:tools` |
| `oauth-github` | GitHub OAuth 2.1 代理 |
| `oauth-custom` | 经 JWKS 的 JWT（`issuer_url/.well-known/jwks.json`） |

REST 路由保持无认证，除非单独添加网关规则。

---

## Agent 集成示例

```python
# llama-index-tools-mcp BasicMCPClient (stdio)
from llama_index.tools.mcp import BasicMCPClient

client = BasicMCPClient("python", ["-m", "eagle_rag.api.mcp_server"])
tools = await client.list_tools()
result = await client.call_tool("query", {"query": "…", "kb_name": "finance"})
```

HTTP 传输：将 MCP 客户端指向 `http://host:8001/mcp`（端口来自 `settings.mcp.port`）。

---

## 相关文档

- [MCP 服务端（后端）](../backend/mcp-server.md)
- [健康检查与 admin](health-admin.md) —— MCP 仪表盘 + 调用日志
- [查询](query.md) —— `query` 工具的 REST 对等
- [摄入](ingest.md) —— `ingest` 工具的 REST 对等
