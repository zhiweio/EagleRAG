# Database

Eagle-RAG uses **PostgreSQL** for metadata, audit trails, sessions, and operational data. Schema is managed by **Alembic** migrations over **SQLModel** table definitions. Vector data lives in Milvus — PostgreSQL is the system of record for document lifecycle and user-facing state.

**Source modules:** `eagle_rag/db/models/`, `alembic/versions/`

---

## 1. Theoretical background

### 1.1 Dual-store architecture in RAG

Modern RAG systems split storage by access pattern (Gao et al., arXiv:2312.10997):

| Store | Data | Query pattern |
|-------|------|--------------|
| **Vector DB** (Milvus) | Embeddings + chunk text | ANN similarity search |
| **Relational DB** (PostgreSQL) | Metadata, audit, sessions | CRUD, joins, transactions |

This separation allows independent scaling: Milvus for billion-vector search, PostgreSQL for transactional consistency.

### 1.2 Multi-tenancy via composite keys

Dedup uses `(sha256, kb_name)` as composite primary key — the same file content can exist in multiple knowledge bases without collision. This follows the **shared database, shared schema, tenant discriminator** pattern.

### 1.3 Event sourcing for task audit

The `task_audit` table acts as an **append-friendly audit log** for ingest jobs — recording state transitions, progress, and error messages for observability without querying Celery internals.

---

## 2. Entity-relationship overview

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

## 3. Core tables

### 3.1 `knowledge_bases`

| Column | Type | Notes |
|--------|------|-------|
| `name` | VARCHAR PK | Tenant identifier (`finance`, `pharma`, …) |
| `display_name` | VARCHAR | UI label |
| `description` | TEXT | Optional |
| `pdf_text_page_ratio` | FLOAT | Per-KB PDF probe override |
| `created_at` | TIMESTAMP | |

### 3.2 `documents`

| Column | Type | Notes |
|--------|------|-------|
| `document_id` | UUID PK | |
| `name` | VARCHAR | Filename |
| `source_type` | VARCHAR | policy/financial/… |
| `pipeline` | VARCHAR | knowhere/pixelrag/pending |
| `kb_name` | VARCHAR FK | Tenant key |
| `source_uri` | VARCHAR | Original path/URL |
| `sha256` | VARCHAR | Content hash |
| `status` | VARCHAR | pending/indexing/ready |
| `chunk_count` | INT | Indexed node count |
| `extra` | JSONB | doc_nav tree, misc |
| `created_at` | TIMESTAMP | |

### 3.3 `dedup`

| Column | Type | Notes |
|--------|------|-------|
| `sha256` | VARCHAR | Content hash |
| `kb_name` | VARCHAR | Tenant key |
| `document_id` | UUID FK | Points to existing doc |
| PK | `(sha256, kb_name)` | Composite |

Registered only after successful parse — failed ingests don't block re-upload.

### 3.4 `document_keywords`

Tag catalog for scope filtering:

| Column | Type | Notes |
|--------|------|-------|
| `document_id` | UUID | |
| `kb_name` | VARCHAR | |
| `keyword` | VARCHAR | From Knowhere chunk keywords |
| `count` | INT | Occurrence count |

Queried by `GET /tags` and `resolve_tags_to_document_ids()` at query time.

### 3.5 `task_audit`

| Column | Type | Notes |
|--------|------|-------|
| `job_id` | UUID PK | Celery task ID |
| `document_id` | UUID | |
| `pipeline` | VARCHAR | router/knowhere/pixelrag |
| `kb_name` | VARCHAR | |
| `state` | VARCHAR | PENDING/RENDERING/…/SUCCESS/FAILED |
| `progress` | INT | 0-100 |
| `current` / `total` | INT | Progress counters |
| `error` | TEXT | Last error message |
| `log` | JSONB | Append-only log entries |
| `name` | VARCHAR | Filename |
| `source_uri` | VARCHAR | |

### 3.6 `sessions` / `session_messages`

Chat session persistence:

| Table | Key fields |
|-------|-----------|
| `sessions` | session_id, user_id, title, scope_filter (JSONB), kb_name |
| `session_messages` | message_id, session_id, role, content, sources (JSONB), steps (JSONB) |

`scope_filter` persisted so follow-up queries inherit KB/doc/tag scope.

### 3.7 `images`

Visual tile metadata (complement to Milvus vectors):

| Column | Type | Notes |
|--------|------|-------|
| `image_id` | VARCHAR PK | |
| `document_id` | UUID | |
| `object_key` | VARCHAR | MinIO path |
| `kb_name` | VARCHAR | |
| `page`, `position` | INT/VARCHAR | Tile location |
| `width`, `height` | INT | Dimensions |

