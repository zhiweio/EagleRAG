# 数据库

Eagle-RAG 使用 **PostgreSQL** 存储元数据、审计轨迹、会话与运营数据。Schema 由 **Alembic** 迁移管理，表定义基于 **SQLModel**。向量数据在 Milvus — PostgreSQL 是文档生命周期与用户态数据的权威来源。

所有域表通过 **repositories**（`eagle_rag/db/repositories/`）访问，每次读写注入 `plugin_namespace`。参见[插件架构](../architecture/plugin-architecture.md)。

**源模块：** `eagle_rag/db/models/`、`eagle_rag/db/repositories/`、`eagle_rag/db/namespace.py`、`alembic/versions/`

---

## 1. 理论背景

### 1.1 RAG 中的双存储架构

现代 RAG 系统按访问模式拆分存储（Gao 等，arXiv:2312.10997）：

| 存储 | 数据 | 查询模式 |
|-------|------|--------------|
| **向量 DB**（Milvus） | 嵌入 + 分块文本 | ANN 相似度搜索 |
| **关系型 DB**（PostgreSQL） | 元数据、审计、会话 | CRUD、连接、事务 |

该分离支持独立扩展：Milvus 面向十亿级向量搜索，PostgreSQL 面向事务一致性。

### 1.2 通过复合键实现多租户

Eagle-RAG 在两个轴上隔离（[多租户](../architecture/multi-tenancy.md)）：

| 轴 | 键 | 模式 |
|------|-----|---------|
| **域** | `plugin_namespace` | 每条 PG 行的仓储过滤；部署时固定 |
| **知识库** | `kb_name` | 单个 Milvus Database 内的标量过滤 |

去重使用 `(sha256, kb_name, plugin_namespace)` 作为复合主键 — 相同文件内容可存在于多个知识库或域而不冲突。`knowledge_bases` 主键为 `(kb_name, plugin_namespace)`。

### 1.3 任务审计的事件溯源

`task_audit` 表作为摄取作业的**追加友好审计日志** — 记录状态转换、进度与错误信息，无需查询 Celery 内部实现。

---

## 2. 实体关系概览

```mermaid
erDiagram
    knowledge_bases ||--o{ documents : contains
    documents ||--o{ document_keywords : tagged
    documents ||--o| dedup : "sha256+kb"
    documents ||--o{ task_audit : tracked
    documents ||--o{ images : visual
    sessions ||--o{ session_messages : has
    users ||--o{ sessions : owns
    users ||--o{ notifications : receives
```

---

## 3. 核心表

### 3.1 `knowledge_bases`

| 列 | 类型 | 说明 |
|--------|------|-------|
| `kb_name` | VARCHAR | 租户标识（`finance`、`pharma` 等） |
| `plugin_namespace` | TEXT | 域绑定（PK 组成部分） |
| `display_name` | VARCHAR | UI 标签 |
| `description` | TEXT | 可选 |
| `pdf_text_page_ratio` | FLOAT | 每 KB 的 PDF 探测覆盖 |
| `collections_used` | JSONB | 摄取写入的 Milvus collection 的 KB 级并集 |
| `created_at` | TIMESTAMP | |

**PK：** `(kb_name, plugin_namespace)`

### 3.2 `documents`

| 列 | 类型 | 说明 |
|--------|------|-------|
| `document_id` | UUID PK | |
| `name` | VARCHAR | 文件名 |
| `source_type` | VARCHAR | policy/financial/… |
| `pipeline` | VARCHAR | knowhere/pixelrag/pending |
| `kb_name` | VARCHAR | 租户键 |
| `plugin_namespace` | TEXT | 域绑定（仓储注入） |
| `source_uri` | VARCHAR | 原始路径/URL |
| `sha256` | VARCHAR | 内容哈希 |
| `status` | VARCHAR | pending/indexing/ready |
| `chunk_count` | INT | 已索引节点数 |
| `extra` | JSONB | doc_nav 树、`collections_used` catalog 等 |
| `created_at` | TIMESTAMP | |

### 3.3 `document_dedup`

