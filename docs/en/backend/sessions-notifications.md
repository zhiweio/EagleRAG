# Sessions and notifications

Chat sessions persist query history, scope filters, and message metadata (sources, steps) in PostgreSQL. Notifications alert users when ingest tasks reach terminal states. Both modules use async database access in FastAPI handlers.

**Source modules:** `eagle_rag/sessions/store.py`, `eagle_rag/notifications/store.py`, `eagle_rag/api/query.py`, `eagle_rag/api/notifications.py`

---

## 1. Theoretical background

### 1.1 Conversational RAG

Multi-turn RAG requires **session state** to maintain context across queries (Gao et al., arXiv:2312.10997). Eagle-RAG persists:

- Message history (user + assistant)
- Retrieval scope (`scope_filter`) for follow-up queries
- Execution traces (`steps`) for transparency

Unlike memory-augmented agents (MemGPT, Packer et al., arXiv:2310.08560), Eagle-RAG stores explicit message records rather than learned memory compression — simpler and auditable.

### 1.2 Scope persistence

`ScopeSelection` (kb_names, document_ids, tags) stored on the session ensures follow-up queries inherit the same Milvus filter constraints without re-selection:

```
(kb_name in ["finance"] or document_id in ["doc-1", "doc-2"])
```

---

## 2. Session model

**PostgreSQL tables:** `sessions`, `session_messages`

### 2.1 Session fields

| Field | Type | Purpose |
|-------|------|---------|
| `session_id` | UUID PK | |
| `user_id` | UUID FK | Owner |
| `title` | VARCHAR | Auto-generated or user-set |
| `kb_name` | VARCHAR | Default tenant |
| `scope_filter` | JSONB | Persisted ScopeSelection |
| `created_at` / `updated_at` | TIMESTAMP | |

### 2.2 Message fields

| Field | Type | Purpose |
|-------|------|---------|
| `message_id` | UUID PK | |
| `session_id` | UUID FK | |
| `role` | VARCHAR | user / assistant |
| `content` | TEXT | Message body |
| `sources` | JSONB | `{text: [...], image: [...]}` |
| `steps` | JSONB | Route/recall/rerank/generate trace |
| `route` | JSONB | RouteDecision snapshot |
| `created_at` | TIMESTAMP | |

---

## 3. Code walkthrough: session store

**Module:** `eagle_rag/sessions/store.py`

| Function | Purpose |
|----------|---------|
| `create_session(user_id, kb_name, scope_filter)` | New session |
| `get_session(session_id)` | Fetch with messages |
| `list_sessions(user_id)` | User's session list |
| `add_message(session_id, role, content, ...)` | Append message |
| `update_session_title(session_id, title)` | Rename |
| `delete_session(session_id)` | Remove session + messages |

### Query integration

`POST /query/stream` with `session_id`:

1. Create/load session.
2. Persist user message before streaming.
3. Stream SSE events from router engine.
4. On `done` event, persist assistant message with full sources/steps.

```python
# SSE flow in api/query.py
yield {"event": "session", "data": {"session_id": ..., "user_message_id": ...}}
# ... route, recall, rerank, token events ...
# On done: sessions.store.add_message(role="assistant", sources=..., steps=...)
```

---

## 4. Notifications

**Module:** `eagle_rag/notifications/store.py`

### Trigger points

Notifications created when ingest tasks reach terminal states:

| Event | Notification |
|-------|-------------|
| Task SUCCESS | "Document {name} indexed successfully" |
| Task FAILED | "Document {name} failed: {error}" |

Written by task state transitions in `tasks/state.py` (best-effort, non-blocking).

### API

| Method | Path | Action |
|--------|------|--------|
| GET | `/notifications` | List user notifications |
| PUT | `/notifications/{id}/read` | Mark read |
| DELETE | `/notifications/{id}` | Dismiss |

---

## 5. Milvus scope inheritance

When a session has `scope_filter` persisted, subsequent queries merge it into retriever config:

```python
scope_filter = session.scope_filter or request.scope_filter
# → EagleRouterQueryEngine.retrieve(scope_filter=scope_filter)
# → MetadataFilters pushed to Milvus
```

Example inherited filter:

