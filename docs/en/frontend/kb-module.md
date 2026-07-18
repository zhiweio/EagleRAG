# Knowledge Base Module

Knowledge-base management UI at `/kb` and `/kb/[kbName]`. Components live in `components/kb/`.

!!! note "Terminology"
    - **Domain** (`plugin_namespace`) — deploy-time binding shown read-only in the AppBar. Not selectable in this UI.
    - **Knowledge base** (`kb_name`) — what this module creates, lists, and opens. Scalar filter inside the domain Milvus Database.
    - Do **not** call a KB a “namespace” or “tenant namespace” in UI copy.

See [Multi-tenancy](../architecture/multi-tenancy.md).

---

## List page (`/kb`)

`KBManagementClient.tsx` orchestrates:

| Component | Role |
|-----------|------|
| `KBGhostCard` | Create-KB placeholder card |
| `CreateKBDrawer` | `POST /knowledge_bases` form |
| `KBToast` | Success/error feedback |
| Overview charts | `GET /knowledge_bases/overview` |

### KB cards

Each card shows `KBItem` stats: documents, graph nodes, visual slices, active ingestions, theme swatch (`ThemeSwatchPicker` pattern).

Navigation → `/kb/{kb_name}`.

### Hooks

`useKnowledgeBases`, `useKBOverview` in `lib/hooks/useKB.ts`.

Query keys:

```
["knowledge-bases", params]
["knowledge-bases", "overview"]
```

---

## Detail page (`/kb/[kbName]`)

`KBDetailClient.tsx` — deep dive for one knowledge base.

### KPI header

`GET /knowledge_bases/{kb_name}` → `KBDetailOut`:

- `status` badge (`healthy` / `degraded`)
- `kpi.documents`, `graph_nodes`, `visual_slices`, `queries_7d`

### Charts (`kb-charts.tsx`)

| Chart | Endpoint |
|-------|----------|
| Format distribution | `GET …/format-distribution` |
| Ingestion volume | `GET …/ingestion-volume?days=7` |

Recharts bar/area charts with theme colours from KB `theme` token.

### Milvus panel (`MilvusCollectionCard.tsx`)

`GET …/collections` — row counts for base `eagle_text` / `eagle_visual` (and specialized collections when the domain plugin provides them).

### Facets

`GET …/facets` — drives filter chips for document lists when embedded.

### Destructive actions

| Modal | API |
|-------|-----|
| `PurgeConfirmModal` | `DELETE /knowledge_bases/{kb_name}` |
| `RebuildConfirmModal` | `POST …/rebuild` |
| `DocumentDeleteModal` | `DELETE /documents/{id}` |

### Edit metadata

`EditKBDrawer` → `PATCH /knowledge_bases/{kb_name}`.

---

## Visual system (`kb-visuals.tsx`)

Maps `theme` + `icon` fields to Tailwind colour classes and Lucide icons — consistent card identity across list and detail.

---

## Types (`lib/kb/types.ts`)

Re-exports / narrows generated OpenAPI types for the knowledge-base module.

---

## Isolation UX notes

- `kb_name` in the URL is the canonical KB identifier (lowercase + underscores)
- AppBar shows the deploy **domain** (`NEXT_PUBLIC_PLUGIN_NAMESPACE`); users switch **KBs**, not domains
- Ingest page uses `TargetKBSelector` — separate from QA `scopeStore`
- QA scope drawer can select **multiple** KBs via `scope_filter.kb_names[]`
- i18n: prefer “knowledge base” / “知识库”; never “namespace” / “命名空间” for `kb_name`

---

## Related documentation

- [Frontend index](index.md)
- [Ingest module](ingest-module.md)
- [State management](state-management.md)
- [Multi-tenancy](../architecture/multi-tenancy.md)