| 列 | 类型 | 说明 |
|--------|------|-------|
| `sha256` | VARCHAR | 内容哈希 |
| `kb_name` | VARCHAR | 租户键 |
| `plugin_namespace` | TEXT | 域绑定 |
| `document_id` | UUID FK | 指向已有文档 |
| PK | `(sha256, kb_name, plugin_namespace)` | 复合 |

仅在解析成功后注册 — 失败摄取不阻塞重新上传。仓储：`eagle_rag/db/repositories/dedup.py`。

### 3.4 `document_keywords`

用于 scope 过滤的标签 catalog：

| 列 | 类型 | 说明 |
|--------|------|-------|
| `document_id` | UUID | |
| `kb_name` | VARCHAR | |
| `plugin_namespace` | TEXT | 域绑定 |
| `keyword` | VARCHAR | 来自 Knowhere 分块关键词 |
| `count` | INT | 出现次数 |

由 `GET /tags` 与查询时的 `resolve_tags_to_document_ids()` 查询。

### 3.5 `task_audit`

| 列 | 类型 | 说明 |
|--------|------|-------|
| `job_id` | UUID PK | Celery 任务 ID |
| `document_id` | UUID | |
| `pipeline` | VARCHAR | router/knowhere/pixelrag |
| `kb_name` | VARCHAR | |
| `plugin_namespace` | TEXT | 域绑定 |
| `state` | VARCHAR | PENDING/RENDERING/…/SUCCESS/FAILED |
| `progress` | INT | 0-100 |
| `current` / `total` | INT | 进度计数 |
| `error` | TEXT | 最后错误信息 |
| `log` | JSONB | 仅追加日志条目 |
| `name` | VARCHAR | 文件名 |
| `source_uri` | VARCHAR | |

### 3.6 `sessions` / `session_messages`

聊天会话持久化：

| 表 | 关键字段 |
|-------|-----------|
| `sessions` | session_id、user_id、title、scope_filter（JSONB）、kb_name、plugin_namespace |
| `session_messages` | message_id、session_id、role、content、sources（JSONB）、steps（JSONB）、plugin_namespace |

`scope_filter` 持久化，使后续查询继承 KB/文档/标签 scope。

### 3.7 `images`

视觉瓦片元数据（Milvus 向量的补充）：

| 列 | 类型 | 说明 |
|--------|------|-------|
| `image_id` | VARCHAR PK | |
| `document_id` | UUID | |
| `object_key` | VARCHAR | MinIO 路径 |
| `kb_name` | VARCHAR | |
| `plugin_namespace` | TEXT | 域绑定 |
| `page`, `position` | INT/VARCHAR | 瓦片位置 |
| `width`, `height` | INT | 尺寸 |

### 3.8 `attachments`

会话范围的临时上传：

| 列 | 类型 | 说明 |
|--------|------|-------|
| `attachment_id` | UUID PK | |
| `session_id` | UUID | |
| `filename` | VARCHAR | |
| `object_key` | VARCHAR | MinIO |
| `expires_at` | TIMESTAMP | TTL 来自 `attachments.ttl_hours` |

### 3.9 运营表

| 表 | 用途 |
|-------|---------|
| `notifications` | 用户通知（摄取完成、错误） |
| `mcp_call_log` | MCP 工具调用审计（namespace 范围） |
| `metric_samples` | 队列深度时间序列 |
| `system_settings` | 运行时可配置覆盖 |

---

## 4. 迁移工作流

```bash
# 模型变更后生成迁移
alembic revision --autogenerate -m "describe change"

# 应用
task db:migrate
# 或：alembic upgrade head
```

**约定：**

- 模型在 `eagle_rag/db/models/` — 每域一个文件。
- 仓储在 `eagle_rag/db/repositories/` — 通过 `instance_namespace()` 强制 `plugin_namespace`。
- 迁移 `0007_plugin_namespace` 添加 `plugin_namespace` 列与复合 PK。
- `alembic/env.py` 规范化 DSN：`postgresql+asyncpg://` → `postgresql+psycopg2://`（用于迁移）。
- 仓储模块中无 DDL — 所有 schema 变更经 Alembic。

---

## 5. 与 Milvus 的关系

PostgreSQL 持有指针；Milvus 在**按域 Database**（`MilvusClientPool`，见 [vector-stores](vector-stores.md)）中持有可搜索向量：

