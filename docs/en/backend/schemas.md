# API schemas

Eagle-RAG API contracts are defined as **Pydantic v2** models in `eagle_rag/api/schemas/`. FastAPI routers use `response_model=` for automatic validation, serialization, and OpenAPI generation. The frontend TypeScript types are generated from the same OpenAPI spec.

**Source directory:** `eagle_rag/api/schemas/`

---

## 1. Theoretical background

### 1.1 Schema-driven API design

Typed request/response schemas enforce contracts at the boundary between clients and the RAG pipeline (Gao et al., arXiv:2312.10997). Benefits:

- **Validation** — reject malformed queries before expensive retrieval.
- **Documentation** — auto-generated OpenAPI at `/docs`.
- **Type safety** — frontend codegen via `@hey-api/openapi-ts`.

### 1.2 Scope as a first-class concept

`ScopeSelection` models the multi-tenant filter that maps to Milvus boolean expressions — making tenant isolation an explicit API concern rather than an implementation detail.

---

## 2. Schema organization

| Module | Domain |
|--------|--------|
| `common.py` | Shared types, pagination, root response |
| `query.py` | QueryRequest, QueryResponse, SearchResponse, ScopeSelection |
| `ingest.py` | IngestResponse, TaskStatus, TaskList |
| `documents.py` | DocumentOut, DocumentStructure, ChunkOut |
| `sessions.py` | SessionOut, MessageOut, CreateSessionRequest |
| `knowledge_bases.py` | KbOut, KbCreate, KbStats, KbHealth |
| `attachments.py` | AttachmentOut, UploadResponse |
| `notifications.py` | NotificationOut |
| `tags.py` | TagOut, TagList |
| `users.py` | UserOut |
| `health.py` | HealthStatus, AdminConfigOut, QueueMetrics |
| `_helpers.py` | Sanitization, field validators |

---

## 3. Core query schemas

**Module:** `eagle_rag/api/schemas/query.py`

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

**Milvus mapping:**

| Field | Milvus effect |
|-------|--------------|
| `kb_name` | `kb_name == "{value}"` |
| `scope_filter.kb_names` | `kb_name in [...]` |
| `scope_filter.document_ids` | `document_id in [...]` |
| `scope_filter.tags` | Resolved to `document_id in [...]` |
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

Same as QueryResponse minus `answer` — pure retrieval output.

---

## 4. Ingest schemas

**Module:** `eagle_rag/api/schemas/ingest.py`

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

## 5. Document schemas

**Module:** `eagle_rag/api/schemas/documents.py`

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

## 6. Session schemas

**Module:** `eagle_rag/api/schemas/sessions.py`

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

## 7. Admin schemas

**Module:** `eagle_rag/api/schemas/health.py`

```python
class AdminConfigOut(BaseModel):
    app: AppSettings
    kb_name: str
    milvus: MilvusSettings
    router: RouterSettings
    # ... full settings tree with api_key → "***"
```

Mirrors `eagle_rag/config.py` Settings model with secret sanitization.

---

## 8. LlamaIndex type mapping

Schemas are the boundary DTOs — internal LlamaIndex types map as follows:

| LlamaIndex | Pydantic schema |
|-----------|----------------|
| `TextNode` + score | `SourceText` |
| `ImageNode` + score | `SourceImage` |
| `RouteDecision` | `RouteOut` |
| Pipeline steps dict | `StepOut` |
| `NodeWithScore` list | `SourcesOut` |

Mapping functions live in `EagleMultimodalQueryEngine._text_source()` / `_image_source()` and `EagleRouterQueryEngine._map_nodes_to_search_payload()`.

---

## 9. OpenAPI generation

FastAPI auto-generates OpenAPI 3.1 spec at `/openapi.json`. Frontend codegen:

```bash
cd frontend && bun run generate:api
# → frontend/lib/api/generated/types.gen.ts
```

All routers specify `response_model=` ensuring response shapes match schemas.

---

## 10. Validation rules

| Field | Rule |
|-------|------|
| `QueryRequest.query` | Required, non-empty |
| `QueryRequest.top_k` | 1–50 |
| `ScopeSelection` tags | Resolved server-side with cap |
| `IngestResponse.status` | `pending` or `success` only |
| `kb_name` on create | Must match `^[a-z][a-z0-9_-]*$` |

Custom validators in `_helpers.py` handle normalization (strip whitespace, lowercase enums).

---

## 11. Config-reflecting schemas

Several schemas mirror `settings.yaml` sections for admin/config endpoints:

| Settings section | Schema type |
|-----------------|------------|
| `router.*` | `RouterSettings` |
| `milvus.*` | `MilvusSettings` |
| `rerank.*` | `RerankSettings` |
| `celery.*` | `CelerySettings` |

Defined in `eagle_rag/config.py`, re-exported in `health.py` schemas.

---

## 12. Design tensions and tuning

| Tension | Schema field | Runtime effect | Guidance |
| --- | --- | --- | --- |
| **Empty vs omitted scope** | `ScopeSelection` defaults `[]` | All-empty → legacy full-KB behavior; partial empty lists still OR union | Document “clear scope” as explicit empty object vs omit |
| **List size vs Milvus** | `document_ids`, `tags` unbounded in Pydantic | Router caps tag expansion at `max_scope_documents` — silent truncation | Validate client-side before bulk tag select |
| **SSE event typing** | Stream models document `event` + `data` | Clients ignoring unknown events break on additive fields | Forward-compatible parsing in frontend |
| **OpenAPI drift** | `types.gen.ts` from schema | Frontend compile-time safety; regen required after schema change | `bun run api:gen` in CI on `eagle_rag/api/schemas/` changes |
| **Attachment ID format** | Opaque string refs | Invalid ID fails at parse time in query, not at upload | Upload then reference returned ID only |

---

## 13. Tests

Schema validation is tested indirectly through API tests:

| Test file | Schema coverage |
|-----------|----------------|
| `tests/test_api_query_sessions_documents_tasks.py` | QueryRequest/Response, SessionOut |
| `tests/test_api_ingest_queue_metrics.py` | IngestResponse, TaskStatus |
| `tests/test_api_kb_attachments_notifications_users.py` | KbOut, AttachmentOut, NotificationOut |

---

## 14. References

- Pydantic v2: [docs.pydantic.dev/latest](https://docs.pydantic.dev/latest/)
- FastAPI response models: [fastapi.tiangolo.com/tutorial/response-model](https://fastapi.tiangolo.com/tutorial/response-model/)
- OpenAPI: [swagger.io/specification](https://swagger.io/specification/)
- Gao et al., *RAG Survey*, [arXiv:2312.10997](https://arxiv.org/abs/2312.10997)
