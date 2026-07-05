# Knowledge Bases API

Multi-tenant namespaces are managed under **`/knowledge_bases`**. Each `kb_name` isolates documents, Milvus scalar filters, Celery kwargs, and console theme metadata.

Implementation: `eagle_rag/api/knowledge_bases.py`, schemas in `eagle_rag/api/schemas/knowledge_bases.py`.

---

## Naming rules

`kb_name` must match `registry.KB_NAME_PATTERN`:

```
^[a-z][a-z0-9_]*$
```

Lowercase letters, digits, underscores only. **422** on violation.

---

## `GET /knowledge_bases`

List registered KBs with live stats.

| Query | Default | Description |
|-------|---------|-------------|
| `query` | — | Search display name / kb_name |
| `sort` | `recent` | `recent \| name \| size` |
| `limit` | 50 | 1–200 |
| `offset` | 0 | Pagination |

### `KBItem` fields

| Field | Description |
|-------|-------------|
| `kb_name` | Identifier |
| `display_name` | UI label |
| `description` | Optional blurb |
| `theme` | Colour token (`blue`, `violet`, …) |
| `icon` | Lucide icon key |
| `pdf_text_page_ratio` | PDF form-probe threshold (0–1) |
| `documents` | Ready document count |
| `graph_nodes` | Text collection entities |
| `visual_slices` | Visual tile count |
| `collections` | Milvus collection names |
| `active_ingestions` | In-flight tasks |
| `updated_at` | ISO timestamp |

---

## `GET /knowledge_bases/overview`

Cross-KB aggregate `KBOverviewResponse` — dashboard KPIs for `/kb` landing page.

---

## `POST /knowledge_bases`

Create namespace. Body — `KBCreate`:

```json
{
  "kb_name": "pharma",
  "display_name": "Pharma R&D",
  "description": "Clinical and regulatory corpus",
  "theme": "emerald",
  "icon": "flask",
  "pdf_text_page_ratio": 0.25
}
```

| HTTP | Condition |
|------|-----------|
| `201` | Created |
| `409` | `kb_name already exists` |
| `422` | Invalid name or validation error |
| `503` | Registry / DB failure |

---

## `GET /knowledge_bases/{kb_name}`

`KBDetailOut` = `KBItem` + `status` + `kpi`:

```json
{
  "status": "healthy",
  "kpi": {
    "documents": 120,
    "graph_nodes": 45000,
    "visual_slices": 8000,
    "queries_7d": 340
  }
}
```

`status` from `health.compute_kb_status` (`healthy`, `degraded`, …). **404** if KB missing.

---

## Analytics sub-routes

| Path | Response | Purpose |
|------|----------|---------|
| `GET …/format-distribution` | `KBFormatDistributionResponse` | File type breakdown |
| `GET …/ingestion-volume?days=7` | `KBIngestionVolumeResponse` | Time-series ingest (1–90 days) |
| `GET …/collections` | `KBCollectionsResponse` | Milvus collection stats |
| `GET …/facets` | `KBFacetsResponse` | `source_type`, `year`, pipeline facets |

All require existing KB — else **404**.

---

## `PATCH /knowledge_bases/{kb_name}`

Partial update via `KBUpdate` (display_name, description, theme, icon, pdf_text_page_ratio). **404** if missing.

---

## `DELETE /knowledge_bases/{kb_name}`

`KBDeleteResponse`:

```json
{
  "kb_name": "pharma",
  "deleted": {
    "documents": 120,
    "milvus_text": 45000,
    "milvus_visual": 8000,
    "minio_objects": 240
  }
}
```

Calls `lifecycle.delete_kb_namespace` — destructive, async-heavy. **404** if KB not found.

!!! danger "Irreversible"
    Purge removes registry rows, Milvus entities, and stored objects for the namespace. Take backups before deleting production KBs.

---

## `POST /knowledge_bases/{kb_name}/rebuild`

Triggers full re-index job. `RebuildResponse`:

```json
{ "job_id": "rebuild-uuid" }
```

Track via `/tasks`. **404** if KB missing.

---

## Multi-tenancy integration

| Consumer | How `kb_name` is passed |
|----------|------------------------|
| `POST /ingest` | Form field |
| `POST /query` | Body field or `scope_filter.kb_names[]` |
| `GET /documents` | Query filter |
| `GET /tasks` | Query filter |
| MCP tools | Optional parameter, defaults to `settings.kb_name` |
| Frontend KB picker | `useKBStore` on ingest; scope drawer on QA |

Default KB: `default` (`KB_NAME` env).

---

## Frontend integration

| Route | Components |
|-------|------------|
| `/kb` | `KBManagementClient`, ghost cards, overview charts |
| `/kb/[kbName]` | `KBDetailClient`, Milvus cards, purge/rebuild modals |

See [KB module](../frontend/kb-module.md).

---

## Related documentation

- [Multi-tenancy](../architecture/multi-tenancy.md)
- [Ingest](ingest.md) — requires registered KB
- [Database](../backend/database.md) — `knowledge_bases` table
