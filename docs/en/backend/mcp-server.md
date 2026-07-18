# MCP server

Eagle-RAG exposes **RAG-only** MCP tools for LLM agents: Core tools `core_ingest`, `core_query`, `core_retrieve_text`, `core_retrieve_visual`, plus `{namespace}_*` tools from the active profile. The server reuses the same service layer as REST — no HTTP self-calls.

**Source modules:** `eagle_rag/api/mcp_server.py`, `eagle_rag/plugins/mcp_registry.py`, `eagle_rag/api/mcp_http.py`, `eagle_rag/mcp_resilience.py`, `eagle_rag/mcp_cache.py`

!!! note "Product boundary"
    MCP is for ingest and retrieval context only — no side-effect tools such as SQL execution. See [ADR-008](../architecture/adr/008-rag-only-plugin-platform.md).

---

## 1. Theoretical background

### 1.1 Model Context Protocol

MCP (Anthropic, 2024) standardizes how LLM agents discover and invoke external tools. Eagle-RAG's MCP server enables agents (Claude, LlamaIndex FunctionAgent, etc.) to ingest documents and query knowledge bases without custom HTTP integration.

### 1.2 Tool-based RAG for agents

Agent frameworks use tools for retrieval-augmented reasoning (Schick et al., *Toolformer*, arXiv:2302.04761). Eagle-RAG's four tools map to the RAG pipeline stages:

| Tool | RAG stage |
|------|----------|
| `core_ingest` | Indexing |
| `core_retrieve_text` / `core_retrieve_visual` | Retrieval |
| `core_query` | Retrieval + Generation |

Separating retrieval from generation tools allows agents to inspect evidence before synthesizing answers.

### 1.3 Resilience patterns

MCP tools wrap service calls with **circuit breaker**, **timeout**, and **retry** patterns (Nygard, *Release It!*) — preventing agent sessions from hanging when Milvus or VLM is unavailable.

---

## 2. Tool definitions

Core tools are registered via `@register_mcp_tool` in `eagle_rag/plugins/mcp_registry.py` and exposed through FastMCP. Domain plugins register `{namespace}_{name}` tools; the instance exposes only `core_*` plus tools from `settings.plugins.default_namespace` (G3 filter). `assert_rag_only_tool_name` rejects side-effect fragments (`execute_sql`, `send_email`, …). Pre-plugin bare names (`ingest`, `query`) are **not** aliased.

Metadata mirrored in `TOOL_DEFINITIONS` for REST discovery at `GET /mcp/tools`.

### 2.1 `core_ingest`

```python
core_ingest(source_uri: str, source_type: str | None, kb_name: str | None)
→ {"job_id", "status", "document_id", "dedup_hit"}
```

Dispatches to Celery via `runner.ingest()`. Accepts file path or URL.

### 2.2 `core_query`

```python
core_query(query: str, mode: str | None, scope: list[str] | None,
           kb_name: str | None, scope_filter: dict | None)
→ {"answer", "sources", "route", "steps"}
```

Full multimodal Q&A via `EagleRouterQueryEngine.query()`. Retrieval may fan out to multiple Milvus collections via `RetrieverOrchestrator` + RRF merge when domain plugins are active.

### 2.3 `core_retrieve_text`

```python
core_retrieve_text(query: str, scope: list[str] | None, top_k: int, kb_name: str | None)
→ [{"node_id", "text", "score", "metadata": {path, level, summary, document_id, source_type}}]
```

Pure text retrieval via `KnowhereGraphRetriever` (Core) or `RetrieverOrchestrator` (multi-collection) — no LLM generation.

### 2.4 `core_retrieve_visual`

```python
core_retrieve_visual(query: str, scope: list[str] | None, top_k: int, kb_name: str | None)
→ [{"image_id", "document_id", "page", "position", "score"}]
```

Pure visual retrieval via `PixelRAGVisualRetriever`.

### 2.5 Domain plugin tools

Domain plugins register additional tools at load time (e.g. `biomed_query_entities`, `lakehouse_bi_query_semantic_context`). Only tools from the bound `default_namespace` are exposed alongside `core_*`. See [Plugin architecture](../architecture/plugin-architecture.md) § MCP surface.

---

## 3. Transport modes

### 3.1 HTTP (default)

Streamable HTTP mounted at `/mcp` in the main FastAPI app:

```yaml
mcp:
  transport: http
  streamable_http_path: /mcp
  stateless_http: true
  json_response: true
  port: 8081          # standalone mode
  workers: 4
```

Stateless mode (`FASTMCP_STATELESS_HTTP=true`) enables horizontal scaling without sticky sessions.

### 3.2 stdio (fallback)

```bash
python -m eagle_rag.api.mcp_server
# mcp.run(transport="stdio")
```

For local agent subprocess integration (LlamaIndex `BasicMCPClient`).

---

## 4. Resilience layer

**Module:** `eagle_rag/mcp_resilience.py`

```python
resilient_call("core_query", _do_query)
```

