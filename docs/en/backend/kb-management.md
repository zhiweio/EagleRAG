# Knowledge base management

Knowledge bases (`kb_name`) are the multi-tenancy unit in Eagle-RAG. Each KB isolates documents, Milvus vectors, dedup records, and object storage prefixes. The KB module provides registry, lifecycle (create/delete/rebuild), statistics, and health monitoring.

**Source modules:** `eagle_rag/kb/registry.py`, `eagle_rag/kb/lifecycle.py`, `eagle_rag/kb/stats.py`, `eagle_rag/kb/health.py`, `eagle_rag/api/knowledge_bases.py`

---

## 1. Theoretical background

### 1.1 Multi-tenant RAG

Industry-agnostic RAG platforms serve multiple isolated knowledge domains (finance, pharma, patent, …) from a single deployment. **Logical isolation** via a tenant discriminator (`kb_name`) on every table and Milvus scalar filter is more cost-effective than per-tenant infrastructure (AWS SaaS Lens: tenant isolation patterns).

### 1.2 Capacity planning

Vector stores have practical entity limits per collection. Eagle-RAG tracks text/visual entity counts against configurable limits (`kb.text_entity_limit`, `kb.visual_entity_limit`) to prevent unbounded growth.

### 1.3 Index rebuild without re-parse

When the embedding model changes, text vectors can be **reindexed** from existing Milvus text/metadata without re-running Knowhere parse — a significant cost saving for large corpora.

---

## 2. KB registry

**Module:** `eagle_rag/kb/registry.py`

| Function | Context | Purpose |
|----------|---------|---------|
| `kb_exists_sync(kb_name)` | Sync (ingest) | Validate before dispatch |
| `get_kb(kb_name)` | Async (API) | Fetch KB metadata |
| `list_kbs()` | Async | List all KBs |
| `create_kb(name, ...)` | Async | Register new KB |
| `get_pdf_ratio_sync(kb_name)` | Sync (router) | Per-KB PDF probe threshold |

Each KB can override `pdf_text_page_ratio` — allowing finance KBs to prefer Knowhere for mixed PDFs while patent KBs route more to PixelRAG.

### API endpoints

| Method | Path | Action |
|--------|------|--------|
| GET | `/knowledge-bases` | List KBs with stats |
| POST | `/knowledge-bases` | Create KB |
| GET | `/knowledge-bases/{name}` | KB detail |
| DELETE | `/knowledge-bases/{name}` | Cascade delete |
| POST | `/knowledge-bases/{name}/rebuild` | Reindex text vectors |

---

## 3. Lifecycle operations

**Module:** `eagle_rag/kb/lifecycle.py`

### 3.1 Cascade delete

```
1. delete_text_by_kb(kb_name)     → Milvus eagle_text
2. delete_visual_by_kb(kb_name)  → Milvus eagle_visual
3. delete MinIO prefix            → object storage
4. DELETE documents, dedup, keywords, images (PostgreSQL)
5. DELETE knowledge_bases row
```

Celery task: runs on `knowhere_queue` for long-running cleanup.

### 3.2 Text reindex

```
1. fetch_text_nodes_by_kb(kb_name)  → read existing text + metadata
2. delete_text_by_kb(kb_name)       → remove old vectors
3. Rebuild TextNodes with current embed_model
4. upsert_text_nodes()              → write fresh vectors
```

Visual reindex requires full re-ingest (render + embed is not reversible from Milvus scalars alone).

---

## 4. Statistics

**Module:** `eagle_rag/kb/stats.py`

Aggregates per KB:

| Metric | Source |
|--------|--------|
| `document_count` | PostgreSQL `documents` |
| `text_entity_count` | Milvus `count_text(kb_name)` |
| `visual_entity_count` | Milvus `count_visual(kb_name)` |
| `ready_count` / `pending_count` | PostgreSQL status filter |
| `format_distribution` | Extension histogram |

Compared against limits from `settings.kb`:

```yaml
kb:
  text_entity_limit: 500000
  visual_entity_limit: 200000
```

---

## 5. Health monitoring

**Module:** `eagle_rag/kb/health.py`

Per-KB health status:

