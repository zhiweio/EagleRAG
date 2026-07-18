# Health & Admin API

Operations probes and dashboards for the `/health` console page. Two routers in `eagle_rag/api/health.py`:

| Router | Prefix | Tag |
|--------|--------|-----|
| `router` | `/health`, `/health/plugins`, `/mcp/tools` | `health` |
| `admin_router` | `/admin` | `admin` |

Probe timeout: **3 s** per dependency (`_PROBE_TIMEOUT`). All probes are read-only.

---

## `GET /health`

`HealthResponse` — dependency connectivity for the service grid.

### Probed dependencies

| Name | Check |
|------|-------|
| `postgresql` | Async DB ping |
| `redis` | Broker connectivity |
| `milvus` | List collections in the instance-bound Database (`eagle_text`, `eagle_visual`, …) |
| `minio` | Bucket head |
| `knowhere` | HTTP GET `settings.knowhere.base_url` |
| `pixelrag` | Import `pixelrag_render` / `pixelrag_embed` (library, not serve) |
| `vlm` | Qwen-VL reachability |
| `celery` | Inspect active workers |

Each dependency returns `DependencyStatus`:

```json
{
  "name": "milvus",
  "status": "up",
  "latency_ms": 42,
  "detail": "collections: eagle_text, eagle_visual",
  "uptime": "2 hours"
}
```

`uptime` uses in-process monotonic tracking (`_UPTIME_SINCE`) — resets on API restart.

Milvus probes use `settings.milvus.db_name` (from `EAGLE_RAG_PROFILE` / `plugins.default_namespace`) — not a global default database.

### Summary block

`DependencySummary`: counts of `up` / `down` / `unknown`, overall `status`, `version` (`eagle_rag.__version__`).

---

## `GET /health/plugins`

`PluginsHealthResponse` — loaded plugin manifests and Celery module list (worker consistency probe).

```json
{
  "default_namespace": "core",
  "enabled_modules": ["eagle_rag.plugins.core_defaults"],
  "manifests": [
    {
      "namespace": "core",
      "version": "1.0.0",
      "milvus_db_name": "core",
      "provides_pipelines": ["knowhere", "pixelrag"],
      "provides_specialized_collections": [],
      "provides_mcp_tools": ["core_ingest", "core_query", "core_retrieve_text", "core_retrieve_visual"]
    }
  ],
  "celery_modules": ["eagle_rag.plugins.core_defaults", "..."]
}
```

| Field | Meaning |
|-------|---------|
| `default_namespace` | Instance-bound domain (`settings.plugins.default_namespace`) |
| `enabled_modules` | Python module paths from `settings.plugins.enabled` |
| `manifests` | Per-plugin `PluginManifest` summary |
| `celery_modules` | Modules workers should import for task registration parity |

Use after changing `EAGLE_RAG_PROFILE`, adding in-repo plugins, or debugging namespace / MCP tool exposure mismatches.

---

## `GET /mcp/tools`

`McpToolsResponse` — static tool catalog from `TOOL_DEFINITIONS` in `mcp_server.py` (no async `list_tools()`).

```json
{
  "tools": [
    {
      "name": "core_ingest",
      "description": "…",
      "parameters": { "type": "object", "properties": { … } }
    }
  ]
}
```

Powers `McpServerDashboard` tool table. Full semantics: [MCP tools](mcp-tools.md).

---

## Admin routes (`/admin/*`)

### Infrastructure dashboards

| Path | Response | Content |
|------|----------|---------|
| `GET /admin/celery` | `AdminCeleryResponse` | Workers, active tasks, queue depths |
| `GET /admin/milvus` | `AdminMilvusResponse` | Collection row counts, partitions per KB |
| `GET /admin/minio` | `AdminMinioResponse` | Buckets, object counts |
| `GET /admin/redis` | `AdminRedisResponse` | Memory, connected clients |
| `GET /admin/knowhere` | `AdminKnowhereResponse` | Remote parser health |
| `GET /admin/pixelrag` | `AdminPixelragResponse` | In-process library status |
| `GET /admin/vlm` | `AdminVlmResponse` | Qwen-VL probe |
| `GET /admin/mcp` | `AdminMcpResponse` | Recent MCP call log |
| `GET /admin/config` | `AdminConfigOut` | Sanitized settings snapshot |
| `GET /admin/probes` | `AdminProbesResponse` | Probe config + last results |

### Mutating admin actions

| Path | Method | Purpose |
|------|--------|---------|
| `/admin/model-router` | `GET` / `PATCH` | Read/update routing mode override |
| `/admin/resource-limits` | `GET` / `PATCH` | Ops tuning knobs |
| `/admin/actions/{action}` | `POST` | Controlled maintenance actions |

Responses use `AdminActionResult` with `success`, `detail`.

---

## `GET /admin/logs` (SSE)

Real-time log tail for `LiveLogsTab`.

| Event | Payload |
|-------|---------|
| `log` | `{ level, message, timestamp, … }` |
| `heartbeat` | Keep-alive |

Frontend: `streamAdminLogs` in `lib/api/sse.ts`.

Wire format identical to other SSE endpoints (`event:` + `data:` JSON + blank line).

---

## MCP call log

`GET /admin/mcp` includes `McpCallLogOut` entries:

- `tool_name`, `arguments`, `result_summary`, `caller`, `latency_ms`, `timestamp`

Written by `record_mcp_call` from MCP tool wrappers.

---

## Error handling

| Situation | Behaviour |
|-----------|-----------|
| Single probe failure | `status: "down"` for that dependency; HTTP 200 on `/health` |
| Admin DB read failure | **503** or partial empty sections |
| SSE log stream error | Connection close; client reconnects |

---

## Frontend integration

`/health` route → `HealthHeaderActions`, `ServiceGrid`, per-service dashboards (`CeleryDashboard`, `KnowhereDashboard`, `McpServerDashboard`, …).

TanStack Query keys: `["health"]`, `["admin", "celery"]`, etc. — see `useHealth.ts`.

See [Health module](../frontend/health-module.md).

---

## Related documentation

- [MCP tools](mcp-tools.md)
- [Health module](../frontend/health-module.md)
- [MCP server (backend)](../backend/mcp-server.md)
- [Installation](../getting-started/installation.md) — dependency setup
