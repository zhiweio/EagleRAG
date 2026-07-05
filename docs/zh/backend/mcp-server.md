# MCP 服务器

Eagle-RAG 暴露四个 MCP（Model Context Protocol）工具供 LLM Agent 集成：`ingest`、`query`、`retrieve_text`、`retrieve_visual`。服务器复用与 REST 相同的服务层 —— 无 HTTP 自调用。

**源码模块：** `eagle_rag/api/mcp_server.py`、`eagle_rag/api/mcp_http.py`、`eagle_rag/mcp_resilience.py`、`eagle_rag/mcp_cache.py`

---

## 1. 理论背景

### 1.1 Model Context Protocol

MCP（Anthropic, 2024）标准化 LLM Agent 发现与调用外部工具的方式。Eagle-RAG MCP 服务器让 Agent（Claude、LlamaIndex FunctionAgent 等）入库文档与查询知识库，无需定制 HTTP 集成。

### 1.2 Agent 的工具式 RAG

Agent 框架用工具做检索增强推理（Schick et al., *Toolformer*, arXiv:2302.04761）。Eagle-RAG 四个工具对应 RAG 流水线阶段：

| 工具 | RAG 阶段 |
|------|----------|
| `ingest` | 索引 |
| `retrieve_text` / `retrieve_visual` | 检索 |
| `query` | 检索 + 生成 |

分离检索与生成工具，Agent 可在综合答案前检查证据。

### 1.3 韧性模式

MCP 工具以服务调用外包**熔断器**、**超时**与**重试**（Nygard, *Release It!*）—— Milvus 或 VLM 不可用时避免 Agent 会话挂起。

---

## 2. 工具定义

经 FastMCP `@mcp.tool()` 注册。元数据镜像于 `TOOL_DEFINITIONS`，REST 在 `GET /mcp/tools` 发现。

### 2.1 `ingest`

```python
ingest(source_uri: str, source_type: str | None, kb_name: str | None)
→ {"job_id", "status", "document_id", "dedup_hit"}
```

经 `runner.ingest()` 派发到 Celery。接受文件路径或 URL。

### 2.2 `query`

```python
query(query: str, mode: str | None, scope: list[str] | None,
      kb_name: str | None, scope_filter: dict | None)
→ {"answer", "sources", "route", "steps"}
```

经 `EagleRouterQueryEngine.query()` 的完整多模态问答。

### 2.3 `retrieve_text`

```python
retrieve_text(query: str, scope: list[str] | None, top_k: int, kb_name: str | None)
→ [{"node_id", "text", "score", "metadata": {path, level, summary, document_id, source_type}}]
```

经 `KnowhereGraphRetriever` 的纯文本检索 —— 无 LLM 生成。

### 2.4 `retrieve_visual`

```python
retrieve_visual(query: str, scope: list[str] | None, top_k: int, kb_name: str | None)
→ [{"image_id", "document_id", "page", "position", "score"}]
```

经 `PixelRAGVisualRetriever` 的纯视觉检索。

---

## 3. 传输模式

### 3.1 HTTP（默认）

可流式 HTTP 挂载于主 FastAPI 应用 `/mcp`：

```yaml
mcp:
  transport: http
  streamable_http_path: /mcp
  stateless_http: true
  json_response: true
  port: 8081          # standalone mode
  workers: 4
```

无状态模式（`FASTMCP_STATELESS_HTTP=true`）支持水平扩展，无需 sticky session。

### 3.2 stdio（回退）

```bash
python -m eagle_rag.api.mcp_server
# mcp.run(transport="stdio")
```

供本地 Agent 子进程集成（LlamaIndex `BasicMCPClient`）。

---

## 4. 韧性层

**模块：** `eagle_rag/mcp_resilience.py`

```python
resilient_call("query", _do_query)
```

| 特性 | 配置 | 行为 |
|---------|--------|----------|
| Timeout | `mcp.tool_timeout: 30` | 抛出 TimeoutError |
| Circuit breaker | `circuit_fail_threshold: 5` | 5 次失败后打开 |
| Retry | `max_retries: 3` | 指数退避 |

错误以 `{"error": "..."}` 返回 —— MCP 会话继续。

