# 任务 API

Celery 作业审计记录在 **`/tasks`** 下暴露。每次摄入派发创建 `task_audit` 行，经流水线阶段跟踪至 `success` 或 `failed`。

实现：`eagle_rag/api/ingest.py`（任务路由与摄入路由共享标签）。

---

## `GET /tasks`

带过滤与分页的任务审计列表。

### 查询参数

| 参数 | 类型 | 说明 |
|-------|------|-------------|
| `pipeline` | `string` | 过滤：`router`、`knowhere`、`pixelrag` 或复合 |
| `status` | `string` | 后端原始状态（`pending`、`rendering`、`success` 等） |
| `q` | `string` | 模糊匹配 `job_id` 或 `document_id` |
| `kb_name` | `string` | 多租户过滤 |
| `limit` | `int` | 1–500，默认 50 |
| `offset` | `int` | ≥ 0 |

### 响应 — `TaskListResponse`

```json
{
  "items": [
    {
      "job_id": "abc-123",
      "document_id": "doc_xyz",
      "name": "report.pdf",
      "source_uri": "kb/finance/report.pdf",
      "pipeline": "knowhere",
      "status": "embedding",
      "status_phase": "running",
      "progress": 65,
      "current": 13,
      "total": 20,
      "error": null,
      "logs": [],
      "created_at": "2025-07-05T01:00:00Z",
      "updated_at": "2025-07-05T01:02:00Z",
      "kb_name": "finance"
    }
  ],
  "limit": 50,
  "offset": 0,
  "error": null
}
```

### `status` 与 `status_phase`

| `status`（原始） | `status_phase`（归一化） |
|----------------|----------------------------|
| `pending`、`queued` | `pending` |
| `rendering`、`embedding`、`indexing`、`processing`、`parsing`、`retrying` | `running` |
| `success`、`done`、`ready` | `success` |
| `failed`、`error` | `failed` |

前端 `status.ts` 将 `status_phase` 映射为胶囊颜色 —— 新增后端状态时须在 `_STATUS_PHASE_MAP`（`schemas/ingest.py`）中维护映射。

### 降级模式

数据库失败 → HTTP **200**，`items: []` 且 `error: "database unavailable"`。UI 应展示提示。

---

## `GET /tasks/{job_id}`

单个 `TaskAuditOut`。**404** 未找到。**503** 数据库不可用。

---

## `GET /tasks/{job_id}/stream`（SSE）

单作业实时进度订阅。

### 事件

| 事件 | 载荷 |
|-------|---------|
| `progress` | 完整审计字典（与 `TaskAuditOut` 源行同形） |
| `timeout` | `{ job_id, reason: "no change timeout", seconds }` |

### 行为

- 轮询间隔：**1.5 s**（`_SSE_POLL_INTERVAL`）
- 状态 ∉ `{success, failed}` 时每次轮询发出 `progress`
- **终端：** `success` 或 `failed` 的 progress 事件后关闭流
- **超时：** `updated_at` **300 s** 无变化 → `timeout` 事件后关闭

### 线格式示例

```
event: progress\r\n
data: {"job_id":"…","status":"embedding","progress":40,…}\r\n
\r\n
```

无 `token` 或 `step` 事件 —— 任务 SSE 仅为审计快照。

### 前端消费者

`frontend/lib/api/sse.ts` → `streamTaskProgress(jobId, onEvent)`，使用生成的 `streamTaskTasksJobIdStreamGet`。

---

## `GET /tasks/{job_id}/logs`

返回 `TaskLogsResponse`：

```json
{ "job_id": "abc-123", "logs": [ { "ts": "…", "level": "info", "message": "…" } ] }
```

`TaskLogEntry` 允许额外 JSONB 键（`ConfigDict(extra="allow")`）。

---

## `POST /tasks/{job_id}/retry`

将失败任务重新派发到原 Celery 队列。

### pipeline → 队列映射

| `pipeline` 键 | Celery 任务 | 队列 |
|----------------|-------------|-------|
| `router` | `eagle_rag.ingest.router.ingest_router` | `router_queue` |
| `knowhere` | `eagle_rag.tasks.knowhere_parse` | `knowhere_queue` |
| `pixelrag` | `eagle_rag.tasks.pixelrag_build` | `pixelrag_queue` |

### 恢复逻辑

1. 加载审计 + 文档注册表行
2. 从 `documents` 表恢复 `object_key` / `source_uri` / `source_type_hint`
3. `local_path` 故意为 **null**（临时文件已不存在）
4. 在 `send_task` **之前**将审计重置为 `PENDING`（避免竞态）

### 响应 — `TaskRetryResponse`

```json
{ "job_id": "abc-123", "status": "pending", "retried": true }
```

| HTTP | 条件 |
|------|-----------|
| `200` | 已派发 |
| `404` | 未知作业 |
| `502` | `send_task` 失败 |
| `503` | 数据库不可用 |

**幂等性：** 每次重试在同一 `job_id` 行上新建执行尝试（状态重置）。不宜频繁触发 —— 若先前部分索引已存在，可能重复写入 Milvus。

---

## `DELETE /tasks/{job_id}`

仅删除审计记录（**不**删除已索引文档）。缺失 **404**。

---

## 多租户

每条审计行含 `kb_name`；列表用 `?kb_name=finance` 过滤。重试在 Celery kwargs 中传递 `kb_name`。

---

## 相关文档

- [摄入](ingest.md) —— 派发入口
- [文档](documents.md) —— `document_id` 生命周期
- [任务队列（后端）](../backend/task-queue.md) —— worker 配置
