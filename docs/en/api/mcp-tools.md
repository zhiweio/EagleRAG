# MCP Tools

Eagle-RAG exposes four MCP tools for LLM agents via **FastMCP** (`eagle_rag/api/mcp_server.py`). Tools call the service layer **directly** — no HTTP round-trip to `/query` or `/ingest`.

Transport: streamable HTTP at `settings.mcp.streamable_http_path` (default `/mcp`), stdio fallback for subprocess clients.

REST discovery: `GET /mcp/tools` returns `TOOL_DEFINITIONS` metadata.

---

## Tool catalogue

| Tool | Service | Returns |
|------|---------|---------|
| `ingest` | `runner.ingest` | `{ job_id, status, document_id, dedup_hit }` |
| `query` | `EagleRouterQueryEngine.query` | `{ answer, sources, route, steps }` |
| `retrieve_text` | `KnowhereGraphRetriever` | `[{ node_id, text, score, metadata }]` |
| `retrieve_visual` | `PixelRAGVisualRetriever` | `[{ image_id, document_id, page, position, score }]` |

On failure, tools return `{ "error": "…" }` (dict) or `[{ "error": "…" }]` (list) without killing the MCP session.

---

## `ingest`

### Parameters (`TOOL_DEFINITIONS`)

```json
{
  "type": "object",
  "required": ["source_uri"],
  "properties": {
    "source_uri": {
      "type": "string",
      "description": "File path or web URL (http/https prefix is treated as a URL)"
    },
    "source_type": {
      "type": "string",
      "enum": ["policy", "financial", "business", "bidding", "tax", "other"]
    },
    "kb_name": {
      "type": "string",
      "description": "Knowledge base id (multi-tenant); optional, defaults to config"
    }
  }
}
```

### Behaviour

- `http://` / `https://` → `ingest(source_uri=…)`
- Otherwise → `ingest(file_path=…)`
- Async Celery dispatch — same as `POST /ingest`
- Wrapped in `resilient_call` + circuit breaker

### Error strings

| Pattern | Meaning |
|---------|---------|
| `circuit_open: ingest` | Circuit breaker open |
| `timeout: ingest` | Call timeout |
| `{ExceptionName}: {message}` | Unexpected failure |

---

## `query`

### Parameters

```json
{
  "type": "object",
  "required": ["query"],
  "properties": {
    "query": { "type": "string" },
    "mode": { "type": "string", "enum": ["auto", "text", "visual", "hybrid"] },
    "scope": { "type": "array", "items": { "type": "string" } },
    "kb_name": { "type": "string" },
    "scope_filter": {
      "type": "object",
      "properties": {
        "kb_names": { "type": "array", "items": { "type": "string" } },
        "document_ids": { "type": "array", "items": { "type": "string" } },
        "tags": { "type": "array", "items": { "type": "string" } }
      }
    }
  }
}
```

### Behaviour

- No session persistence (unlike REST `/query`)
- `scope_filter` union semantics identical to REST — see [Query](query.md#scope-filter--milvus-pushdown)
- Response trimmed to four keys: `answer`, `sources`, `route`, `steps`

### REST vs MCP

| Feature | REST `/query` | MCP `query` |
|---------|---------------|-------------|
| Streaming | SSE `/query/stream` | No — single response |
| Sessions | Yes | No |
| Attachments | Yes | No |
| Telemetry | `ai_logger` | `record_mcp_call` |

---

## `retrieve_text`

### Parameters

| Name | Type | Default | Description |
|------|------|---------|-------------|
| `query` | string | required | Retrieval query |
| `scope` | string[] | optional | Post-filter `document_id` |
| `top_k` | integer | 5 | Result count |
| `kb_name` | string | optional | Milvus KB filter |

### Return shape

```json
[
  {
    "node_id": "…",
    "text": "chunk body",
    "score": 0.87,
    "metadata": {
      "path": "/section/3",
      "level": 2,
      "summary": "…",
      "document_id": "doc_abc",
      "source_type": "policy"
    }
  }
]
```

**Caching:** `mcp_cache` keyed by `(tool, query, scope, top_k, kb_name)` — hits skip Milvus.

**Scope filter:** MCP `retrieve_text` does **not** accept `scope_filter` — use `scope` document list or REST `/search` for tag/KB union.

---

## `retrieve_visual`

### Parameters

Same as `retrieve_text` (`query`, `scope`, `top_k`, `kb_name`).

### Return shape

```json
[
  {
    "image_id": "img_abc",
    "document_id": "doc_xyz",
    "page": 3,
    "position": "0.12,0.45,0.88,0.92",
    "score": 0.91
  }
]
```

Cached similarly to `retrieve_text`.

---

## Resilience layer

| Mechanism | Module | Effect |
|-----------|--------|--------|
| Circuit breaker | `mcp_resilience` | `{ error: "circuit_open: …" }` |
| Timeout | `resilient_call` | `{ error: "timeout: …" }` |
| Metrics | `with_metrics` decorator | Prometheus counters |
| Call log | `admin.mcp_log` | Audit trail in `/admin/mcp` |

---

## Authentication (`configure_mcp_auth`)

When `settings.auth.enabled`:

| Provider | Mechanism |
|----------|-----------|
| `static-token` | `Authorization: Bearer <AUTH_API_KEY>` scope `eagle-rag:tools` |
| `oauth-github` | GitHub OAuth 2.1 proxy |
| `oauth-custom` | JWT via JWKS (`issuer_url/.well-known/jwks.json`) |

REST routes remain unauthenticated unless you add gateway rules separately.

---

## Agent integration example

```python
# llama-index-tools-mcp BasicMCPClient (stdio)
from llama_index.tools.mcp import BasicMCPClient

client = BasicMCPClient("python", ["-m", "eagle_rag.api.mcp_server"])
tools = await client.list_tools()
result = await client.call_tool("query", {"query": "…", "kb_name": "finance"})
```

HTTP transport: point MCP client at `http://host:8001/mcp` (port from `settings.mcp.port`).

---

## Related documentation

- [MCP server (backend)](../backend/mcp-server.md)
- [Health & admin](health-admin.md) — MCP dashboard + call log
- [Query](query.md) — REST parity for `query` tool
- [Ingest](ingest.md) — REST parity for `ingest` tool
