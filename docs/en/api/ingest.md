# Ingest API

Document ingestion enters through **`POST /ingest`** and is tracked via **`/tasks`** and **`/ingest/queue-metrics`**. Preflight uses separate validate endpoints. Implementation: `eagle_rag/api/ingest.py`, schemas in `eagle_rag/api/schemas/ingest.py`, runner in `eagle_rag/ingest/runner.py`.

## Preflight: validate before enqueue

UI and API clients should call validate first, then enqueue. File and URL use **different** endpoints and error vocabularies.

### `POST /ingest/validate/file`

Multipart `file` only. Enforces MinerU `ingest.limits` (size + PDF pages) via `validate_file_preflight`. Extensible for future per-type checks.

**`200 FileValidateResponse`:** `ok`, `filename`, `size_bytes`, `resource_kind`, `page_count?`, `content_type?`

**`422`:** `IngestLimitErrorDetail` — `file_too_large` | `pdf_too_many_pages` | `pdf_unreadable`

### `POST /ingest/validate/url`

Form field `url`. Runs format → bounded-DNS SSRF → HEAD/GET prefetch → content-type-aware checks:

| `resource_kind` | Extra checks |
|-----------------|--------------|
| `html` | Reachability only |
| `pdf` | Same MinerU size/page rules as local files (stream download capped at `max_file_bytes`) |
| `image` / `other` | `Content-Length` vs `max_file_bytes` when present |

**`200 UrlValidateResponse`:** `ok`, `status_code`, `content_type`, `final_url`, `resource_kind`, `size_bytes?`, `page_count?`, `suggested_pipeline?`

**`422`:** URL codes (`invalid_url_format`, `url_target_forbidden`, `url_unreachable`, `url_timeout`, `url_bad_status`) or shared limit codes for PDF/size.

Config: `ingest.url_prefetch` (`dns_timeout_sec`, `timeout_sec`, `max_redirects`, `pdf_download_timeout_sec`).

## `POST /ingest`

Unified **enqueue** entry for **multipart file upload** or **URL form field** (after client validate).

### Request

**Content-Type:** `multipart/form-data`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file` | `UploadFile` | One of `file` / `url` | Raw bytes |
| `url` | `string` | One of `file` / `url` | `http://` or `https://` source |
| `filename` | `string` | No | Optional display/routing name (e.g. `knowhere:https://…`) for URL ingest |
| `source_type_hint` | `string` | No | Free-form source type metadata |
| `kb_name` | `string` | No | Target KB; must be registered |

### Response — `IngestResponse`

```json
{
  "job_id": "celery-uuid",
  "status": "pending",
  "dedup_hit": false,
  "document_id": "doc_abc123"
}
```

| HTTP | Condition |
|------|-----------|
| `201` | New ingest dispatched |
| `200` | Dedup hit — existing `(sha256, kb_name)` row reused |
| `404` | Knowledge base not registered |
| `422` | Missing file/url, validation error, SSRF/format failure |
| `500` | Runner exception (`{"detail": "…"}` JSON body) |

### URL enqueue gate

Before Celery dispatch (lightweight; reachability belongs to validate):

1. `validate_url_format(url)`
2. `assert_not_ssrf_target(url)` — bounded DNS; blocks private IPs / metadata endpoints

Workers re-check SSRF before HTTP fetch. File path still runs `validate_ingest_file` as a safety net.

422 responses may include structured `UrlValidationErrorDetail`:

```json
{
  "detail": {
    "code": "url_unreachable",
    "reason": "Connection timed out",
    "suggestion": "Check firewall rules"
  }
}
```

### Pipeline routing

After `ingest_router` (Celery `router_queue`), documents route by format + content form:

| Input | Pipeline |
|-------|----------|
| Text-based PDF | Knowhere (`knowhere_queue`) |
| Scanned / image PDF | PixelRAG (`pixelrag_queue`) |
| Office / Markdown / CSV / … | Knowhere |
| Images / URLs / HTML | PixelRAG |

Override: filename prefix `knowhere:` / `pixelrag:`, or `settings.router.mode`.

### Multi-tenancy

`kb_name` flows into:

- PostgreSQL `documents.kb_name` (namespace-scoped via repositories)
- Celery kwargs on all downstream tasks
- Milvus scalar field on indexed chunks (inside the bound Milvus Database)

Dedup key: `(sha256, kb_name, plugin_namespace)` — identical file bytes may coexist in `finance` and `pharma`, or across domains on separate instances.

### Idempotency

Re-uploading the same file to the same KB returns `dedup_hit: true` without re-indexing. Different KB → new document row.

---

## `GET /ingest/queue-metrics`

Returns `IngestQueueMetricsResponse`:

```json
{
  "queues": [
    { "name": "router_queue", "concurrency": 4, "size": 2 },
    { "name": "knowhere_queue", "concurrency": 8, "size": 0 },
    { "name": "pixelrag_queue", "concurrency": 1, "size": 5 }
  ]
}
```

| Field | Source |
|-------|--------|
| `concurrency` | `settings.celery.queues.*.concurrency` (static) |
| `size` | Redis `LLEN` on queue name; `null` if broker unreachable |

Always HTTP **200** — partial data is acceptable for dashboard display.

---

## Celery queue topology

```mermaid
flowchart LR
  ING["POST /ingest"] --> RQ["router_queue (4)"]
  RQ --> KQ["knowhere_queue (8)"]
  RQ --> PQ["pixelrag_queue (1)"]
  KQ --> MV[(Milvus eagle_text)]
  PQ --> MV2[(Milvus eagle_visual)]
```

`pixelrag_queue` concurrency **1** — visual encoder is GPU/memory bound.

---

## Error codes (ingest path)

| Situation | HTTP | `detail` pattern |
|-----------|------|------------------|
| Empty multipart | 422 | `Either file or url is required` |
| Unregistered KB | 404 | `knowledge base not registered` / localized variant |
| SSRF blocked URL | 422 | Structured URL validation |
| Runner `ValueError` | 422 | Message string |
| Unexpected exception | 500 | `{"detail": "…"}` |

---

## MCP parity

The MCP `core_ingest` tool accepts `source_uri` (file path or URL) and calls `runner.ingest` directly. Returns `{ job_id, status, document_id, dedup_hit }` or `{ error: "…" }`. See [MCP tools](mcp-tools.md).

---

## Frontend integration

The ingest console (`/ingest`) uses:

- `POST /ingest` via `useIngest` hook
- `GET /tasks` with filters + SSE `GET /tasks/{id}/stream`
- `GET /ingest/queue-metrics` for `QueueCard` components

See [Ingest module](../frontend/ingest-module.md).

---

## Related documentation

- [Tasks](tasks.md) — audit list, SSE progress, retry
- [Documents](documents.md) — post-ingest corpus API
- [Knowledge bases](knowledge-bases.md) — register KB before ingest
- [Task queue (backend)](../backend/task-queue.md)
