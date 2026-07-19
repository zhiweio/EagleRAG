# 知识库管理

知识库（`kb_name`）是**单个已部署域**（`plugin_namespace`）内的 **KB 租户单元**。每个 KB 在实例绑定的 Milvus Database 内隔离文档、Milvus 向量（经 `kb_name` 标量过滤）、去重记录与对象存储前缀。KB 模块提供注册、生命周期（创建/删除/重建）、统计与健康监控。

**源模块：** `eagle_rag/kb/registry.py`、`eagle_rag/kb/lifecycle.py`、`eagle_rag/kb/stats.py`、`eagle_rag/kb/health.py`、`eagle_rag/api/knowledge_bases.py`、`eagle_rag/plugins/ingest_catalog.py`

---

## 1. 理论背景

### 1.1 多租户 RAG

行业无关 RAG 平台从单一**域部署**服务多个隔离知识域（finance、pharma、patent、…）。**域隔离**使用 `plugin_namespace`（Milvus Database + PG 仓库）。**KB 隔离**使用该 Database 内共享基础集合上的 `kb_name` 标量过滤 — 比每 KB 独立基础设施更经济（AWS SaaS Lens：租户隔离模式）。

### 1.2 容量规划

向量库每集合有实用实体上限。Eagle-RAG 跟踪文本/视觉实体数相对可配置上限（`kb.text_entity_limit`、`kb.visual_entity_limit`），防止无界增长。

### 1.3 无需重解析的索引重建

嵌入模型变更时，可从现有 Milvus 文本/元数据**重索引**文本向量，无需重跑 Knowhere 解析 — 对大语料显著节省成本。

---

## 2. KB 注册表

**模块：** `eagle_rag/kb/registry.py`

| 函数 | 上下文 | 用途 |
|----------|---------|---------|
| `kb_exists_sync(kb_name)` | 同步（入库） | 分发前校验 |
| `get_kb(kb_name)` | 异步（API） | 获取 KB 元数据 |
| `list_kbs()` | 异步 | 列出所有 KB |
| `create_kb(name, ...)` | 异步 | 注册新 KB |
| `get_pdf_ratio_sync(kb_name)` | 同步（router） | 每 KB PDF 探测阈值 |

每个 KB 可覆盖 `pdf_text_page_ratio` — 例如 finance KB 对混合 PDF 更倾向 Knowhere，patent KB 更多走 PixelRAG。

### API 端点

| 方法 | 路径 | 操作 |
|--------|------|--------|
| GET | `/knowledge-bases` | 带统计列出 KB |
| POST | `/knowledge-bases` | 创建 KB |
| GET | `/knowledge-bases/{name}` | KB 详情 |
| DELETE | `/knowledge-bases/{name}` | 级联删除 |
| POST | `/knowledge-bases/{name}/rebuild` | 重索引文本向量 |

---

## 3. 生命周期操作

**模块：** `eagle_rag/kb/lifecycle.py`

### 3.1 级联删除

```
1. delete_text_by_kb(kb_name)     → Milvus eagle_text
2. delete_visual_by_kb(kb_name)  → Milvus eagle_visual
3. delete MinIO prefix            → 对象存储
4. DELETE documents, dedup, keywords, images (PostgreSQL)
5. DELETE knowledge_bases row
```

Celery 任务：长时清理运行在 `knowhere_queue`。

### 3.2 文本重索引

```
1. fetch_text_nodes_by_kb(kb_name)  → 读取现有文本 + 元数据
2. delete_text_by_kb(kb_name)       → 删除旧向量
3. 用当前 embed_model 重建 TextNodes
4. upsert_text_nodes()              → 写入新向量
```

视觉重索引需完整重新入库（render + embed 无法仅从 Milvus 标量还原）。

### 3.3 `collections_used` 与专用扇出

入库成功后，每文档记录哪些 Milvus 集合收到向量（`collections_used`）。KB 级目录对这些集合取并集（[ADR-006](../architecture/adr/006-ingest-query-routing-contract.md)）。

查询时，当以下情况时 `RetrieverOrchestrator` 可扇出到专用集合（如 `eagle_text_biomed`）：

- 域 `QueryRouteClassifier` 将其加入 plan，或
- 范围感知目录并集在 scoped KB/文档/标签中包含它们。

Core 默认路由（G4）若无此类 plan 永不自动查询专用集合。参见 [插件架构](../architecture/plugin-architecture.md)。

---

## 4. 统计

**模块：** `eagle_rag/kb/stats.py`

每 KB 聚合：

| 指标 | 来源 |
|--------|--------|
| `document_count` | PostgreSQL `documents` |
| `text_entity_count` | Milvus `count_text(kb_name)` |
| `visual_entity_count` | Milvus `count_visual(kb_name)` |
| `ready_count` / `pending_count` | PostgreSQL 状态过滤 |
| `format_distribution` | 扩展名直方图 |

