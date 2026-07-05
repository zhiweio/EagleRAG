# Knowledge Base Module

Tenant management UI at `/kb` and `/kb/[kbName]`. Components live in `components/kb/`.

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

`KBDetailClient.tsx` — deep dive for one namespace.

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

`GET …/collections` — row counts for `eagle_text` / `eagle_visual`.

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

Re-exports / narrows generated OpenAPI types for KB domain.

---

## Multi-tenancy UX notes

- `kb_name` in URL is the canonical identifier (lowercase + underscores)
- Ingest page uses `TargetKBSelector` — separate from QA `scopeStore`
- QA scope drawer can select **multiple** KBs via `scope_filter.kb_names[]`

---

## Related documentation

- [Knowledge bases API](../api/knowledge-bases.md)
- [Documents API](../api/documents.md)
- [Design system](design-system.md) — theme swatches
