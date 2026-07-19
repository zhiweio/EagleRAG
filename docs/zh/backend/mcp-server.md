# MCP 服务器

Eagle-RAG 为 LLM Agent 暴露**仅 RAG** 的 MCP 工具：Core 工具 `core_ingest`、`core_query`、`core_retrieve_text`、`core_retrieve_visual`，以及来自活跃 profile 的 `{namespace}_*` 工具。服务器复用与 REST 相同的服务层 — 无 HTTP 自调用。

**源模块：** `eagle_rag/api/mcp_server.py`、`eagle_rag/plugins/mcp_registry.py`、`eagle_rag/api/mcp_http.py`、`eagle_rag/mcp_resilience.py`、`eagle_rag/mcp_cache.py`

!!! note "产品边界"
    MCP 仅用于摄取与检索上下文 — 无 SQL 执行等副作用工具。见 [ADR-008](../architecture/adr/008-rag-only-plugin-platform.md)。

---

## 1. 理论背景

### 1.1 Model Context Protocol

MCP（Anthropic，2024）标准化 LLM Agent 发现与调用外部工具的方式。Eagle-RAG 的 MCP 服务器使 Agent（Claude、LlamaIndex FunctionAgent 等）无需自定义 HTTP 集成即可摄取文档并查询知识库。

### 1.2 面向 Agent 的基于工具的 RAG

Agent 框架用工具做检索增强推理（Schick 等，*Toolformer*，arXiv:2302.04761）。Eagle-RAG 的 Core 四个工具映射到 RAG 管线阶段：

| 工具 | RAG 阶段 |
|------|----------|
| `core_ingest` | 索引 |
| `core_retrieve_text` / `core_retrieve_visual` | 检索 |
| `core_query` | 检索 + 生成 |

将检索与生成工具分离，使 Agent 可在综合回答前检查证据。

### 1.3 韧性模式

MCP 工具用**断路器**、**超时**与**重试**模式包装服务调用（Nygard，*Release It!*）— 防止 Milvus 或 VLM 不可用时 Agent 会话挂起。

---

## 2. 工具定义

Core 工具经 `eagle_rag/plugins/mcp_registry.py` 中 `@register_mcp_tool` 注册，经 FastMCP 暴露。域插件注册 `{namespace}_{name}` 工具；实例仅暴露 `core_*` 与 `settings.plugins.default_namespace` 的工具（G3 过滤）。`assert_rag_only_tool_name` 拒绝副作用片段（`execute_sql`、`send_email` 等）。插件前的裸名（`ingest`、`query`）**不**做别名。

元数据镜像于 `TOOL_DEFINITIONS`，供 `GET /mcp/tools` REST 发现。

### 2.1 `core_ingest`

```python
core_ingest(source_uri: str, source_type: str | None, kb_name: str | None)
→ {"job_id", "status", "document_id", "dedup_hit"}
```

经 `runner.ingest()` 派发到 Celery。接受文件路径或 URL。

### 2.2 `core_query`

```python
core_query(query: str, mode: str | None, scope: list[str] | None,
           kb_name: str | None, scope_filter: dict | None)
→ {"answer", "sources", "route", "steps"}
```

经 `EagleRouterQueryEngine.query()` 做完整多模态问答。域插件活跃时，检索可经 `RetrieverOrchestrator` + RRF 合并扇出到多个 Milvus collection。

### 2.3 `core_retrieve_text`

```python
core_retrieve_text(query: str, scope: list[str] | None, top_k: int, kb_name: str | None)
→ [{"node_id", "text", "score", "metadata": {path, level, summary, document_id, source_type}}]
```

纯文本检索，经 `KnowhereGraphRetriever`（Core）或 `RetrieverOrchestrator`（多 collection）— 无 LLM 生成。

### 2.4 `core_retrieve_visual`

```python
core_retrieve_visual(query: str, scope: list[str] | None, top_k: int, kb_name: str | None)
→ [{"image_id", "document_id", "page", "position", "score"}]
```

纯视觉检索，经 `PixelRAGVisualRetriever`。

### 2.5 域插件工具

域插件在加载时注册额外工具（如 `biomed_query_entities`、`lakehouse_bi_query_semantic_context`）。仅绑定 `default_namespace` 的工具与 `core_*` 一并暴露。见[插件架构](../architecture/plugin-architecture.md) § MCP 表面。

---

## 3. 传输模式

### 3.1 HTTP（默认）

可流式 HTTP 挂载于主 FastAPI 应用的 `/mcp`：

```yaml
mcp:
  transport: http
  streamable_http_path: /mcp
  stateless_http: true
  json_response: true
  port: 8081          # 独立模式
  workers: 4
```

无状态模式（`FASTMCP_STATELESS_HTTP=true`）支持水平扩展，无需粘性会话。

### 3.2 stdio（回退）

```bash
python -m eagle_rag.api.mcp_server
# mcp.run(transport="stdio")
```

用于本地 Agent 子进程集成（LlamaIndex `BasicMCPClient`）。

---

## 4. 韧性层

**模块：** `eagle_rag/mcp_resilience.py`

```python
resilient_call("core_query", _do_query)
```