```
(kb_name in ["finance"] or document_id in ["doc-a", "doc-b"]) and source_type == "policy"
```

---

## 6. LlamaIndex integration

Session messages store the output of LlamaIndex-based pipeline stages:

| Stored field | LlamaIndex origin |
|-------------|------------------|
| `sources.text[].path` | TextNode metadata |
| `sources.image[].image_id` | ImageNode metadata |
| `steps[].text_top` | Post-rerank TextNode paths |
| `steps[].visual_top` | Post-rerank ImageNode IDs |

No LlamaIndex objects are persisted directly — only serialized DTOs.

---

## 7. Design tensions and tuning

| Tension | Field / flow | Effect | Practice |
| --- | --- | --- | --- |
| **Persisted scope drift** | `sessions.scope_filter` JSONB | Deleted documents still in scope → empty retrieval | Reconcile scope after KB admin actions |
| **Session kb_name vs query** | Session default + per-query override | Mixed if client sends conflicting `kb_name` | Treat per-query `kb_name` as authoritative |
| **Message replay size** | Full history loaded for context | Large sessions slow `GET /sessions/{id}` | Paginate messages in UI |
| **Notification fan-out** | Per-user rows on ingest complete | No back-pressure if ingest flood | Batch or throttle notification creation |
| **Scope inheritance** | Frontend restores scope to Zustand | Stale tags if keyword catalog changed | Refetch `/tags` after ingest |

---

## 8. Config & tuning

Sessions and notifications use the standard PostgreSQL DSN. No dedicated config section — TTL and limits are implicit (no session expiry by default).

---

## 9. Tests

| Test file | Coverage |
|-----------|----------|
| `tests/test_api_query_sessions_documents_tasks.py` | Session CRUD, message persistence, streaming |
| `tests/test_api_kb_attachments_notifications_users.py` | Notification list/read |

---

## 10. API endpoints

**Sessions** (`eagle_rag/api/query.py`):

| Method | Path | Action |
|--------|------|--------|
| POST | `/sessions` | Create session |
| GET | `/sessions` | List user sessions |
| GET | `/sessions/{id}` | Get session with messages |
| PATCH | `/sessions/{id}` | Update title / scope_filter |
| DELETE | `/sessions/{id}` | Delete session |

**Notifications** (`eagle_rag/api/notifications.py`):

| Method | Path | Action |
|--------|------|--------|
| GET | `/notifications` | List unread/read |
| PUT | `/notifications/{id}/read` | Mark read |
| DELETE | `/notifications/{id}` | Dismiss |

---

## 11. Attachment + session interaction

When a query includes `attachments: [attachment_id, ...]` alongside `session_id`:

1. Attachments are lazy-parsed (`attachments/parser.py`).
2. Parsed text nodes prepended to retrieval results with `score=1.0`.
3. Parsed images passed as `ImageDocument` to VLM.
4. Attachment parse step appears in `steps` trace.
5. Doc attachments trigger hybrid routing via `AttachmentSelector`.

Attachments are session-scoped and expire per `attachments.ttl_hours` — not persisted in Milvus.

---

## 12. LlamaIndex query path through sessions

```
POST /query/stream {query, session_id, scope_filter}
  → sessions.store.load(session_id)
  → merge session.scope_filter with request scope_filter
  → EagleRouterQueryEngine.query_stream(...)
  → EagleMultimodalQueryEngine.stream_custom_query(...)
  → on done: sessions.store.add_message(assistant, sources, steps)
```

The session store is a thin PostgreSQL wrapper — no LlamaIndex memory module. Full retrieval context is re-fetched per query (stateless retrieval, stateful scope).

---

## 13. References

- Gao et al., *RAG Survey*, [arXiv:2312.10997](https://arxiv.org/abs/2312.10997)
- Packer et al., *MemGPT*, [arXiv:2310.08560](https://arxiv.org/abs/2310.08560)
- FastAPI SSE: [fastapi.tiangolo.com/advanced/custom-response](https://fastapi.tiangolo.com/advanced/custom-response/)
- LlamaIndex chat engines: [docs.llamaindex.ai/en/stable/module_guides/deploying/chat_engines](https://docs.llamaindex.ai/en/stable/module_guides/deploying/chat_engines/)