| PostgreSQL | Milvus 过滤 |
|-----------|--------------|
| `documents.document_id` | `document_id == "..."` |
| `documents.kb_name` | `kb_name == "..."` |
| `documents.source_type` | `source_type == "..."` |
| `document_keywords.keyword` | 解析为 `document_id in [...]` |
| `documents.extra.collections_used` | 查询时 scope 感知的专用 collection 计划 |

摄取成功后，`collections_used` 在文档级（`documents.extra`）与 KB 级（`knowledge_bases.collections_used`）更新，经 `eagle_rag/db/repositories/catalog.py`。失败或部分摄取不更新 catalog。

KB 删除（`kb/lifecycle.py`）级联：PostgreSQL 行（namespace 范围）→ Milvus `delete_*_by_kb()` → MinIO 前缀清理。

---

## 6. LlamaIndex 集成

PostgreSQL 存储文档 registry 元数据，与 LlamaIndex `TextNode.metadata` 镜像：

| PG 字段 | TextNode metadata |
|----------|------------------|
| `document_id` | `metadata.document_id` |
| `source_type` | `metadata.source_type` |
| `kb_name` | `metadata.kb_name` |
| `extra.doc_nav` | 经 structure API 提供（不在 Milvus 中） |

LlamaIndex docstore 可在本地缓存节点，但权威元数据在 Milvus 动态字段 + PostgreSQL registry。

---

## 7. 设计张力与调优

| 张力 | Schema / 仓储 | 后果 | 实践 |
| --- | --- | --- | --- |
| **Namespace 不匹配** | `eagle_rag/db/namespace.py` 中的 `resolve_namespace()` | 请求 `plugin_namespace` ≠ `default_namespace` → **403** | 仅在测试中使用 `plugins.allow_namespace_override` |
| **无 DB 约束的 JSONB scope** | `sessions.scope_filter` | 删除后文档 ID 过期 — 查询返回空，不报错 | KB 清理后客户端刷新 scope |
| **双驱动一致性** | asyncpg（API）vs psycopg2（worker） | 同一条记录从两路径更新 — 与 Milvus 无分布式事务 | 将 Postgres 视为生命周期权威；Milvus 最终一致 |
| **CASCADE vs 向量清理** | FK `document_keywords` ON DELETE CASCADE | SQL 干净；Milvus 向量需 lifecycle 中显式 `delete_*` | 始终使用 KB 清理 API，勿直接 SQL 删除 |
| **Alembic vs 运行时** | `eagle_rag/db/models/` 中的模型 | 部署前未跑迁移则漂移 | 发布流水线中执行 `task db:migrate` |
| **任务审计增长** | `task_state` 仅追加日志 | 大 JSONB 日志数组拖慢管理 UI | 定期归档旧审计 |
| **消息历史无界** | 每会话 `messages` | 长聊天增加会话恢复负载 | 客户端分页；未来保留策略 |

---

## 8. 配置与调优

```yaml
postgres:
  dsn: postgresql://eagle:eagle@localhost:5432/eagle_rag
```

**环境变量：**

```
POSTGRES_DSN=postgresql://user:pass@host:5432/eagle_rag
```

异步路由内部使用 `postgresql+asyncpg://` 变体。

---

## 9. 测试

| 测试文件 | 覆盖 |
|-----------|----------|
| `tests/test_api_query_sessions_documents_tasks.py` | 会话 CRUD |
| `tests/test_api_kb_attachments_notifications_users.py` | KB registry、附件 |
| `tests/test_api_admin_health.py` | 健康检查中的 DB 连通性 |
| `tests/plugins/test_namespace_isolation.py` | `plugin_namespace` 仓储隔离 |

---

## 10. 参考文献

- SQLModel：[sqlmodel.tiangolo.com](https://sqlmodel.tiangolo.com/)
- Alembic：[alembic.sqlalchemy.org](https://alembic.sqlalchemy.org/)
- Gao 等，*RAG Survey*，[arXiv:2312.10997](https://arxiv.org/abs/2312.10997)
- 多租户数据架构：[docs.aws.amazon.com/wellarchitected/latest/saas-lens](https://docs.aws.amazon.com/wellarchitected/latest/saas-lens/saas-lens.html)
