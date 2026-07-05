# 知识库 API

多租户命名空间在 **`/knowledge_bases`** 下管理。每个 `kb_name` 隔离文档、Milvus 标量过滤、Celery kwargs 与控制台主题元数据。

实现：`eagle_rag/api/knowledge_bases.py`，schema：`eagle_rag/api/schemas/knowledge_bases.py`。

---

## 命名规则

`kb_name` 须匹配 `registry.KB_NAME_PATTERN`：

```
^[a-z][a-z0-9_]*$
```

仅小写字母、数字、下划线。违反时 **422**。

---

## `GET /knowledge_bases`

列出已注册 KB 及实时统计。

| 查询 | 默认 | 说明 |
|-------|---------|-------------|
| `query` | — | 搜索显示名 / kb_name |
| `sort` | `recent` | `recent \| name \| size` |
| `limit` | 50 | 1–200 |
| `offset` | 0 | 分页 |

### `KBItem` 字段

| 字段 | 说明 |
|-------|-------------|
| `kb_name` | 标识符 |
| `display_name` | UI 标签 |
| `description` | 可选简介 |
| `theme` | 颜色 token（`blue`、`violet` 等） |
| `icon` | Lucide 图标键 |
| `pdf_text_page_ratio` | PDF 形态探测阈值（0–1） |
| `documents` | 就绪文档数 |
| `graph_nodes` | 文本集合实体数 |
| `visual_slices` | 视觉 tile 数 |
| `collections` | Milvus 集合名 |
| `active_ingestions` | 进行中任务数 |
| `updated_at` | ISO 时间戳 |

---

## `GET /knowledge_bases/overview`

跨 KB 聚合 `KBOverviewResponse` —— `/kb` 落地页仪表盘 KPI。

---

## `POST /knowledge_bases`

创建命名空间。请求体 — `KBCreate`：

```json
{
  "kb_name": "pharma",
  "display_name": "Pharma R&D",
  "description": "Clinical and regulatory corpus",
  "theme": "emerald",
  "icon": "flask",
  "pdf_text_page_ratio": 0.25
}
```

| HTTP | 条件 |
|------|-----------|
| `201` | 已创建 |
| `409` | `kb_name already exists` |
| `422` | 无效名称或校验错误 |
| `503` | 注册表 / DB 失败 |

---

## `GET /knowledge_bases/{kb_name}`

`KBDetailOut` = `KBItem` + `status` + `kpi`：

```json
{
  "status": "healthy",
  "kpi": {
    "documents": 120,
    "graph_nodes": 45000,
    "visual_slices": 8000,
    "queries_7d": 340
  }
}
```

`status` 来自 `health.compute_kb_status`（`healthy`、`degraded` 等）。KB 缺失时 **404**。

---

## 分析子路由

| 路径 | 响应 | 用途 |
|------|----------|---------|
| `GET …/format-distribution` | `KBFormatDistributionResponse` | 文件类型分布 |
| `GET …/ingestion-volume?days=7` | `KBIngestionVolumeResponse` | 摄入时间序列（1–90 天） |
| `GET …/collections` | `KBCollectionsResponse` | Milvus 集合统计 |
| `GET …/facets` | `KBFacetsResponse` | `source_type`、`year`、pipeline 分面 |

均需 KB 存在 —— 否则 **404**。

---

## `PATCH /knowledge_bases/{kb_name}`

通过 `KBUpdate` 部分更新（display_name、description、theme、icon、pdf_text_page_ratio）。缺失时 **404**。

---

## `DELETE /knowledge_bases/{kb_name}`

`KBDeleteResponse`：

```json
{
  "kb_name": "pharma",
  "deleted": {
    "documents": 120,
    "milvus_text": 45000,
    "milvus_visual": 8000,
    "minio_objects": 240
  }
}
```

调用 `lifecycle.delete_kb_namespace` —— 破坏性、异步较重。KB 未找到 **404**。

!!! warning "警告"
    清理会删除该命名空间的注册表行、Milvus 实体与存储对象。删除生产 KB 前请备份。

---

## `POST /knowledge_bases/{kb_name}/rebuild`

触发全量重建索引任务。`RebuildResponse`：

```json
{ "job_id": "rebuild-uuid" }
```

通过 `/tasks` 跟踪。KB 缺失 **404**。

---

## 多租户集成

| 消费者 | `kb_name` 传递方式 |
|----------|------------------------|
| `POST /ingest` | 表单字段 |
| `POST /query` | 请求体字段或 `scope_filter.kb_names[]` |
| `GET /documents` | 查询过滤 |
| `GET /tasks` | 查询过滤 |
| MCP 工具 | 可选参数，默认 `settings.kb_name` |
| 前端 KB 选择器 | 摄入页 `useKBStore`；问答范围抽屉 |

默认 KB：`default`（`KB_NAME` 环境变量）。

---

## 前端集成

| 路由 | 组件 |
|-------|------------|
| `/kb` | `KBManagementClient`、占位卡片、概览图表 |
| `/kb/[kbName]` | `KBDetailClient`、Milvus 卡片、清理/重建弹窗 |

见 [知识库模块](../frontend/kb-module.md)。

---

## 相关文档

- [多租户](../architecture/multi-tenancy.md)
- [摄入](ingest.md) —— 需已注册 KB
- [数据库](../backend/database.md) —— `knowledge_bases` 表
