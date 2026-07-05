# 数据库

Eagle-RAG 使用 **PostgreSQL** 存储元数据、审计轨迹、会话与运维数据。Schema 由 **Alembic** 迁移管理，表定义基于 **SQLModel**。向量数据在 Milvus —— PostgreSQL 是文档生命周期与用户可见状态的系统记录。

**源码模块：** `eagle_rag/db/models/`、`alembic/versions/`

---

## 1. 理论背景

### 1.1 RAG 中的双存储架构

现代 RAG 按访问模式拆分存储（Gao et al., arXiv:2312.10997）：

| 存储 | 数据 | 查询模式 |
|-------|------|--------------|
| **向量库**（Milvus） | 嵌入 + chunk 文本 | 近似最近邻相似度搜索 |
| **关系库**（PostgreSQL） | 元数据、审计、会话 | CRUD、连接、事务 |

分离便于独立扩展：Milvus 做十亿级向量搜索，PostgreSQL 做事务一致性。

### 1.2 复合键多租户

去重使用 `(sha256, kb_name)` 复合主键 —— 相同文件内容可在多知识库共存无冲突。遵循**共享库、共享 schema、租户判别字段**模式。

### 1.3 任务审计的事件溯源

`task_audit` 表作为入库任务的**追加友好审计日志** —— 记录状态迁移、进度与错误信息，便于可观测性而无需查 Celery 内部。

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
| `name` | VARCHAR PK | 租户标识（`finance`, `pharma`, …） |
| `display_name` | VARCHAR | UI 标签 |
| `description` | TEXT | 可选 |
| `pdf_text_page_ratio` | FLOAT | 每 KB PDF 探测覆盖 |
| `created_at` | TIMESTAMP | |

### 3.2 `documents`

| 列 | 类型 | 说明 |
|--------|------|-------|
| `document_id` | UUID PK | |
| `name` | VARCHAR | 文件名 |
| `source_type` | VARCHAR | policy/financial/… |
| `pipeline` | VARCHAR | knowhere/pixelrag/pending |
| `kb_name` | VARCHAR FK | 租户键 |
| `source_uri` | VARCHAR | 原始 path/URL |
| `sha256` | VARCHAR | 内容哈希 |
| `status` | VARCHAR | pending/indexing/ready |
| `chunk_count` | INT | 已索引节点数 |
| `extra` | JSONB | doc_nav 树等 |
| `created_at` | TIMESTAMP | |

### 3.3 `dedup`

| 列 | 类型 | 说明 |
|--------|------|-------|
| `sha256` | VARCHAR | 内容哈希 |
| `kb_name` | VARCHAR | 租户键 |
| `document_id` | UUID FK | 指向已有文档 |
| PK | `(sha256, kb_name)` | 复合 |

仅在解析成功后注册 —— 失败入库不阻塞重新上传。

### 3.4 `document_keywords`

范围过滤用的标签 catalog：

| 列 | 类型 | 说明 |
|--------|------|-------|
| `document_id` | UUID | |
| `kb_name` | VARCHAR | |
| `keyword` | VARCHAR | 来自 Knowhere chunk 关键词 |
| `count` | INT | 出现次数 |

由 `GET /tags` 与查询时 `resolve_tags_to_document_ids()` 查询。

### 3.5 `task_audit`

| 列 | 类型 | 说明 |
|--------|------|-------|
| `job_id` | UUID PK | Celery 任务 ID |
| `document_id` | UUID | |
| `pipeline` | VARCHAR | router/knowhere/pixelrag |
| `kb_name` | VARCHAR | |
| `state` | VARCHAR | PENDING/RENDERING/…/SUCCESS/FAILED |
| `progress` | INT | 0-100 |
| `current` / `total` | INT | 进度计数 |
| `error` | TEXT | 最后错误消息 |
| `log` | JSONB | 追加式日志项 |
| `name` | VARCHAR | 文件名 |
| `source_uri` | VARCHAR | |

### 3.6 `sessions` / `session_messages`

聊天会话持久化：

| 表 | 关键字段 |
|-------|-----------|
| `sessions` | session_id, user_id, title, scope_filter (JSONB), kb_name |
| `session_messages` | message_id, session_id, role, content, sources (JSONB), steps (JSONB) |

持久化 `scope_filter`，后续查询继承 KB/doc/tag 范围。

### 3.7 `images`

视觉 tile 元数据（Milvus 向量补充）：

