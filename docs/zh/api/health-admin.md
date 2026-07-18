# 健康与管理 API

面向 `/health` 控制台页面的运维探测与面板。`eagle_rag/api/health.py` 中两个路由：

| 路由 | 前缀 | 标签 |
|--------|--------|-----|
| `router` | `/health`、`/health/plugins`、`/mcp/tools` | `health` |
| `admin_router` | `/admin` | `admin` |

探测超时：每依赖 **3 s**（`_PROBE_TIMEOUT`）。所有探测只读。

---

## `GET /health`

`HealthResponse` — 服务网格的依赖连通性。

### 探测依赖

| 名称 | 检查 |
|------|-------|
| `postgres` | 异步 DB ping（`SELECT 1`） |
| `redis` | Broker 连通性 |
| `milvus` | 实例绑定 Database 中列出集合（`eagle_text`、`eagle_visual`、…） |
| `minio` | Bucket head |
| `knowhere` | `mode=api`：HTTP GET `settings.knowhere.base_url`。`mode=parser`：进程内 `KnowhereParser` + 可写 `tmp_path` |
| `pixelrag` | 渲染库可导入；当 `embedding.visual.provider=dashscope` 时还需 `DASHSCOPE_API_KEY`（detail 含 `visual=dashscope\|pixelrag`） |
| `vlm` | Qwen-VL 可达性 |
| `celery` | 检查活跃 worker |

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

`uptime` 使用进程内单调跟踪（`_UPTIME_SINCE`）— API 重启后重置。

Milvus 探测使用 `settings.milvus.db_name`（来自 `EAGLE_RAG_PROFILE` / `plugins.default_namespace`）— 非全局默认 database。

### 摘要块

`DependencySummary`：`up` / `down` / `unknown` 计数、整体 `status`、`version`（`eagle_rag.__version__`）。

---

## `GET /health/plugins`

`PluginsHealthResponse` — 已加载插件清单、Celery 模块列表，以及近期 PluginAudit 决策（worker 一致性 + 路由遥测探测）。

```json
{
  "default_namespace": "core",
  "enabled_modules": ["eagle_rag.plugins.core_defaults"],
  "manifests": [
    {
      "namespace": "core",
      "version": "1.0.0",
      "milvus_db_name": "core",
      "provides_pipelines": ["knowhere", "pixelrag"],
      "provides_specialized_collections": [],
      "provides_mcp_tools": ["core_ingest", "core_query", "core_retrieve_text", "core_retrieve_visual"]
    }
  ],
  "celery_modules": ["eagle_rag.plugins.core_defaults", "..."],
  "recent_decisions": [
    {
      "event": "plugin_audit_decision",
      "ts": "2026-07-18T04:00:00Z",
      "category": "retrieve_plan",
      "plugin_namespace": "core",
      "reason": "plan_failed"
    }
  ],
  "audit_stats": {
    "buffer_size": 1000,
    "source": "redis",
    "enabled": true,
    "redis_enabled": true
  }
}
```

| 字段 | 含义 |
|-------|---------|
| `default_namespace` | 实例绑定域（`settings.plugins.default_namespace`） |
| `enabled_modules` | 来自 `settings.plugins.enabled` 的 Python 模块路径 |
| `manifests` | 每插件 `PluginManifest` 摘要 |
| `celery_modules` | worker 应导入以保持任务注册一致的模块 |
| `recent_decisions` | 按时间从旧到新的 PluginAudit 事件（优先 Redis 近期窗口，否则内存；受 `telemetry.plugin_audit_health_limit` 限制） |
| `audit_stats` | ring 容量，以及最近一次读取来源是 `redis` 还是 `memory` |

示例 audit category：`classify_chunk`、`route_query`、`retrieve_plan`、`scope_routing_error`、`hook_failure`。环境变量：`PLUGIN_AUDIT_ENABLED`、`PLUGIN_AUDIT_REDIS_ENABLED`（YAML：`telemetry.plugin_audit_*`）。

在更改 `EAGLE_RAG_PROFILE`、添加仓库内插件或调试命名空间 / MCP 工具暴露不一致后使用。

---

## `GET /mcp/tools`

`McpToolsResponse` — `mcp_server.py` 中 `TOOL_DEFINITIONS` 的静态工具目录（无异步 `list_tools()`）。

```json
{
  "tools": [
    {
      "name": "core_ingest",
      "description": "…",
      "parameters": { "type": "object", "properties": { … } }
    }
  ]
}
```

驱动 `McpServerDashboard` 工具表。完整语义：[MCP 工具](mcp-tools.md)。

---

## 管理路由（`/admin/*`）

### 基础设施面板

| 路径 | 响应 | 内容 |
|------|----------|---------|
| `GET /admin/celery` | `AdminCeleryResponse` | Worker、活跃任务、队列深度 |
| `GET /admin/milvus` | `AdminMilvusResponse` | 集合行数、每 KB 分区 |
| `GET /admin/minio` | `AdminMinioResponse` | Bucket、对象数 |
| `GET /admin/redis` | `AdminRedisResponse` | 内存、连接客户端 |
| `GET /admin/knowhere` | `AdminKnowhereResponse` | 远程解析器健康 |
| `GET /admin/pixelrag` | `AdminPixelragResponse` | 进程内库状态 |
| `GET /admin/vlm` | `AdminVlmResponse` | Qwen-VL 探测 |
| `GET /admin/mcp` | `AdminMcpResponse` | 近期 MCP 调用日志 |
| `GET /admin/config` | `AdminConfigOut` | 脱敏设置快照 |
| `GET /admin/probes` | `AdminProbesResponse` | 探测配置 + 最近结果 |

### 可变管理操作

| 路径 | 方法 | 用途 |
|------|--------|---------|
| `/admin/model-router` | `GET` / `PATCH` | 读/写路由模式覆盖 |
| `/admin/resource-limits` | `GET` / `PATCH` | 运维调优旋钮 |
| `/admin/actions/{action}` | `POST` | 受控维护操作 |

响应使用 `AdminActionResult`，含 `success`、`detail`。

---

## `GET /admin/logs`（SSE）

`LiveLogsTab` 的实时日志尾。

| 事件 | 载荷 |
|-------|---------|
| `log` | `{ level, message, timestamp, … }` |
| `heartbeat` | 保活 |

前端：`lib/api/sse.ts` 中 `streamAdminLogs`。

线格式与其他 SSE 端点相同（`event:` + `data:` JSON + 空行）。

---

## MCP 调用日志

`GET /admin/mcp` 含 `McpCallLogOut` 条目：

- `tool_name`、`arguments`、`result_summary`、`caller`、`latency_ms`、`timestamp`

由 MCP 工具包装器中的 `record_mcp_call` 写入。

---

## 错误处理

| 情况 | 行为 |
|-----------|-----------|
| 单探测失败 | 该依赖 `status: "down"`；`/health` 仍 HTTP 200 |
| 管理 DB 读失败 | **503** 或部分空节 |
| SSE 日志流错误 | 关闭连接；客户端重连 |

---

## 前端集成

`/health` 路由 → `HealthHeaderActions`、`ServiceGrid`、各服务面板（`CeleryDashboard`、`KnowhereDashboard`、`McpServerDashboard`、…）。

TanStack Query 键：`["health"]`、`["admin", "celery"]` 等 — 见 `useHealth.ts`。

参见 [健康模块](../frontend/health-module.md)。

---

## 相关文档

- [MCP 工具](mcp-tools.md)
- [健康模块](../frontend/health-module.md)
- [MCP 服务器（后端）](../backend/mcp-server.md)
- [安装](../getting-started/installation.md) — 依赖搭建
