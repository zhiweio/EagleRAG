# MCP server

Eagle-RAG exposes four MCP (Model Context Protocol) tools for LLM agent integration: `ingest`, `query`, `retrieve_text`, and `retrieve_visual`. The server reuses the same service layer as REST endpoints — no HTTP self-calls.

**Source modules:** `eagle_rag/api/mcp_server.py`, `eagle_rag/api/mcp_http.py`, `eagle_rag/mcp_resilience.py`, `eagle_rag/mcp_cache.py`

---

## 1. Theoretical background

### 1.1 Model Context Protocol

MCP (Anthropic, 2024) standardizes how LLM agents discover and invoke external tools. Eagle-RAG's MCP server enables agents (Claude, LlamaIndex FunctionAgent, etc.) to ingest documents and query knowledge bases without custom HTTP integration.

### 1.2 Tool-based RAG for agents

Agent frameworks use tools for retrieval-augmented reasoning (Schick et al., *Toolformer*, arXiv:2302.04761). Eagle-RAG's four tools map to the RAG pipeline stages:

| Tool | RAG stage |
|------|----------|
| `ingest` | Indexing |
| `retrieve_text` / `retrieve_visual` | Retrieval |
| `query` | Retrieval + Generation |

Separating retrieval from generation tools allows agents to inspect evidence before synthesizing answers.

### 1.3 Resilience patterns

MCP tools wrap service calls with **circuit breaker**, **timeout**, and **retry** patterns (Nygard, *Release It!*) — preventing agent sessions from hanging when Milvus or VLM is unavailable.

---

## 2. Tool definitions

Registered via FastMCP `@mcp.tool()` decorator. Metadata mirrored in `TOOL_DEFINITIONS` for REST discovery at `GET /mcp/tools`.

### 2.1 `ingest`

```python
ingest(source_uri: str, source_type: str | None, kb_name: str | None)
→ {"job_id", "status", "document_id", "dedup_hit"}
```

Dispatches to Celery via `runner.ingest()`. Accepts file path or URL.

### 2.2 `query`

```python
query(query: str, mode: str | None, scope: list[str] | None,
      kb_name: str | None, scope_filter: dict | None)
→ {"answer", "sources", "route", "steps"}
```

Full multimodal Q&A via `EagleRouterQueryEngine.query()`.

### 2.3 `retrieve_text`

```python
retrieve_text(query: str, scope: list[str] | None, top_k: int, kb_name: str | None)
→ [{"node_id", "text", "score", "metadata": {path, level, summary, document_id, source_type}}]
```

Pure text retrieval via `KnowhereGraphRetriever` — no LLM generation.

### 2.4 `retrieve_visual`

```python
retrieve_visual(query: str, scope: list[str] | None, top_k: int, kb_name: str | None)
→ [{"image_id", "document_id", "page", "position", "score"}]
```

Pure visual retrieval via `PixelRAGVisualRetriever`.

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
resilient_call("query", _do_query)
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
ckey = cache_key("retrieve_text", query, scope=..., top_k=..., kb_name=...)
cached = get_cached(ckey)  # TTL from mcp.cache_ttl (300s)
```

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
# retrieve_text with kb_name="finance"
MetadataFilter(key="kb_name", value="finance", operator=EQ)
# → kb_name == "finance"

# query with scope_filter
{"kb_names": ["finance"], "tags": ["增值税"]}
# → (kb_name in ["finance"] or document_id in [resolved...])
```

---

## 8. LlamaIndex agent integration

Agents using `llama-index-tools-mcp` connect via stdio or HTTP:

```python
from llama_index.tools.mcp import BasicMCPClient
client = BasicMCPClient("python -m eagle_rag.api.mcp_server")
tools = client.list_tools()  # ingest, query, retrieve_text, retrieve_visual
```

Tool outputs are JSON dicts/lists — compatible with LlamaIndex `FunctionAgent` tool calling.

---

## 9. Design tensions and tuning

| Tension | MCP layer | Effect | Mitigation |
| --- | --- | --- | --- |
| **Circuit breaker open** | `mcp_resilience` after N failures | Tools return `{error: ...}` not HTTP 503 — agents may misparse | Teach agents to read `error` field |
| **Tool timeout vs ingest** | `mcp.tool_timeout` 30s default | `ingest` returns before Celery finishes — poll task separately | Document async ingest pattern |
| **Cache staleness** | `mcp_cache` on identical retrieve | KB updated but agent sees old nodes until TTL | Lower TTL after bulk ingest |
| **Scope omitted by agent** | `query` tool optional `scope_filter` | Full-KB search cost + cross-doc noise | Pass `kb_name` + scope in agent prompts |
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

---

## 12. References

- Model Context Protocol: [modelcontextprotocol.io](https://modelcontextprotocol.io/)
- FastMCP: [github.com/jlowin/fastmcp](https://github.com/jlowin/fastmcp)
- Schick et al., *Toolformer*, [arXiv:2302.04761](https://arxiv.org/abs/2302.04761)
- Nygard, *Release It!* (circuit breaker pattern)
- LlamaIndex MCP tools: [docs.llamaindex.ai/en/stable/examples/tools/mcp](https://docs.llamaindex.ai/en/stable/examples/tools/mcp/)
