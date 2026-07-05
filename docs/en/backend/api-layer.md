# API layer

The API layer exposes Eagle-RAG's multimodal RAG capabilities via **FastAPI** HTTP endpoints and mounts the **FastMCP** streamable HTTP sub-app at `/mcp`. Routers validate requests with Pydantic schemas, delegate to the service layer (ingest runner, router engine, stores), and bridge SSE streaming for query/search paths.

**Source modules:** `eagle_rag/api/app.py`, `eagle_rag/api/query.py`, `eagle_rag/api/ingest.py`, `eagle_rag/api/documents.py`, and domain routers.

---

## 1. Theoretical background

### 1.1 RAG as a service API

Production RAG systems expose three core API surfaces (Gao et al., RAG Survey, arXiv:2312.10997):

| Surface | Eagle-RAG endpoint |
|---------|-------------------|
| **Ingest** — add documents to the index | `POST /ingest` |
| **Retrieve** — fetch relevant chunks | `POST /search`, `/search/stream` |
| **Generate** — answer with citations | `POST /query`, `/query/stream` |

Eagle-RAG adds evidence endpoints (`GET /documents/{id}/structure`, `/file`, `/chunks/{id}`) for grounded UI rendering.

### 1.2 Server-Sent Events (SSE) for streaming

Streaming generation uses SSE — the standard for unidirectional server→client push in HTTP/1.1 (WHATWG HTML Living Standard). Each event carries `event` + `data` JSON for route/recall/rerank/token/done steps.

### 1.3 Multi-tenant API design

Every multi-tenant endpoint accepts optional `kb_name`, falling back to `settings.kb_name`. Scope filters (`ScopeSelection`) push tenant/document/tag constraints to Milvus — implementing **request-scoped retrieval isolation**.

---

## 2. Application structure

**Entry:** `eagle_rag/api/app.py`

```python
app = FastAPI(title="Eagle-RAG", version="0.1.0", lifespan=get_combined_lifespan(mcp_app))
```

### 2.1 Middleware stack

| Middleware | Purpose |
|-----------|---------|
| `TelemetryMiddleware` | OpenTelemetry SERVER span per request |
| `GZipMiddleware` | Compress JSON >1KB (retrieval payloads) |
| `CORSMiddleware` | Allow frontend cross-origin (`*`) |

No authentication middleware — intranet-only by design.

### 2.2 Mounted routers

| Router | Prefix | Module |
|--------|--------|--------|
| Health | `/health`, `/admin/*` | `api/health.py` |
| Documents | `/documents` | `api/documents.py` |
| Images | `/images` | `api/documents.py` |
| Ingest | `/ingest` | `api/ingest.py` |
| Knowledge bases | `/knowledge-bases` | `api/knowledge_bases.py` |
| Tags | `/tags` | `api/tags.py` |
| Attachments | `/attachments` | `api/attachments.py` |
| Notifications | `/notifications` | `api/notifications.py` |
| Users | `/users` | `api/users.py` |
| Query/Sessions | `/query`, `/sessions` | `api/query.py` |
| MCP sub-app | `/mcp` | `api/mcp_http.py` |

### 2.3 Infrastructure endpoints

| Path | Handler | Purpose |
|------|---------|---------|
| `/metrics` | Prometheus metrics | Scraping |
| `/health` | Health check | Docker/HAProxy probes |
| `/docs` | OpenAPI UI | API exploration |

---

## 3. Code walkthrough: query endpoints

**Module:** `eagle_rag/api/query.py`

### 3.1 Query engine singleton

```python
_engine: EagleRouterQueryEngine | None = None

def get_query_engine() -> EagleRouterQueryEngine:
    global _engine
    if _engine is None:
        _engine = EagleRouterQueryEngine(top_k=settings.pixelrag.top_k)
    return _engine
```

Lazy singleton avoids import-time Milvus/embedding connections.

### 3.2 Core endpoints

| Method | Path | Engine method | Response |
|--------|------|--------------|----------|
| POST | `/query` | `engine.query()` | `QueryResponse` |
| POST | `/query/stream` | `engine.query_stream()` | SSE |
| POST | `/search` | `engine.search()` | `SearchResponse` |
| POST | `/search/stream` | `engine.search_stream()` | SSE |

All accept `QueryRequest`:

```python
class QueryRequest(BaseModel):
    query: str
    mode: str | None = "auto"
    kb_name: str | None = None
    top_k: int = 5
    scope: list[str] | None = None
    scope_filter: ScopeSelection | None = None
    filters: dict | None = None
    attachments: list[str] | None = None
    session_id: str | None = None
```

### 3.3 SSE bridging

```python
async def _sse_generator(events: Iterator[dict]) -> AsyncGenerator[str, None]:
    for item in events:
        yield f"event: {item['event']}\ndata: {json.dumps(item['data'])}\n\n"
```

Wrapped in `StreamingResponse(media_type="text/event-stream")`.

### 3.4 Session integration

When `session_id` is provided on `/query/stream`:

1. Load or create session via `sessions.store`.
2. Persist user message before streaming.
3. On `done` event, persist assistant message with sources/steps.
4. Yield `session` event with `session_id` + `user_message_id`.

---

## 4. Code walkthrough: ingest endpoints

**Module:** `eagle_rag/api/ingest.py`

