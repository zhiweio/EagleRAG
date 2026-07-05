# 知识库管理

知识库（`kb_name`）是 Eagle-RAG 的多租户单元。每个 KB 隔离文档、Milvus 向量、去重记录与对象存储前缀。KB 模块提供 registry、生命周期（创建/删除/重建）、统计与健康监控。

**源码模块：** `eagle_rag/kb/registry.py`、`eagle_rag/kb/lifecycle.py`、`eagle_rag/kb/stats.py`、`eagle_rag/kb/health.py`、`eagle_rag/api/knowledge_bases.py`

---

## 1. 理论背景

### 1.1 多租户 RAG

行业无关 RAG 平台从单一部署服务多个隔离知识域（finance、pharma、patent…）。经租户判别字段（`kb_name`）在各表与 Milvus 标量过滤上**逻辑隔离**，比每租户独立基础设施更经济（AWS SaaS Lens：租户隔离模式）。

### 1.2 容量规划

向量库每 collection 有实际实体上限。Eagle-RAG 跟踪文本/视觉实体数相对可配置上限（`kb.text_entity_limit`, `kb.visual_entity_limit`），防止无界增长。

### 1.3 不重新解析的索引重建

嵌入模型变更时，可从现有 Milvus 文本/元数据**重建索引**文本向量，无需重跑 Knowhere 解析 —— 对大语料显著省成本。

---

## 2. KB registry

**模块：** `eagle_rag/kb/registry.py`

| 函数 | 上下文 | 用途 |
|----------|---------|---------|
| `kb_exists_sync(kb_name)` | 同步（入库） | 派发前校验 |
| `get_kb(kb_name)` | 异步（API） | 取 KB 元数据 |
| `list_kbs()` | 异步 | 列出所有 KB |
| `create_kb(name, ...)` | 异步 | 注册新 KB |
| `get_pdf_ratio_sync(kb_name)` | 同步（router） | 每 KB PDF 探测阈值 |

每个 KB 可覆盖 `pdf_text_page_ratio` —— 例如 finance KB 混合 PDF 偏 Knowhere，patent KB 更多路由到 PixelRAG。

### API 端点

| 方法 | 路径 | 动作 |
|--------|------|--------|
| GET | `/knowledge-bases` | 列出 KB 及统计 |
| POST | `/knowledge-bases` | 创建 KB |
| GET | `/knowledge-bases/{name}` | KB 详情 |
| DELETE | `/knowledge-bases/{name}` | 级联删除 |
| POST | `/knowledge-bases/{name}/rebuild` | 重建文本向量 |

---

## 3. 生命周期操作

**模块：** `eagle_rag/kb/lifecycle.py`

### 3.1 级联删除

```
1. delete_text_by_kb(kb_name)     → Milvus eagle_text
2. delete_visual_by_kb(kb_name)  → Milvus eagle_visual
3. delete MinIO prefix            → object storage
4. DELETE documents, dedup, keywords, images (PostgreSQL)
5. DELETE knowledge_bases row
```

Celery 任务：长耗时清理跑在 `knowhere_queue`。

### 3.2 文本重建索引

```
1. fetch_text_nodes_by_kb(kb_name)  → read existing text + metadata
2. delete_text_by_kb(kb_name)       → remove old vectors
3. Rebuild TextNodes with current embed_model
4. upsert_text_nodes()              → write fresh vectors
```

视觉重建索引需完整重新入库（仅凭 Milvus 标量无法逆推 render + embed）。

---

## 4. 统计

**模块：** `eagle_rag/kb/stats.py`

按 KB 聚合：

| 指标 | 来源 |
|--------|--------|
| `document_count` | PostgreSQL `documents` |
| `text_entity_count` | Milvus `count_text(kb_name)` |
| `visual_entity_count` | Milvus `count_visual(kb_name)` |
| `ready_count` / `pending_count` | PostgreSQL 状态过滤 |
| `format_distribution` | 扩展名直方图 |

与 `settings.kb` 上限对比：

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
| 待处理文档 | 无文档长期卡在 `pending` 超阈值 |

暴露在 admin 面板与 `GET /knowledge-bases/{name}`。

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

重建索引从 Milvus 取数重建 `TextNode`：

```python
node = TextNode(text=row["text"], id_=row["id"])
node.metadata = row["metadata"]  # preserves path, connect_to, etc.
index.insert_nodes([node])         # re-embeds with current model
```

保留元数据保证图扩展（`connect_to`）与父文档（`path`）检索在重建后仍可用。

---

## 8. 设计张力与调参

| 张力 | 操作 | 风险 | 缓解 |
| --- | --- | --- | --- |
| **Purge 顺序** | Milvus delete expr 后 Postgres | 部分失败 → 孤儿向量或缺失 registry | 经 API purge；事后核对计数 |
| **Rebuild 风暴** | 全量文档重排队 | `knowhere_queue` / `pixelrag_queue` 尖峰 | 限速 rebuild；临时扩 worker |
| **实体上限告警** | `kb.text_entity_limit` / `visual_entity_limit` | 仅软阈值 —— 入库继续 | 硬治理需外部配额 |
| **每 KB PDF 比例** | `get_pdf_ratio_sync` | 扫描型 KB 用全局默认易错 | 在 registry metadata 设 per-KB ratio |
| **kb_name 不可变** | Registry 约束 | 显示名变更需新 KB + 迁移 | 租户 ID 规划为稳定 slug |
| **统计滞后** | `kb/stats.py` 数 Milvus + SQL | purge 后缓存可能 stale | 生命周期操作后刷新 stats 端点 |

---

## 9. 配置与调优

```yaml
kb_name: default              # fallback tenant

kb:
  text_entity_limit: 500000
  visual_entity_limit: 200000
```

每 KB PDF 探测覆盖存于 `knowledge_bases.pdf_text_page_ratio`。

---

## 10. 测试

| 测试文件 | 覆盖 |
|-----------|----------|
| `tests/test_api_kb_attachments_notifications_users.py` | KB CRUD |
| `tests/test_api_admin_health.py` | admin 中 KB 健康 |

---

## 11. 入库校验门

任何入库派发前，`runner.ingest()` 校验 KB 存在：

```python
from eagle_rag.kb.registry import kb_exists_sync
if not kb_exists_sync(kb):
    raise ValueError(f"知识库未注册: {kb}")
```

MCP `ingest` 工具与 `POST /ingest` 均传播此错误，防止 Milvus 出现无 registry 行的孤儿向量。

---

## 12. 多 KB 查询模式

单次查询可经 `scope_filter.kb_names` 跨多 KB：

```json
{"scope_filter": {"kb_names": ["finance", "pharma"], "tags": ["2025"]}}
```

Milvus 表达式：

```
(kb_name in ["finance", "pharma"] or document_id in [tag-resolved ids])
```

默认单 KB 查询用 `QueryRequest.kb_name` → `kb_name == "{value}"`。

---

## 13. 容量告警

当 `text_entity_count > 0.9 * text_entity_limit`，KB 健康返回 `warning`。100% 时应阻止入库（API 层上传前经 stats 检查）。视觉上限对 `eagle_visual` 实体数同样适用。

---

## 14. 参考文献

- Milvus delete by filter: [milvus.io/docs/delete_entities.md](https://milvus.io/docs/delete_entities.md)
- Milvus count: [milvus.io/docs/get_collection_stats.md](https://milvus.io/docs/get_collection_stats.md)
- Gao et al., *RAG Survey*, [arXiv:2312.10997](https://arxiv.org/abs/2312.10997)
- Multi-tenancy in Eagle-RAG: [multi-tenancy](../architecture/multi-tenancy.md)
