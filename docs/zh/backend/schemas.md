# API Schema

Eagle-RAG API 契约在 `eagle_rag/api/schemas/` 中定义为 **Pydantic v2** 模型。FastAPI 路由使用 `response_model=` 做自动校验、序列化与 OpenAPI 生成。前端 TypeScript 类型从同一 OpenAPI 规范生成。

**源码目录：** `eagle_rag/api/schemas/`

---

## 1. 理论背景

### 1.1 Schema 驱动的 API 设计

类型化请求/响应 schema 在客户端与 RAG 流水线边界强制契约（Gao et al., arXiv:2312.10997）。收益：

- **校验** — 昂贵检索前拒绝畸形查询。
- **文档** — `/docs` 自动生成 OpenAPI。
- **类型安全** — 前端经 `@hey-api/openapi-ts`  codegen。

### 1.2 范围作为一等概念

`ScopeSelection` 建模多租户过滤并映射到 Milvus 布尔表达式 —— 使租户隔离成为显式 API 关切，而非实现细节。

---

## 2. Schema 组织

| 模块 | 域 |
|--------|--------|
| `common.py` | 共享类型、分页、根响应 |
| `query.py` | QueryRequest、QueryResponse、SearchResponse、ScopeSelection |
| `ingest.py` | IngestResponse、TaskStatus、TaskList |
| `documents.py` | DocumentOut、DocumentStructure、ChunkOut |
| `sessions.py` | SessionOut、MessageOut、CreateSessionRequest |
| `knowledge_bases.py` | KbOut、KbCreate、KbStats、KbHealth |
| `attachments.py` | AttachmentOut、UploadResponse |
| `notifications.py` | NotificationOut |
| `tags.py` | TagOut、TagList |
| `users.py` | UserOut |
| `health.py` | HealthStatus、AdminConfigOut、QueueMetrics |
| `_helpers.py` |  sanitize、字段校验器 |

---

## 3. 核心查询 Schema

**模块：** `eagle_rag/api/schemas/query.py`

### 3.1 QueryRequest

```python
class ScopeSelection(BaseModel):
    kb_names: list[str] = []
    document_ids: list[str] = []
    tags: list[str] = []

class QueryRequest(BaseModel):
    query: str
    mode: Literal["auto", "text", "visual", "hybrid"] | None = "auto"
    kb_name: str | None = None
    top_k: int = Field(default=5, ge=1, le=50)
    scope: list[str] | None = None          # legacy document_id list
    scope_filter: ScopeSelection | None = None
    filters: dict[str, Any] | None = None   # source_type, year, pipeline
    attachments: list[str] | None = None    # attachment_ids
    session_id: str | None = None
```

**Milvus 映射：**

| 字段 | Milvus 效果 |
|-------|--------------|
| `kb_name` | `kb_name == "{value}"` |
| `scope_filter.kb_names` | `kb_name in [...]` |
| `scope_filter.document_ids` | `document_id in [...]` |
| `scope_filter.tags` | 解析为 `document_id in [...]` |
| `filters.source_type` | `source_type == "{value}"` |
| `filters.year` | `year == {value}` |

### 3.2 QueryResponse

```python
class SourceText(BaseModel):
    type: str
    path: str | None
    level: int | None
    document_id: str | None
    score: float | None
    content: str | None          # capped by source_content_max_chars
    summary: str | None
    keywords: list[str] = []
    page_nums: list[int] = []
    kb_name: str | None
    source_type: str | None
    chunk_count: int | None      # section_summary only

class SourceImage(BaseModel):
    type: Literal["image"] = "image"
    image_id: str | None
    image_path: str | None
    page: int | None
    position: str | None
    document_id: str | None
    score: float | None
    chunk_type: str | None       # tile/image/table
    parent_section: str | None   # fusion anchor
    content_summary: str | None
    source_chunk_id: str | None
    kb_name: str | None
    year: int | None

class QueryResponse(BaseModel):
    answer: str
    sources: SourcesOut          # {text: [SourceText], image: [SourceImage]}
    route: RouteOut              # {mode, selected, reason, selector}
    steps: list[StepOut]         # route/recall/rerank/generate trace
```

### 3.3 SearchResponse

与 QueryResponse 相同但无 `answer` —— 纯检索输出。

---

## 4. 入库 Schema

**模块：** `eagle_rag/api/schemas/ingest.py`

```python
class IngestResponse(BaseModel):
    job_id: str
    status: Literal["pending", "success"]
    document_id: str
    dedup_hit: bool

class TaskStatus(BaseModel):
    job_id: str
    document_id: str | None
    state: str                   # TaskState enum value
    progress: int | None
    current: int | None
    total: int | None
    error: str | None
    log: list[LogEntry] | None
    pipeline: str | None
    kb_name: str | None
    name: str | None
```

---

## 5. 文档 Schema

**模块：** `eagle_rag/api/schemas/documents.py`

```python
class DocumentOut(BaseModel):
    document_id: str
    name: str
    source_type: str
    pipeline: str
    kb_name: str
    status: str
    chunk_count: int | None
    source_uri: str | None
    created_at: datetime

class SectionNode(BaseModel):
    path: str
    level: int
    title: str
    summary: str
    chunk_count: int
    children: list[SectionNode] = []

class DocumentStructure(BaseModel):
    document_id: str
    sections: list[SectionNode]  # from extra.doc_nav or Milvus rebuild
```

