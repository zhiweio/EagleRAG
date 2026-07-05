# 会话与通知

聊天会话在 PostgreSQL 中持久化查询历史、范围过滤与消息元数据（sources、steps）。通知在入库任务到达终态时提醒用户。两模块在 FastAPI 处理器中使用异步数据库访问。

**源码模块：** `eagle_rag/sessions/store.py`、`eagle_rag/notifications/store.py`、`eagle_rag/api/query.py`、`eagle_rag/api/notifications.py`

---

## 1. 理论背景

### 1.1 对话式 RAG

多轮 RAG 需要**会话状态**跨查询保持上下文（Gao et al., arXiv:2312.10997）。Eagle-RAG 持久化：

- 消息历史（user + assistant）
- 检索范围（`scope_filter`）供后续查询
- 执行轨迹（`steps`）供透明化

与记忆增强 Agent（MemGPT, Packer et al., arXiv:2310.08560）不同，Eagle-RAG 存显式消息记录而非学习式记忆压缩 —— 更简单、可审计。

### 1.2 范围持久化

会话上的 `ScopeSelection`（kb_names, document_ids, tags）保证后续查询继承相同 Milvus 过滤约束，无需重新选择：

```
(kb_name in ["finance"] or document_id in ["doc-1", "doc-2"])
```

---

## 2. 会话模型

**PostgreSQL 表：** `sessions`, `session_messages`

### 2.1 会话字段

| 字段 | 类型 | 用途 |
|-------|------|---------|
| `session_id` | UUID PK | |
| `user_id` | UUID FK | 所有者 |
| `title` | VARCHAR | 自动生成或用户设置 |
| `kb_name` | VARCHAR | 默认租户 |
| `scope_filter` | JSONB | 持久化 ScopeSelection |
| `created_at` / `updated_at` | TIMESTAMP | |

### 2.2 消息字段

| 字段 | 类型 | 用途 |
|-------|------|---------|
| `message_id` | UUID PK | |
| `session_id` | UUID FK | |
| `role` | VARCHAR | user / assistant |
| `content` | TEXT | 消息正文 |
| `sources` | JSONB | `{text: [...], image: [...]}` |
| `steps` | JSONB | route/recall/rerank/generate 轨迹 |
| `route` | JSONB | RouteDecision 快照 |
| `created_at` | TIMESTAMP | |

---

## 3. 代码走读：会话 store

**模块：** `eagle_rag/sessions/store.py`

| 函数 | 用途 |
|----------|---------|
| `create_session(user_id, kb_name, scope_filter)` | 新会话 |
| `get_session(session_id)` | 含消息获取 |
| `list_sessions(user_id)` | 用户会话列表 |
| `add_message(session_id, role, content, ...)` | 追加消息 |
| `update_session_title(session_id, title)` | 重命名 |
| `delete_session(session_id)` | 删除会话及消息 |

### 查询集成

带 `session_id` 的 `POST /query/stream`：

1. 创建/加载会话。
2. 流式前持久化用户消息。
3. 从路由引擎流式 SSE。
4. `done` 事件时持久化 assistant 消息（完整 sources/steps）。

```python
# SSE flow in api/query.py
yield {"event": "session", "data": {"session_id": ..., "user_message_id": ...}}
# ... route, recall, rerank, token events ...
# On done: sessions.store.add_message(role="assistant", sources=..., steps=...)
```

---

## 4. 通知

**模块：** `eagle_rag/notifications/store.py`

### 触发点

入库任务到达终态时创建通知：

| 事件 | 通知 |
|-------|-------------|
| Task SUCCESS | "Document {name} indexed successfully" |
| Task FAILED | "Document {name} failed: {error}" |

由 `tasks/state.py` 状态迁移写入（尽力而为、非阻塞）。

### API

| 方法 | 路径 | 动作 |
|--------|------|--------|
| GET | `/notifications` | 列出用户通知 |
| PUT | `/notifications/{id}/read` | 标为已读 |
| DELETE | `/notifications/{id}` |  dismiss |

---

## 5. Milvus 范围继承

会话持久化 `scope_filter` 时，后续查询合并进检索器配置：

```python
scope_filter = session.scope_filter or request.scope_filter
# → EagleRouterQueryEngine.retrieve(scope_filter=scope_filter)
# → MetadataFilters pushed to Milvus
```

继承过滤示例：

```
(kb_name in ["finance"] or document_id in ["doc-a", "doc-b"]) and source_type == "policy"
```