| Feature | Config | Behavior |
|---------|--------|----------|
| Timeout | `mcp.tool_timeout: 30` | Raises TimeoutError |
| Circuit breaker | `circuit_fail_threshold: 5` | Opens after 5 failures |
| Retry | `max_retries: 3` | Exponential backoff |

Errors returned as `{"error": "..."}` — MCP session continues.

---

## 5. Caching

**Module:** `eagle_rag/mcp_cache.py`

Retrieval tools cache results in Redis:

```python
ckey = cache_key("core_retrieve_text", query, scope=..., top_k=..., kb_name=...)
cached = get_cached(ckey)  # TTL from mcp.cache_ttl (300s)
```

Cache keys include `plugin_namespace` for multi-instance MinIO/Redis isolation.

Only non-empty results cached. Cache hits logged in MCP call log.

---

## 6. Authentication

**Function:** `configure_mcp_auth()`

| Provider | Config | Mechanism |
|----------|--------|-----------|
| Disabled | `auth.enabled: false` | No auth (intranet) |
| static-token | `auth_provider: static-token` | Bearer API key |
| oauth-github | `auth_provider: oauth-github` | GitHub OAuth 2.1 |
| oauth-custom | `auth_provider: oauth-custom` | JWT via JWKS |

REST API has no auth; MCP HTTP can be secured independently for cloud deployment.

---

## 7. Milvus filter usage via tools

Tools accept `kb_name` and `scope` parameters that translate to Milvus filters:

```python
# core_retrieve_text with kb_name="finance"
MetadataFilter(key="kb_name", value="finance", operator=EQ)
# → kb_name == "finance"

# core_query with scope_filter
{"kb_names": ["finance"], "tags": ["增值税"]}
# → (kb_name in ["finance"] or document_id in [resolved...])
```

---

## 8. LlamaIndex agent integration

Agents using `llama-index-tools-mcp` connect via stdio or HTTP:

```python
from llama_index.tools.mcp import BasicMCPClient
client = BasicMCPClient("python -m eagle_rag.api.mcp_server")
tools = client.list_tools()  # core_ingest, core_query, core_retrieve_text, core_retrieve_visual, …
```

Tool outputs are JSON dicts/lists — compatible with LlamaIndex `FunctionAgent` tool calling.

---

## 9. Design tensions and tuning

| Tension | MCP layer | Effect | Mitigation |
| --- | --- | --- | --- |
| **Circuit breaker open** | `mcp_resilience` after N failures | Tools return `{error: ...}` not HTTP 503 — agents may misparse | Teach agents to read `error` field |
| **Tool timeout vs ingest** | `mcp.tool_timeout` 30s default | `core_ingest` returns before Celery finishes — poll task separately | Document async ingest pattern |
| **Cache staleness** | `mcp_cache` on identical retrieve | KB updated but agent sees old nodes until TTL | Lower TTL after bulk ingest |
| **Scope omitted by agent** | `core_query` optional `scope_filter` | Full-KB search cost + cross-doc noise | Pass `kb_name` + scope in agent prompts |
| **G3 tool filter** | `PluginManager` at load | Domain tools from other namespaces not listed | Match `default_namespace` to profile |
| **RAG-only guard** | `assert_rag_only_tool_name` | Registration fails for side-effect tool names | Keep domain tools retrieve/ingest only |
| **stdio vs HTTP transport** | Different connection lifecycle | Long-running stdio agents hold API connections | Prefer streamable HTTP for poolers |
| **OAuth optional** | `auth` on `/mcp` when enabled | Token expiry mid-session | Refresh before long agent runs |

---

## 10. Config & tuning

```yaml
mcp:
  transport: http
  tool_timeout: 30
  max_retries: 3
  circuit_fail_threshold: 5
  cache_ttl: 300
  redis_url: ""               # falls back to celery.broker_url
  auth_provider: static-token

auth:
  enabled: false
  api_key: ${AUTH_API_KEY}
```

---

## 11. Tests

| Test file | Contract |
|-----------|----------|
| `tests/test_mcp_http_transport.py` | HTTP mount, tool listing |
| `tests/test_mcp_resilience.py` | Circuit breaker, timeout |
| `tests/test_mcp_cache.py` | Redis cache hit/miss |
| `tests/test_mcp_metrics.py` | Call logging |
| `tests/test_mcp_auth.py` | Static token verification |
| `tests/test_mcp_config.py` | Transport config |
| `tests/plugins/test_manager.py` | G3 MCP tool filter |

---

## 12. References

- Model Context Protocol: [modelcontextprotocol.io](https://modelcontextprotocol.io/)
- FastMCP: [github.com/jlowin/fastmcp](https://github.com/jlowin/fastmcp)
- Schick et al., *Toolformer*, [arXiv:2302.04761](https://arxiv.org/abs/2302.04761)
- Nygard, *Release It!* (circuit breaker pattern)
- LlamaIndex MCP tools: [docs.llamaindex.ai/en/stable/examples/tools/mcp](https://docs.llamaindex.ai/en/stable/examples/tools/mcp/)