| 列 | 类型 | 说明 |
|--------|------|-------|
| `image_id` | VARCHAR PK | |
| `document_id` | UUID | |
| `object_key` | VARCHAR | MinIO path |
| `kb_name` | VARCHAR | |
| `page`, `position` | INT/VARCHAR | Tile 位置 |
| `width`, `height` | INT | 尺寸 |

### 3.8 `attachments`

会话级临时上传：

| 列 | 类型 | 说明 |
|--------|------|-------|
| `attachment_id` | UUID PK | |
| `session_id` | UUID | |
| `filename` | VARCHAR | |
| `object_key` | VARCHAR | MinIO |
| `expires_at` | TIMESTAMP | 来自 `attachments.ttl_hours` 的 TTL |

### 3.9 运维表

| 表 | 用途 |
|-------|---------|
| `notifications` | 用户通知（入库完成、错误） |
| `mcp_call_log` | MCP 工具调用审计 |
| `metric_samples` | 队列深度时间序列 |
| `system_settings` | 运行时可配置覆盖 |

---

## 4. 迁移工作流

```bash
# Generate migration after model change
alembic revision --autogenerate -m "describe change"

# Apply
task db:migrate
# or: alembic upgrade head
```

**约定：**

- 模型在 `eagle_rag/db/models/` —— 每域一文件。
- `alembic/env.py` 规范化 DSN：`postgresql+asyncpg://` → `postgresql+psycopg2://` 供迁移使用。
- store 模块无 DDL —— 所有 schema 变更经 Alembic。

---

## 5. 与 Milvus 的关系

PostgreSQL 存指针；Milvus 存可搜索向量：

| PostgreSQL | Milvus 过滤 |
|-----------|--------------|
| `documents.document_id` | `document_id == "..."` |
| `documents.kb_name` | `kb_name == "..."` |
| `documents.source_type` | `source_type == "..."` |
| `document_keywords.keyword` | 解析为 `document_id in [...]` |

KB 删除（`kb/lifecycle.py`）级联：PostgreSQL 行 → Milvus `delete_*_by_kb()` → MinIO 前缀清理。

---

## 6. LlamaIndex 集成

PostgreSQL 存文档 registry 元数据，与 LlamaIndex `TextNode.metadata` 镜像：

| PG 字段 | TextNode metadata |
|----------|------------------|
| `document_id` | `metadata.document_id` |
| `source_type` | `metadata.source_type` |
| `kb_name` | `metadata.kb_name` |
| `extra.doc_nav` | 经 structure API 提供（不在 Milvus） |

LlamaIndex docstore 可能本地缓存节点，但权威元数据在 Milvus dynamic 字段 + PostgreSQL registry。

---

## 7. 设计张力与调参

| 张力 | Schema / store | 后果 | 实践 |
| --- | --- | --- | --- |
| **JSONB scope 无 DB 约束** | `sessions.scope_filter` | 删除 doc 后 scope 仍含 stale ID —— 查询空结果非报错 | KB  purge 后客户端刷新 scope |
| **双驱动一致性** | asyncpg（API）vs psycopg2（worker） | 同 row 双路径更新 —— 与 Milvus 无分布式事务 | Postgres 为生命周期权威；Milvus 最终一致 |
| **CASCADE vs 向量 purge** | FK `document_keywords` ON DELETE CASCADE | SQL 干净；Milvus 向量需 lifecycle 显式 `delete_*` | 始终用 KB purge API，勿 raw SQL delete |
| **Alembic vs 运行时** | 模型在 `eagle_rag/db/models/` | 部署前未 migrate 则漂移 | 发布流水线跑 `task db:migrate` |
| **Task audit 增长** | `task_state` 仅追加日志 | 大 JSONB 日志数组拖慢 admin UI | 定期归档旧 audit |
| **消息历史无界** | 每 session 的 `messages` | 长聊加重 `GET /sessions/{id}` | 客户端分页；未来保留策略 |

---

## 8. 配置与调优

```yaml
postgres:
  dsn: postgresql://eagle:eagle@localhost:5432/eagle_rag
```

**环境：**

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

---

## 10. 参考文献

- SQLModel: [sqlmodel.tiangolo.com](https://sqlmodel.tiangolo.com/)
- Alembic: [alembic.sqlalchemy.org](https://alembic.sqlalchemy.org/)
- Gao et al., *RAG Survey*, [arXiv:2312.10997](https://arxiv.org/abs/2312.10997)
- Multi-tenant data architecture: [docs.aws.amazon.com/wellarchitected/latest/saas-lens](https://docs.aws.amazon.com/wellarchitected/latest/saas-lens/saas-lens.html)