与 `settings.kb` 中上限对比：

```yaml
kb:
  text_entity_limit: 500000
  visual_entity_limit: 200000
```

---

## 5. 健康监控

**模块：** `eagle_rag/kb/health.py`

每 KB 健康状态：

| 检查 | 健康条件 |
|-------|-------------|
| Milvus 文本可达 | `count_text()` 成功 |
| Milvus 视觉可达 | `count_visual()` 成功 |
| 实体比例 | count < 上限 90% |
| 待定文档 | 无文档长时间卡在 `pending` |

展示在管理面板与 `GET /knowledge-bases/{name}`。

---

## 6. Milvus 过滤表达式

所有 KB 操作使用租户标量：

```
kb_name == "finance"
```

删除操作：

```python
client.delete(collection, filter='kb_name == "finance"')
```

计数操作：

```python
client.query(collection, filter='kb_name == "finance"', output_fields=["count(*)"])
```

---

## 7. LlamaIndex 集成

重索引从 Milvus 拉取数据重建 `TextNode`：

```python
node = TextNode(text=row["text"], id_=row["id"])
node.metadata = row["metadata"]  # preserves path, connect_to, etc.
index.insert_nodes([node])         # re-embeds with current model
```

保留元数据确保图扩展（`connect_to`）与父文档（`path`）检索在重索引后仍有效。

---

## 8. 设计张力与调优

| 张力 | 操作 | 风险 | 缓解 |
| --- | --- | --- | --- |
| **清除顺序** | Milvus delete expr 再 Postgres | 部分失败 → 孤儿向量或缺失注册 | 经 API 跑清除；事后核对计数 |
| **重建风暴** | 重排队全部文档 | 打满 `knowhere_queue` / `pixelrag_queue` | 限速重建；临时扩 worker |
| **实体上限警告** | `kb.text_entity_limit` / `visual_entity_limit` | 仅软阈值 — 入库继续 | 硬治理需外部配额 |
| **每 KB PDF 比例** | `get_pdf_ratio_sync` | 全局默认不适合扫描型 KB | 在注册元数据设 per-KB ratio |
| **不可变 kb_name** | 注册表约束 | 显示重命名需新 KB + 迁移 | 租户 ID 规划为稳定 slug |
| **统计滞后** | `kb/stats.py` 数 Milvus + SQL | 清除后立即刷新端点可能陈旧 | 生命周期操作后刷新统计 |

---

## 9. 配置与调优

```yaml
kb_name: default              # fallback tenant

kb:
  text_entity_limit: 500000
  visual_entity_limit: 200000
```

每 KB PDF 探测覆盖存在 `knowledge_bases.pdf_text_page_ratio`。

---

## 10. 测试

| 测试文件 | 覆盖 |
|-----------|----------|
| `tests/test_api_kb_attachments_notifications_users.py` | KB CRUD |
| `tests/test_api_admin_health.py` | 管理中 KB 健康 |

---

## 11. 入库校验门

任何入库分发前，`runner.ingest()` 校验 KB 存在：

```python
from eagle_rag.kb.registry import kb_exists_sync
if not kb_exists_sync(kb):
    raise ValueError(f"知识库未注册: {kb}")
```

MCP `core_ingest` 与 `POST /ingest` 均传播此错误。防止 Milvus 出现无注册表行的孤儿向量。

---

## 12. 多 KB 查询模式

单次查询可经 `scope_filter.kb_names` 跨多个 KB：

```json
{"scope_filter": {"kb_names": ["finance", "pharma"], "tags": ["2025"]}}
```

Milvus 表达式：

```
(kb_name in ["finance", "pharma"] or document_id in [tag-resolved ids])
```

默认单 KB 查询使用 `QueryRequest.kb_name` → `kb_name == "{value}"`。

---

## 13. 容量告警

当 `text_entity_count > 0.9 * text_entity_limit` 时，KB 健康返回 `warning`。100% 时应阻止入库（API 层经统计检查在上传前强制执行）。`eagle_visual` 实体计数对视觉上限同样模式。

---

## 14. 参考文献

- Milvus 按过滤删除：[milvus.io/docs/delete_entities.md](https://milvus.io/docs/delete_entities.md)
- Milvus 计数：[milvus.io/docs/get_collection_stats.md](https://milvus.io/docs/get_collection_stats.md)
- Gao 等，*RAG Survey*，[arXiv:2312.10997](https://arxiv.org/abs/2312.10997)
- Eagle-RAG 多租户：[multi-tenancy](../architecture/multi-tenancy.md)