| Check | Healthy when |
|-------|-------------|
| Milvus text reachable | `count_text()` succeeds |
| Milvus visual reachable | `count_visual()` succeeds |
| Entity ratio | count < 90% of limit |
| Pending documents | No docs stuck in `pending` > threshold |

Surfaced in admin dashboard and `GET /knowledge-bases/{name}`.

---

## 6. Milvus filter expressions

All KB operations use the tenant scalar:

```
kb_name == "finance"
```

Delete operations:

```python
client.delete(collection, filter='kb_name == "finance"')
```

Count operations:

```python
client.query(collection, filter='kb_name == "finance"', output_fields=["count(*)"])
```

---

## 7. LlamaIndex integration

Reindex rebuilds `TextNode` objects from Milvus-fetched data:

```python
node = TextNode(text=row["text"], id_=row["id"])
node.metadata = row["metadata"]  # preserves path, connect_to, etc.
index.insert_nodes([node])         # re-embeds with current model
```

Metadata preservation ensures graph expansion (`connect_to`) and parent-document (`path`) retrieval continue working after reindex.

---

## 8. Design tensions and tuning

| Tension | Operation | Risk | Mitigation |
| --- | --- | --- | --- |
| **Purge ordering** | Milvus delete expr then Postgres | Partial failure → orphaned vectors or missing registry | Run purge via API; verify counts after |
| **Rebuild storm** | Re-queue all documents | Spikes `knowhere_queue` / `pixelrag_queue` | Rate-limit rebuild; scale workers temporarily |
| **Entity limit warnings** | `kb.text_entity_limit` / `visual_entity_limit` | Soft threshold only — ingest continues | Hard governance requires external quotas |
| **PDF ratio per KB** | `get_pdf_ratio_sync` | Global default wrong for scan-heavy KB | Set per-KB ratio in registry metadata |
| **Immutable kb_name** | Registry constraint | Display rename needs new KB + migration | Plan tenant IDs as stable slugs |
| **Stats lag** | `kb/stats.py` counts Milvus + SQL | Immediately after purge, caches may be stale | Refresh stats endpoint after lifecycle ops |

---

## 9. Config & tuning

```yaml
kb_name: default              # fallback tenant

kb:
  text_entity_limit: 500000
  visual_entity_limit: 200000
```

Per-KB PDF probe override stored in `knowledge_bases.pdf_text_page_ratio`.

---

## 10. Tests

| Test file | Coverage |
|-----------|----------|
| `tests/test_api_kb_attachments_notifications_users.py` | KB CRUD |
| `tests/test_api_admin_health.py` | KB health in admin |

---

## 11. Ingest validation gate

Before any ingest dispatch, `runner.ingest()` validates KB existence:

```python
from eagle_rag.kb.registry import kb_exists_sync
if not kb_exists_sync(kb):
    raise ValueError(f"知识库未注册: {kb}")
```

MCP `ingest` tool and `POST /ingest` both propagate this error. Prevents orphan vectors in Milvus without a registry row.

---

## 12. Multi-KB query patterns

A single query can span multiple KBs via `scope_filter.kb_names`:

```json
{"scope_filter": {"kb_names": ["finance", "pharma"], "tags": ["2025"]}}
```

Milvus expression:

```
(kb_name in ["finance", "pharma"] or document_id in [tag-resolved ids])
```

Default single-KB queries use `QueryRequest.kb_name` → `kb_name == "{value}"`.

---

## 13. Capacity alerts

When `text_entity_count > 0.9 * text_entity_limit`, KB health returns `warning`. At 100%, ingest should be blocked (enforced at API layer via stats check before upload). Visual limits follow the same pattern for `eagle_visual` entity counts.

---

## 14. References

- Milvus delete by filter: [milvus.io/docs/delete_entities.md](https://milvus.io/docs/delete_entities.md)
- Milvus count: [milvus.io/docs/get_collection_stats.md](https://milvus.io/docs/get_collection_stats.md)
- Gao et al., *RAG Survey*, [arXiv:2312.10997](https://arxiv.org/abs/2312.10997)
- Multi-tenancy in Eagle-RAG: [multi-tenancy](../architecture/multi-tenancy.md)
