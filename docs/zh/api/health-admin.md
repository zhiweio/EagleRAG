# 健康检查与 Admin API

`/health` 控制台页的运维探测与仪表盘。`eagle_rag/api/health.py` 中两个路由：

| 路由 | 前缀 | 标签 |
|--------|--------|-----|
| `router` | `/health`、`/mcp/tools` | `health` |
| `admin_router` | `/admin` | `admin` |

探测超时：每个依赖 **3 s**（`_PROBE_TIMEOUT`）。所有探测只读。

---

## `GET /health`

`HealthResponse` —— 服务网格的依赖连通性。

### 探测的依赖

| 名称 | 检查 |
|------|-------|
| `postgresql` | 异步 DB ping |
| `redis` | Broker 连通性 |
| `milvus` | 列出集合（`eagle_text`、`eagle_visual`） |
| `minio` | Bucket head |
| `knowhere` | HTTP GET `settings.knowhere.base_url` |
| `pixelrag` | 导入 `pixelrag_render` / `pixelrag_embed`（库，非 serve） |
| `vlm` | Qwen-VL 可达性 |
| `celery` | Inspect 活跃 worker |

每个依赖返回 `DependencyStatus`：

```json
{
  "name": "milvus",
  "status": "up",
  "latency_ms": 42,
  "detail": "collections: eagle_text, eagle_visual",
  "uptime": "2 hours"
}
```

`uptime` 使用进程内单调时钟跟踪（`_UPTIME_SINCE`）—— API 重启后重置。

### 摘要块

`DependencySummary`：`up` / `down` / `unknown` 计数、整体 `status`、`version`（`eagle_rag.__version__`）。

---

## `GET /mcp/tools`

`McpToolsResponse` —— `mcp_server.py` 中 `TOOL_DEFINITIONS` 的静态工具目录（无异步 `list_tools()`）。

```json
{
  "tools": [
    {
      "name": "ingest",
      "description": "…",
      "parameters": { "type": "object", "properties": { … } }
    }
  ]
}
```

驱动 `McpServerDashboard` 工具表。完整语义：[MCP 工具](mcp-tools.md)。

---

## Admin 路由（`/admin/*`）

### 基础设施仪表盘

| 路径 | 响应 | 内容 |
|------|----------|---------|
| `GET /admin/celery` | `AdminCeleryResponse` | Worker、活跃任务、队列深度 |
| `GET /admin/milvus` | `AdminMilvusResponse` | 集合行数、按 KB 分区 |
| `GET /admin/minio` | `AdminMinioResponse` | Bucket、对象数 |
| `GET /admin/redis` | `AdminRedisResponse` | 内存、已连接客户端 |
| `GET /admin/knowhere` | `AdminKnowhereResponse` | 远程解析器健康 |
| `GET /admin/pixelrag` | `AdminPixelragResponse` | 进程内库状态 |
| `GET /admin/vlm` | `AdminVlmResponse` | Qwen-VL 探测 |
| `GET /admin/mcp` | `AdminMcpResponse` | 近期 MCP 调用日志 |
| `GET /admin/config` | `AdminConfigOut` | 脱敏配置快照 |
| `GET /admin/probes` | `AdminProbesResponse` | 探测配置 + 最近结果 |

### 变更类 admin 操作

| 路径 | 方法 | 用途 |
|------|--------|---------|
| `/admin/model-router` | `GET` / `PATCH` | 读取/更新路由模式覆盖 |
| `/admin/resource-limits` | `GET` / `PATCH` | 运维调参旋钮 |
| `/admin/actions/{action}` | `POST` | 受控维护动作 |

响应使用 `AdminActionResult`，含 `success`、`detail`。

---

## `GET /admin/logs`（SSE）

`LiveLogsTab` 的实时日志尾随。

| 事件 | 载荷 |
|-------|---------|
| `log` | `{ level, message, timestamp, … }` |
| `heartbeat` | 保活 |

前端：`lib/api/sse.ts` 中 `streamAdminLogs`。

线格式与其他 SSE 端点相同（`event:` + `data:` JSON + 空行）。

---

## MCP 调用日志

`GET /admin/mcp` 包含 `McpCallLogOut` 条目：

- `tool_name`、`arguments`、`result_summary`、`caller`、`latency_ms`、`timestamp`

由 MCP 工具包装器中的 `record_mcp_call` 写入。

---

## 错误处理

| 情况 | 行为 |
|-----------|-----------|
| 单个探测失败 | 该依赖 `status: "down"`；`/health` 仍 HTTP 200 |
| Admin DB 读取失败 | **503** 或部分空区块 |
| SSE 日志流错误 | 关闭连接；客户端重连 |

---

## 前端集成

`/health` 路由 → `HealthHeaderActions`、`ServiceGrid`、各服务仪表盘（`CeleryDashboard`、`KnowhereDashboard`、`McpServerDashboard` 等）。

TanStack Query keys：`["health"]`、`["admin", "celery"]` 等 —— 见 `useHealth.ts`。

见 [健康模块](../frontend/health-module.md)。

---

## 相关文档

- [MCP 工具](mcp-tools.md)
- [健康模块](../frontend/health-module.md)
- [MCP 服务端（后端）](../backend/mcp-server.md)
- [安装](../getting-started/installation.md) —— 依赖搭建