---

## 6. LlamaIndex 集成

会话消息存储 LlamaIndex 流水线各阶段输出：

| 存储字段 | LlamaIndex 来源 |
|-------------|------------------|
| `sources.text[].path` | TextNode metadata |
| `sources.image[].image_id` | ImageNode metadata |
| `steps[].text_top` | 重排后 TextNode path |
| `steps[].visual_top` | 重排后 ImageNode ID |

不直接持久化 LlamaIndex 对象 —— 仅序列化 DTO。

---

## 7. 设计张力与调参

| 张力 | 字段 / 流程 | 效果 | 实践 |
| --- | --- | --- | --- |
| **持久化 scope 漂移** | `sessions.scope_filter` JSONB | 已删文档仍在 scope → 空检索 | KB 管理操作后对账 scope |
| **Session kb_name vs query** | Session 默认 + 每 query 覆盖 | 客户端 `kb_name` 冲突时混乱 | 每 query 的 `kb_name` 为权威 |
| **消息回放体积** | 为上下文加载全历史 | 大会话拖慢 `GET /sessions/{id}` | UI 分页消息 |
| **通知扇出** | 入库完成每用户一行 | 入库洪峰无背压 | 批量或限流通知创建 |
| **Scope 继承** | 前端恢复 scope 到 Zustand | 关键词 catalog 变则 tag stale | 入库后重拉 `/tags` |

---

## 8. 配置与调优

会话与通知使用标准 PostgreSQL DSN。无独立配置段 —— TTL 与限制隐式（默认无会话过期）。

---

## 9. 测试

| 测试文件 | 覆盖 |
|-----------|----------|
| `tests/test_api_query_sessions_documents_tasks.py` | 会话 CRUD、消息持久化、流式 |
| `tests/test_api_kb_attachments_notifications_users.py` | 通知列表/已读 |

---

## 10. API 端点

**Sessions**（`eagle_rag/api/query.py`）：

| 方法 | 路径 | 动作 |
|--------|------|--------|
| POST | `/sessions` | 创建会话 |
| GET | `/sessions` | 列出用户会话 |
| GET | `/sessions/{id}` | 获取含消息的会话 |
| PATCH | `/sessions/{id}` | 更新 title / scope_filter |
| DELETE | `/sessions/{id}` | 删除会话 |

**Notifications**（`eagle_rag/api/notifications.py`）：

| 方法 | 路径 | 动作 |
|--------|------|--------|
| GET | `/notifications` | 列出未读/已读 |
| PUT | `/notifications/{id}/read` | 标为已读 |
| DELETE | `/notifications/{id}` | Dismiss |

---

## 11. 附件与会话交互

查询同时含 `attachments: [attachment_id, ...]` 与 `session_id` 时：

1. 懒解析附件（`attachments/parser.py`）。
2. 解析文本节点前置到检索结果，`score=1.0`。
3. 解析图片作为 `ImageDocument` 传给 VLM。
4. 附件解析步骤出现在 `steps` 轨迹。
5. 文档附件经 `AttachmentSelector` 触发 hybrid 路由。

附件会话级，按 `attachments.ttl_hours` 过期 —— 不写入 Milvus。

---

## 12. 经会话的 LlamaIndex 查询路径

```
POST /query/stream {query, session_id, scope_filter}
  → sessions.store.load(session_id)
  → merge session.scope_filter with request scope_filter
  → EagleRouterQueryEngine.query_stream(...)
  → EagleMultimodalQueryEngine.stream_custom_query(...)
  → on done: sessions.store.add_message(assistant, sources, steps)
```

会话 store 是薄 PostgreSQL 包装 —— 无 LlamaIndex memory 模块。每查询重新取完整检索上下文（检索无状态，范围有状态）。

---

## 13. 参考文献

- Gao et al., *RAG Survey*, [arXiv:2312.10997](https://arxiv.org/abs/2312.10997)
- Packer et al., *MemGPT*, [arXiv:2310.08560](https://arxiv.org/abs/2310.08560)
- FastAPI SSE: [fastapi.tiangolo.com/advanced/custom-response](https://fastapi.tiangolo.com/advanced/custom-response/)
- LlamaIndex chat engines: [docs.llamaindex.ai/en/stable/module_guides/deploying/chat_engines](https://docs.llamaindex.ai/en/stable/module_guides/deploying/chat_engines/)