| 特性 | 配置 | 行为 |
|---------|--------|----------|
| 超时 | `mcp.tool_timeout: 30` | 抛出 TimeoutError |
| 断路器 | `circuit_fail_threshold: 5` | 5 次失败后打开 |
| 重试 | `max_retries: 3` | 指数退避 |

错误以 `{"error": "..."}` 返回 — MCP 会话继续。

---

## 5. 缓存

**模块：** `eagle_rag/mcp_cache.py`

检索工具在 Redis 中缓存结果：

```python
ckey = cache_key("core_retrieve_text", query, scope=..., top_k=..., kb_name=...)
cached = get_cached(ckey)  # TTL 来自 mcp.cache_ttl（300s）
```

缓存键包含 `plugin_namespace`，用于多实例 MinIO/Redis 隔离。

仅缓存非空结果。缓存命中记入 MCP 调用日志。

---

## 6. 认证

**函数：** `configure_mcp_auth()`

| 提供者 | 配置 | 机制 |
|----------|--------|-----------|
| 禁用 | `auth.enabled: false` | 无认证（内网） |
| static-token | `auth_provider: static-token` | Bearer API key |
| oauth-github | `auth_provider: oauth-github` | GitHub OAuth 2.1 |
| oauth-custom | `auth_provider: oauth-custom` | 经 JWKS 的 JWT |

REST API 无认证；MCP HTTP 可独立加固以用于云部署。

---

## 7. 经工具的 Milvus 过滤用法

工具接受 `kb_name` 与 `scope` 参数，翻译为 Milvus 过滤器：

```python
# core_retrieve_text，kb_name="finance"
MetadataFilter(key="kb_name", value="finance", operator=EQ)
# → kb_name == "finance"

# core_query，scope_filter
{"kb_names": ["finance"], "tags": ["增值税"]}
# → (kb_name in ["finance"] or document_id in [resolved...])
```

---

## 8. LlamaIndex Agent 集成

使用 `llama-index-tools-mcp` 的 Agent 经 stdio 或 HTTP 连接：

```python
from llama_index.tools.mcp import BasicMCPClient
client = BasicMCPClient("python -m eagle_rag.api.mcp_server")
tools = client.list_tools()  # core_ingest, core_query, core_retrieve_text, core_retrieve_visual, …
```

工具输出为 JSON dict/list — 兼容 LlamaIndex `FunctionAgent` 工具调用。

---

## 9. 设计张力与调优

| 张力 | MCP 层 | 效果 | 缓解 |
| --- | --- | --- | --- |
| **断路器打开** | N 次失败后 `mcp_resilience` | 工具返回 `{error: ...}` 而非 HTTP 503 — Agent 可能误解析 | 教导 Agent 读取 `error` 字段 |
| **工具超时 vs 摄取** | 默认 `mcp.tool_timeout` 30s | `core_ingest` 在 Celery 完成前返回 — 需单独轮询任务 | 文档化异步摄取模式 |
| **缓存陈旧** | 相同检索上的 `mcp_cache` | KB 已更新但 Agent 在 TTL 内看到旧节点 | 批量摄取后降低 TTL |
| **Agent 省略 scope** | `core_query` 可选 `scope_filter` | 全 KB 搜索成本 + 跨文档噪声 | 在 Agent 提示中传入 `kb_name` + scope |
| **G3 工具过滤** | 加载时 `PluginManager` | 其他 namespace 的域工具不列出 | `default_namespace` 与 profile 匹配 |
| **仅 RAG 守卫** | `assert_rag_only_tool_name` | 副作用工具名注册失败 | 域工具仅保留 retrieve/ingest |
| **stdio vs HTTP 传输** | 不同连接生命周期 | 长运行 stdio Agent 占用 API 连接 | 连接池优先用可流式 HTTP |
| **OAuth 可选** | 启用时 `/mcp` 上的 `auth` | 长会话中 token 过期 | 长 Agent 运行前刷新 |

---

## 10. 配置与调优

```yaml
mcp:
  transport: http
  tool_timeout: 30
  max_retries: 3
  circuit_fail_threshold: 5
  cache_ttl: 300
  redis_url: ""               # 回退到 celery.broker_url
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
| `tests/test_mcp_resilience.py` | 断路器、超时 |
| `tests/test_mcp_cache.py` | Redis 缓存命中/未命中 |
| `tests/test_mcp_metrics.py` | 调用日志 |
| `tests/test_mcp_auth.py` | 静态 token 校验 |
| `tests/test_mcp_config.py` | 传输配置 |
| `tests/plugins/test_manager.py` | G3 MCP 工具过滤 |

---

## 12. 参考文献

- Model Context Protocol：[modelcontextprotocol.io](https://modelcontextprotocol.io/)
- FastMCP：[github.com/jlowin/fastmcp](https://github.com/jlowin/fastmcp)
- Schick 等，*Toolformer*，[arXiv:2302.04761](https://arxiv.org/abs/2302.04761)
- Nygard，*Release It!*（断路器模式）
- LlamaIndex MCP 工具：[docs.llamaindex.ai/en/stable/examples/tools/mcp](https://docs.llamaindex.ai/en/stable/examples/tools/mcp/)
