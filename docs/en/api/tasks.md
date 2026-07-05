# Tasks API

Celery job audit records are exposed under **`/tasks`**. Each ingest dispatch creates a `task_audit` row tracked through pipeline stages until `success` or `failed`.

Implementation: `eagle_rag/api/ingest.py` (task routes share the ingest router tag).

---

## `GET /tasks`

List task audit records with filtering and pagination.

### Query parameters

| Param | Type | Description |
|-------|------|-------------|
| `pipeline` | `string` | Filter: `router`, `knowhere`, `pixelrag`, or compound |
| `status` | `string` | Raw backend status (`pending`, `rendering`, `success`, …) |
| `q` | `string` | Fuzzy match on `job_id` or `document_id` |
| `kb_name` | `string` | Multi-tenant filter |
| `limit` | `int` | 1–500, default 50 |
| `offset` | `int` | ≥ 0 |

### Response — `TaskListResponse`

```json
{
  "items": [
    {
      "job_id": "abc-123",
      "document_id": "doc_xyz",
      "name": "report.pdf",
      "source_uri": "kb/finance/report.pdf",
      "pipeline": "knowhere",
      "status": "embedding",
      "status_phase": "running",
      "progress": 65,
      "current": 13,
      "total": 20,
      "error": null,
      "logs": [],
      "created_at": "2025-07-05T01:00:00Z",
      "updated_at": "2025-07-05T01:02:00Z",
      "kb_name": "finance"
    }
  ],
  "limit": 50,
  "offset": 0,
  "error": null
}
```

### `status` vs `status_phase`

| `status` (raw) | `status_phase` (normalized) |
|----------------|----------------------------|
| `pending`, `queued` | `pending` |
| `rendering`, `embedding`, `indexing`, `processing`, `parsing`, `retrying` | `running` |
| `success`, `done`, `ready` | `success` |
| `failed`, `error` | `failed` |

The frontend `status.ts` maps `status_phase` to pill colours — keep new backend statuses mapped in `_STATUS_PHASE_MAP` (`schemas/ingest.py`).

### Degraded mode

Database failure → HTTP **200** with `items: []` and `error: "database unavailable"`. UI should surface the hint.

---

## `GET /tasks/{job_id}`

Single `TaskAuditOut`. **404** if not found. **503** if database down.

---

## `GET /tasks/{job_id}/stream` (SSE)

Live progress subscription for one job.

### Events

| Event | Payload |
|-------|---------|
| `progress` | Full audit dict (same shape as `TaskAuditOut` source row) |
| `timeout` | `{ job_id, reason: "no change timeout", seconds }` |

### Behaviour

- Poll interval: **1.5 s** (`_SSE_POLL_INTERVAL`)
- Emits `progress` on every poll while status ∉ `{success, failed}`
- **Terminal:** stream closes after `success` or `failed` progress event
- **Timeout:** no `updated_at` change for **300 s** → `timeout` event then close

### Wire example

```
event: progress\r\n
data: {"job_id":"…","status":"embedding","progress":40,…}\r\n
\r\n
```

No `token` or `step` events — task SSE is audit-snapshot only.

### Frontend consumer

`frontend/lib/api/sse.ts` → `streamTaskProgress(jobId, onEvent)` using generated `streamTaskTasksJobIdStreamGet`.

---

## `GET /tasks/{job_id}/logs`

Returns `TaskLogsResponse`:

```json
{ "job_id": "abc-123", "logs": [ { "ts": "…", "level": "info", "message": "…" } ] }
```

`TaskLogEntry` allows extra JSONB keys (`ConfigDict(extra="allow")`).

---

## `POST /tasks/{job_id}/retry`

Re-dispatch a failed task to its original Celery queue.

### Pipeline → queue mapping

| `pipeline` key | Celery task | Queue |
|----------------|-------------|-------|
| `router` | `eagle_rag.ingest.router.ingest_router` | `router_queue` |
| `knowhere` | `eagle_rag.tasks.knowhere_parse` | `knowhere_queue` |
| `pixelrag` | `eagle_rag.tasks.pixelrag_build` | `pixelrag_queue` |

### Recovery logic

1. Load audit + document registry row
2. Restore `object_key` / `source_uri` / `source_type_hint` from `documents` table
3. `local_path` intentionally **null** (temp file gone)
4. Reset audit to `PENDING` **before** `send_task` (race avoidance)

### Response — `TaskRetryResponse`

```json
{ "job_id": "abc-123", "status": "pending", "retried": true }
```

| HTTP | Condition |
|------|-----------|
| `200` | Dispatched |
| `404` | Unknown job |
| `502` | `send_task` failure |
| `503` | Database unavailable |

**Idempotency:** Each retry creates a new execution attempt on the same `job_id` row (status reset). Not safe to spam — may duplicate Milvus writes if prior partial index exists.

---

## `DELETE /tasks/{job_id}`

Deletes audit record only (does **not** delete indexed document). **404** if missing.

---

## Multi-tenancy

`kb_name` on each audit row; filter list with `?kb_name=finance`. Retry passes `kb_name` in Celery kwargs.

---

## Related documentation

- [Ingest](ingest.md) — dispatch entry point
- [Documents](documents.md) — `document_id` lifecycle
- [Task queue (backend)](../backend/task-queue.md) — worker configuration
