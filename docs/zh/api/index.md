# Eagle-RAG REST API

Eagle-RAG 暴露 **FastAPI** HTTP API（默认端口 **8000**）。它是 Next.js 控制台、外部 Agent、Celery worker 与 MCP 客户端的集成面。端点覆盖完整 RAG 生命周期：**摄入 → 索引 → 检索 → 生成**，以及多租户知识库管理与运维探测。

!!! note "说明"
    打开 [`http://localhost:8000/docs`](http://localhost:8000/docs) 查看由路由 `response_model` 定义生成的 Swagger UI；[`/openapi.json`](http://localhost:8000/openapi.json) 提供机器可读的 schema 导出。

## 架构位置

```mermaid
flowchart TB
  subgraph Clients
    FE["Next.js console"]
    AG["External agents"]
    MCP["MCP / FastMCP"]
  end
  subgraph API["FastAPI :8000"]
    Q["query / search / sessions"]
    I["ingest / tasks"]
    D["documents / images / tags"]
    KB["knowledge_bases"]
    OPS["health / admin / notifications"]
  end
  subgraph Services
    PG[(PostgreSQL)]
    MV[(Milvus)]
    RD[(Redis / Celery)]
    MN[(MinIO)]
  end
  FE --> API
  AG --> API
  MCP --> Services
  API --> PG
  API --> MV
  API --> RD
  API --> MN
```

MCP 工具**直接调用服务层**（无 HTTP 自调用）。`eagle_rag/api/*.py` 中的 REST 路由共享同一套引擎与存储。

---

## 按标签划分的 API 地图

| OpenAPI 标签 | 基础路径 | 指南 |
|-------------|------------|-------|
| **query** | `/query`、`/search`、`/sessions` | [查询](query.md)、[会话](sessions.md) |
| **ingest** | `/ingest`、`/tasks`、`/ingest/queue-metrics` | [摄入](ingest.md)、[任务](tasks.md) |
| **documents** | `/documents`、`/images` | [文档](documents.md) |
| **tags** | `/tags` | [查询 → 标签](query.md#get-tags) |
| **knowledge_bases** | `/knowledge_bases` | [知识库](knowledge-bases.md) |
| **attachments** | `/attachments` | [附件](attachments.md) |
| **notifications** | `/notifications` | [通知](notifications.md) |
| **health** | `/health`、`/mcp/tools` | [健康检查与 admin](health-admin.md) |
| **admin** | `/admin/*` | [健康检查与 admin](health-admin.md) |

基础设施路由（不一定出现在标签摘要中）：

| 路径 | 用途 |
|------|---------|
| `GET /` | 应用名、版本、文档链接（`RootResponse`） |
| `GET /metrics` | Prometheus 抓取 |
| `GET /health`（metrics 模块） | Docker / HAProxy 存活探测 |

MCP 可流式 HTTP 挂载于 `settings.mcp.streamable_http_path`（默认 `/mcp`）。见 [MCP 工具](mcp-tools.md)。

---

## 请求 / 响应约定

### 分页

列表端点返回 `PaginatedMeta`：

```json
{ "items": […], "limit": 50, "offset": 0 }
```

部分列表端点还包含 `total`（文档、知识库）或 `error`（降级的任务列表）。

### 删除确认

`DELETE` 路由返回 `DeletedResponse`：

```json
{ "deleted": true }
```

`deleted: false` 不用于 404 —— 资源不存在时直接返回 **404**。

### 日期时间

通过 `iso_datetime()` 辅助函数（`eagle_rag/api/schemas/_helpers.py`）以 UTC ISO 8601 字符串返回。

### 内容协商

- JSON 请求体：`Content-Type: application/json`
- 文件摄入：`multipart/form-data`
- SSE 流：`text/event-stream`（无 `Accept` 协商）

---

## 多租户（`kb_name`）

大多数写入与查询端点接受可选 **`kb_name`** —— 知识库标识符（`finance`、`pharma`、`default` 等）。

传播链：

| 层 | 用法 |
|-------|-------|
| PostgreSQL | `documents.kb_name`、`sessions.kb_name`、`task_audit.kb_name` |
| Milvus | 标量过滤 `kb_name == 'pharma'` |
| Celery | 任务 kwargs `kb_name=…` |
| 去重主键 | `(sha256, kb_name)` —— 相同字节可存在于多个 KB |

见 [多租户](../architecture/multi-tenancy.md)。

---

## 范围过滤（`ScopeSelection`）

`/query` 与 `/search` 上的高级召回范围：

```json
{
  "kb_names": ["pharma", "finance"],
  "document_ids": ["doc_abc123"],
  "tags": ["clinical-trial"]
}
```

**并集（OR）语义** —— 若 chunk 属于任一列出的 KB、显式文档，或由任一标签解析出的文档，即匹配。在 `router_engine._resolve_scope_filter` 中解析并下推到 Milvus。完整说明：[查询 → 范围过滤](query.md#scope-filter--milvus-pushdown)。

---

## 流式（SSE）概览

| 端点 | 事件 |
|----------|--------|
| `POST /query/stream` | `session`、`step`、`sources`、`token`、`done`、`error` |
| `POST /search/stream` | `step`、`sources`、`done`、`error` |
| `GET /tasks/{job_id}/stream` | `progress`、`timeout` |
| `GET /admin/logs` | `log`、`heartbeat` |

线格式与字节级示例：[查询 → SSE 协议](query.md#post-querystream--sse-protocol)。

---

## 错误模型

除非另有说明，FastAPI 返回标准 HTTP 错误：

| 状态码 | 典型 `detail` | 降级行为 |
|--------|------------------|-------------------|
| `404` | 资源未找到（`session not found: …`） | — |
| `409` | 冲突（`kb_name already exists`） | — |
| `422` | 校验失败（`Either file or url is required`） | URL 预取结构化 detail |
| `500` | 引擎 / 意外错误（`detail` 字符串） | 摄入可能返回 JSON 体 |
| `502` | Celery 派发失败（任务重试） | — |
| `503` | 数据库不可用 | `GET /sessions` → 空列表 |

SSE 端点在流已开始后发出 `error` **事件**，而非 HTTP 错误体。

### 幂等性摘要

| 操作 | 是否幂等 |
|-----------|-----------|
| `POST /ingest`（相同文件哈希 + kb） | **是** —— `dedup_hit: true`，HTTP 200 |
| `POST /query` | **否** —— 追加消息 |
| `POST /attachments` | **否** —— 每次上传新 `attachment_id` |
| `DELETE /*` | **是** —— 第二次删除 → 404 |
| `PATCH /sessions/{id}` | **是** —— 相同标题 |

---

## 认证

REST 路由默认**无认证中间件**。部署于私有网络、VPN 或 API 网关之后。

MCP 可通过 `settings.auth.enabled` 与 `configure_mcp_auth()` 单独启用认证（静态 token、GitHub OAuth、自定义 JWT）。见 [MCP 工具](mcp-tools.md)。

---

## OpenAPI 生成（前端）

Next.js 控制台从实时 OpenAPI 文档重新生成 TypeScript SDK：

```bash
# API 必须运行（或设置 OPENAPI_URL）
cd frontend && bun run api:gen
```

配置：`frontend/openapi-ts.config.ts` —— 输入 `${API_BASE}/openapi.json`，输出 `lib/api/generated/`。`predev` 会自动运行 `api:gen`。

---

## 配置面

服务端 host、端口、模型密钥、Milvus URI、Celery broker 与 MCP 传输从 `eagle_rag/settings.yaml` 加载，支持 `${ENV:-default}` 替换。见 [配置](../getting-started/configuration.md)。

---

## 集成检查清单

- [ ] 首次请求前执行 `alembic upgrade head`（或 `task db:migrate`）
- [ ] 至少注册一个知识库（`POST /knowledge_bases`）
- [ ] 启动 `router_queue`、`knowhere_queue`、`pixelrag_queue` 的 Celery worker
- [ ] 将客户端指向 `http://<host>:8000`（或反向代理 + `NEXT_PUBLIC_API_BASE`）
- [ ] 交互式 UX 使用 `/query/stream`；检索基准使用 `/search`
- [ ] API schema 变更后运行 `bun run api:gen`

---

## 相关文档

| 主题 | 链接 |
|-------|------|
| 后端路由布局 | [API 层](../backend/api-layer.md) |
| 检索路由 | [路由引擎](../backend/router-engine.md) |
| 前端 SDK | [API 客户端](../frontend/api-client.md) |
| MCP 实现 | [MCP 服务端（后端）](../backend/mcp-server.md) |
| Schema 参考 | [Schemas](../backend/schemas.md) |