### 3.8 `attachments`

Session-scoped temporary uploads:

| Column | Type | Notes |
|--------|------|-------|
| `attachment_id` | UUID PK | |
| `session_id` | UUID | |
| `filename` | VARCHAR | |
| `object_key` | VARCHAR | MinIO |
| `expires_at` | TIMESTAMP | TTL from `attachments.ttl_hours` |

### 3.9 Operational tables

| Table | Purpose |
|-------|---------|
| `notifications` | User notifications (ingest complete, errors) |
| `mcp_call_log` | MCP tool invocation audit |
| `metric_samples` | Queue depth time series |
| `system_settings` | Runtime-configurable overrides |

---

## 4. Migration workflow

```bash
# Generate migration after model change
alembic revision --autogenerate -m "describe change"

# Apply
task db:migrate
# or: alembic upgrade head
```

**Convention:**

- Models in `eagle_rag/db/models/` — one file per domain.
- `alembic/env.py` normalizes DSN: `postgresql+asyncpg://` → `postgresql+psycopg2://` for migrations.
- No DDL in store modules — all schema changes via Alembic.

---

## 5. Milvus relationship

PostgreSQL holds pointers; Milvus holds searchable vectors:

| PostgreSQL | Milvus filter |
|-----------|--------------|
| `documents.document_id` | `document_id == "..."` |
| `documents.kb_name` | `kb_name == "..."` |
| `documents.source_type` | `source_type == "..."` |
| `document_keywords.keyword` | Resolved to `document_id in [...]` |

KB deletion (`kb/lifecycle.py`) cascades: PostgreSQL rows → Milvus `delete_*_by_kb()` → MinIO prefix cleanup.

---

## 6. LlamaIndex integration

PostgreSQL stores document registry metadata that LlamaIndex `TextNode.metadata` mirrors:

| PG field | TextNode metadata |
|----------|------------------|
| `document_id` | `metadata.document_id` |
| `source_type` | `metadata.source_type` |
| `kb_name` | `metadata.kb_name` |
| `extra.doc_nav` | Served via structure API (not in Milvus) |

LlamaIndex docstore may cache nodes locally, but authoritative metadata is in Milvus dynamic fields + PostgreSQL registry.

---

## 7. Design tensions and tuning

| Tension | Schema / store | Consequence | Practice |
| --- | --- | --- | --- |
| **JSONB scope without DB constraint** | `sessions.scope_filter` | Stale doc IDs after delete — queries return empty, not error | Refresh scope client-side after KB purge |
| **Dual driver consistency** | asyncpg (API) vs psycopg2 (workers) | Same row updated from both paths — no distributed transaction with Milvus | Treat Postgres as source of truth for lifecycle; Milvus eventual |
| **CASCADE vs vector purge** | FK `document_keywords` ON DELETE CASCADE | SQL clean; Milvus vectors need explicit `delete_*` in lifecycle | Always use KB purge API, not raw SQL delete |
| **Alembic vs runtime** | Models in `eagle_rag/db/models/` | Drift if migration not run before deploy | `task db:migrate` in release pipeline |
| **Task audit growth** | `task_state` append-only logs | Large JSONB log arrays slow admin UI | Archive old audits periodically |
| **Message history unbounded** | `messages` per session | Long chats increase load on session restore | Client-side pagination; future retention policy |

---

## 8. Config & tuning

```yaml
postgres:
  dsn: postgresql://eagle:eagle@localhost:5432/eagle_rag
```

**Environment:**

```
POSTGRES_DSN=postgresql://user:pass@host:5432/eagle_rag
```

Async routes use `postgresql+asyncpg://` variant internally.

---

## 9. Tests

| Test file | Coverage |
|-----------|----------|
| `tests/test_api_query_sessions_documents_tasks.py` | Session CRUD |
| `tests/test_api_kb_attachments_notifications_users.py` | KB registry, attachments |
| `tests/test_api_admin_health.py` | DB connectivity in health |

---

## 10. References

- SQLModel: [sqlmodel.tiangolo.com](https://sqlmodel.tiangolo.com/)
- Alembic: [alembic.sqlalchemy.org](https://alembic.sqlalchemy.org/)
- Gao et al., *RAG Survey*, [arXiv:2312.10997](https://arxiv.org/abs/2312.10997)
- Multi-tenant data architecture: [docs.aws.amazon.com/wellarchitected/latest/saas-lens](https://docs.aws.amazon.com/wellarchitected/latest/saas-lens/saas-lens.html)