---

## 5. 缓存

**模块：** `eagle_rag/mcp_cache.py`

检索工具在 Redis 缓存结果：

```python
ckey = cache_key("retrieve_text", query, scope=..., top_k=..., kb_name=...)
cached = get_cached(ckey)  # TTL from mcp.cache_ttl (300s)
```

仅缓存非空结果。命中记入 MCP 调用日志。

---

## 6. 认证

**函数：** `configure_mcp_auth()`

| Provider | 配置 | 机制 |
|----------|--------|-----------|
| Disabled | `auth.enabled: false` | 无鉴权（内网） |
| static-token | `auth_provider: static-token` | Bearer API key |
| oauth-github | `auth_provider: oauth-github` | GitHub OAuth 2.1 |
| oauth-custom | `auth_provider: oauth-custom` | JWT via JWKS |

REST API 无鉴权；MCP HTTP 可独立加固供云部署。

---

## 7. 工具中的 Milvus 过滤

工具接受 `kb_name` 与 `scope`，翻译为 Milvus 过滤：

```python
# retrieve_text with kb_name="finance"
MetadataFilter(key="kb_name", value="finance", operator=EQ)
# → kb_name == "finance"

# query with scope_filter
{"kb_names": ["finance"], "tags": ["增值税"]}
# → (kb_name in ["finance"] or document_id in [resolved...])
```

---

## 8. LlamaIndex Agent 集成

使用 `llama-index-tools-mcp` 的 Agent 经 stdio 或 HTTP 连接：

```python
from llama_index.tools.mcp import BasicMCPClient
client = BasicMCPClient("python -m eagle_rag.api.mcp_server")
tools = client.list_tools()  # ingest, query, retrieve_text, retrieve_visual
```

工具输出为 JSON dict/list —— 兼容 LlamaIndex `FunctionAgent` 工具调用。

---

## 9. 设计张力与调参

| 张力 | MCP 层 | 效果 | 缓解 |
| --- | --- | --- | --- |
| **熔断器打开** | N 次失败后 `mcp_resilience` | 工具返回 `{error: ...}` 非 HTTP 503 —— agent 可能误解析 | 教 agent 读 `error` 字段 |
| **工具超时 vs 入库** | 默认 30s `mcp.tool_timeout` | `ingest` 在 Celery 完成前返回 —— 须单独轮询任务 | 文档化异步入库模式 |
| **缓存 stale** | 相同 retrieve 走 `mcp_cache` | KB 更新后 agent 见旧节点直至 TTL | 批量入库后降 TTL |
| **Agent 省略 scope** | `query` 工具可选 `scope_filter` | 全 KB 搜索成本 + 跨 doc 噪声 | agent prompt 传 `kb_name` + scope |
| **stdio vs HTTP 传输** | 不同连接生命周期 | 长驻 stdio agent 占住 API 连接 | 连接池场景优先 streamable HTTP |
| **OAuth 可选** | 启用时 `/mcp` 上 `auth` | 长 session 中 token 过期 | 长跑 agent 前刷新 |

---

## 10. 配置与调优

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

## 11. 测试

| 测试文件 | 契约 |
|-----------|----------|
| `tests/test_mcp_http_transport.py` | HTTP 挂载、工具列表 |
| `tests/test_mcp_resilience.py` | 熔断器、超时 |
| `tests/test_mcp_cache.py` | Redis 缓存命中/未命中 |
| `tests/test_mcp_metrics.py` | 调用日志 |
| `tests/test_mcp_auth.py` | 静态 token 校验 |
| `tests/test_mcp_config.py` | 传输配置 |

---

## 12. 参考文献

- Model Context Protocol: [modelcontextprotocol.io](https://modelcontextprotocol.io/)
- FastMCP: [github.com/jlowin/fastmcp](https://github.com/jlowin/fastmcp)
- Schick et al., *Toolformer*, [arXiv:2302.04761](https://arxiv.org/abs/2302.04761)
- Nygard, *Release It!* (circuit breaker pattern)
- LlamaIndex MCP tools: [docs.llamaindex.ai/en/stable/examples/tools/mcp](https://docs.llamaindex.ai/en/stable/examples/tools/mcp/)