| Method | Path | Action |
|--------|------|--------|
| POST | `/ingest` | Multipart file upload → `runner.ingest()` |
| POST | `/ingest/url` | URL ingest |
| GET | `/tasks/{job_id}` | Task audit status |
| GET | `/tasks` | List recent tasks |

File upload flow:

1. Read bytes from `UploadFile`.
2. Call `ingest(file_bytes=..., filename=..., kb_name=...)`.
3. Return `IngestResponse` with job_id/document_id.

---

## 5. Code walkthrough: evidence endpoints

**Module:** `eagle_rag/api/documents.py`

| Method | Path | Data source |
|--------|------|------------|
| GET | `/documents` | PostgreSQL registry |
| GET | `/documents/{id}` | Document detail |
| GET | `/documents/{id}/structure` | `doc_nav` from `extra` or Milvus rebuild |
| GET | `/documents/{id}/file` | MinIO presigned URL |
| GET | `/documents/{id}/chunks/{chunk_id}` | Milvus text node by ID |
| DELETE | `/documents/{id}` | Cascade delete |

Structure endpoint enables the frontend document tree viewer without re-parsing.

---

## 6. Milvus interaction (via service layer)

The API layer never calls Milvus directly. Filter expressions are assembled by retrievers based on request parameters:

```
# From QueryRequest.kb_name
kb_name == "finance"

# From QueryRequest.scope_filter
(kb_name in ["finance", "pharma"] or document_id in ["doc-1"])
```

See [retrieval](retrieval.md) and [vector-stores](vector-stores.md).

---

## 7. LlamaIndex integration

The API layer invokes `EagleRouterQueryEngine` which internally uses:

- `VectorStoreIndex.as_retriever()` for text ANN
- `CustomQueryEngine` (`EagleMultimodalQueryEngine`) for generation
- `TextNode` / `ImageNode` / `NodeWithScore` throughout the pipeline

No LlamaIndex types leak to API responses — Pydantic schemas map nodes to `SourceText` / `SourceImage` DTOs.

---

## 8. Design tensions and tuning

| Tension | Endpoint / layer | Effect | Dial |
| --- | --- | --- | --- |
| **SSE thread bridge** | `query_stream` runs sync VLM in executor | One OS thread per active stream — caps concurrent users on small pods | Limit ingress concurrency; use non-stream `/query` for batch |
| **Sync query tail latency** | `POST /query` blocks through full generation | MCP and REST sync callers wait for rerank + VLM | Prefer `/query/stream` for UX; set client timeouts > 120s |
| **Source payload cap** | `_text_source` + `source_content_max_chars` | Evidence panel truncated vs model context | Raise `router.source_content_max_chars` (response only) |
| **Scope validation gap** | Pydantic accepts any `scope_filter` lists | Oversized `document_ids` may exceed Milvus expr limits | Keep under `max_scope_documents`; validate in client |
| **kb_name fallback** | Handler uses `settings.kb_name` when omitted | Multi-tenant agents accidentally query wrong KB | Require explicit `kb_name` in agent integrations |
| **Evidence HTML fetch** | `GET /chunks/{chunk_id}` MinIO round-trip | Large table HTML slow for evidence rail | Cache in frontend; lazy-load chunk preview |
| **Health vs admin cost** | `/health` probes all deps with timeout | Frequent K8s probes load Milvus + Celery | Use `/health/live` pattern if split later |

---

## 9. Config & tuning

```yaml
app:
  host: 0.0.0.0
  port: 8000

pixelrag:
  top_k: 5              # default retrieval breadth for query engine singleton

router:
  source_content_max_chars: 4000

attachments:
  ttl_hours: 24
```

**Environment:**

```
APP_PORT=8000
KB_NAME=default
```

---

## 10. Tests

| Test file | Coverage |
|-----------|----------|
| `tests/test_api_query_sessions_documents_tasks.py` | Query, search, SSE, sessions, documents |
| `tests/test_api_ingest_queue_metrics.py` | Ingest + task listing |
| `tests/test_api_admin_health.py` | Health + admin endpoints |
| `tests/test_api_kb_attachments_notifications_users.py` | KB, attachments, notifications |
| `tests/test_mcp_http_transport.py` | MCP mount at `/mcp` |

---

## 11. Dual database drivers

| Context | Driver | Placeholder |
|---------|--------|-------------|
| FastAPI handlers | asyncpg | `$1`, `$2` |
| Celery / sync stores | psycopg2 | `%s` |

Session and notification stores expose async variants for route handlers; ingest/task paths use sync stores.

---

## 12. References

- FastAPI: [fastapi.tiangolo.com](https://fastapi.tiangolo.com/)
- SSE specification: [html.spec.whatwg.org/multipage/server-sent-events.html](https://html.spec.whatwg.org/multipage/server-sent-events.html)
- Gao et al., *RAG Survey*, [arXiv:2312.10997](https://arxiv.org/abs/2312.10997)
- OpenTelemetry FastAPI: [opentelemetry.io/docs/instrumentation/python/fastapi](https://opentelemetry.io/docs/instrumentation/python/fastapi/)
- LlamaIndex query engines: [docs.llamaindex.ai/module_guides/deploying/query_engine](https://docs.llamaindex.ai/en/stable/module_guides/deploying/query_engine/)