---

## 6. 会话 Schema

**模块：** `eagle_rag/api/schemas/sessions.py`

```python
class SessionOut(BaseModel):
    session_id: str
    title: str | None
    kb_name: str | None
    scope_filter: ScopeSelection | None
    messages: list[MessageOut]
    created_at: datetime
    updated_at: datetime

class MessageOut(BaseModel):
    message_id: str
    role: Literal["user", "assistant"]
    content: str
    sources: SourcesOut | None
    steps: list[StepOut] | None
    route: RouteOut | None
    created_at: datetime
```

---

## 7. 管理 Schema

**模块：** `eagle_rag/api/schemas/health.py`

```python
class AdminConfigOut(BaseModel):
    app: AppSettings
    kb_name: str
    milvus: MilvusSettings
    router: RouterSettings
    # ... full settings tree with api_key → "***"
```

镜像 `eagle_rag/config.py` Settings 模型，密钥已脱敏。

---

## 8. LlamaIndex 类型映射

Schema 是边界 DTO —— 内部 LlamaIndex 类型映射如下：

| LlamaIndex | Pydantic schema |
|-----------|----------------|
| `TextNode` + score | `SourceText` |
| `ImageNode` + score | `SourceImage` |
| `RouteDecision` | `RouteOut` |
| Pipeline steps dict | `StepOut` |
| `NodeWithScore` list | `SourcesOut` |

映射函数在 `EagleMultimodalQueryEngine._text_source()` / `_image_source()` 与 `EagleRouterQueryEngine._map_nodes_to_search_payload()`。

---

## 9. OpenAPI 生成

FastAPI 在 `/openapi.json` 自动生成 OpenAPI 3.1。前端 codegen：

```bash
cd frontend && bun run generate:api
# → frontend/lib/api/generated/types.gen.ts
```

所有路由指定 `response_model=`，保证响应形状与 schema 一致。

---

## 10. 校验规则

| 字段 | 规则 |
|-------|------|
| `QueryRequest.query` | 必填、非空 |
| `QueryRequest.top_k` | 1–50 |
| `ScopeSelection` tags | 服务端解析并带上限 |
| `IngestResponse.status` | 仅 `pending` 或 `success` |
| 创建时 `kb_name` | 须匹配 `^[a-z][a-z0-9_-]*$` |

`_helpers.py` 中自定义校验器做规范化（去空白、小写枚举等）。

---

## 11. 反映配置的 Schema

若干 schema 镜像 `settings.yaml` 段，供 admin/config 端点：

| Settings 段 | Schema 类型 |
|-----------------|------------|
| `router.*` | `RouterSettings` |
| `milvus.*` | `MilvusSettings` |
| `rerank.*` | `RerankSettings` |
| `celery.*` | `CelerySettings` |

定义在 `eagle_rag/config.py`，在 `health.py` schema 中再导出。

---

## 12. 设计张力与调参

| 张力 | Schema 字段 | 运行时效果 | 指引 |
| --- | --- | --- | --- |
| **空 vs 省略 scope** | `ScopeSelection` 默认 `[]` | 全空 → 遗留全 KB；部分空列表仍 OR 并集 | 文档化「清 scope」为显式空对象 vs 省略 |
| **列表大小 vs Milvus** | Pydantic 不限制 `document_ids`、`tags` | Router 在 `max_scope_documents` 截断 tag 扩展 —— 静默 | 大批量 tag 选择前客户端校验 |
| **SSE 事件类型** | 流式模型描述 `event` + `data` | 忽略未知事件的客户端在 additive 字段上坏 | 前端前向兼容解析 |
| **OpenAPI 漂移** | 自 schema 的 `types.gen.ts` | 前端编译期安全；schema 变更须 regen | `eagle_rag/api/schemas/` 变更时 CI 跑 `bun run api:gen` |
| **Attachment ID 格式** | 不透明字符串引用 | 无效 ID 在 query 解析时失败，非 upload 时 | 仅引用 upload 返回的 ID |

---

## 13. 测试

Schema 校验经 API 测试间接覆盖：

| 测试文件 | Schema 覆盖 |
|-----------|----------------|
| `tests/test_api_query_sessions_documents_tasks.py` | QueryRequest/Response、SessionOut |
| `tests/test_api_ingest_queue_metrics.py` | IngestResponse、TaskStatus |
| `tests/test_api_kb_attachments_notifications_users.py` | KbOut、AttachmentOut、NotificationOut |

---

## 14. 参考文献

- Pydantic v2: [docs.pydantic.dev/latest](https://docs.pydantic.dev/latest/)
- FastAPI response models: [fastapi.tiangolo.com/tutorial/response-model](https://fastapi.tiangolo.com/tutorial/response-model/)
- OpenAPI: [swagger.io/specification](https://swagger.io/specification/)
- Gao et al., *RAG Survey*, [arXiv:2312.10997](https://arxiv.org/abs/2312.10997)
