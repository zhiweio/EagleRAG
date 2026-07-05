# API 层

API 层经 **FastAPI** HTTP 端点暴露 Eagle-RAG 多模态 RAG 能力，并在 `/mcp` 挂载 **FastMCP** 可流式 HTTP 子应用。路由用 Pydantic schema 校验请求，委托服务层（入库 runner、路由引擎、store），并为 query/search 路径桥接 SSE 流式。

**源码模块：** `eagle_rag/api/app.py`、`eagle_rag/api/query.py`、`eagle_rag/api/ingest.py`、`eagle_rag/api/documents.py` 及各域路由。

---

## 1. 理论背景

### 1.1 RAG 即服务 API

生产 RAG 暴露三类核心 API 面（Gao et al., RAG Survey, arXiv:2312.10997）：

| 面 | Eagle-RAG 端点 |
|---------|-------------------|
| **入库** — 向索引添加文档 | `POST /ingest` |
| **检索** — 取相关 chunk | `POST /search`, `/search/stream` |
| **生成** — 带引用作答 | `POST /query`, `/query/stream` |

Eagle-RAG 另有证据端点（`GET /documents/{id}/structure`, `/file`, `/chunks/{id}`）供 grounded UI 渲染。

### 1.2 流式生成的 Server-Sent Events（SSE）

流式生成用 SSE —— HTTP/1.1 服务端→客户端单向推送标准（WHATWG HTML Living Standard）。每事件带 `event` + `data` JSON，对应 route/recall/rerank/token/done 等步骤。

### 1.3 多租户 API 设计

多租户端点均接受可选 `kb_name`，回退 `settings.kb_name`。范围过滤（`ScopeSelection`）将租户/文档/标签约束下推到 Milvus —— 实现**请求级检索隔离**。

---

## 2. 应用结构

**入口：** `eagle_rag/api/app.py`

```python
app = FastAPI(title="Eagle-RAG", version="0.1.0", lifespan=get_combined_lifespan(mcp_app))
```

### 2.1 中间件栈

| 中间件 | 用途 |
|-----------|---------|
| `TelemetryMiddleware` | 每请求 OpenTelemetry SERVER span |
| `GZipMiddleware` | 压缩 >1KB JSON（检索载荷） |
| `CORSMiddleware` | 允许前端跨域（`*`） |

无鉴权中间件 —— 按设计仅内网。

### 2.2 挂载路由

| 路由 | 前缀 | 模块 |
|--------|--------|--------|
| Health | `/health`, `/admin/*` | `api/health.py` |
| Documents | `/documents` | `api/documents.py` |
| Images | `/images` | `api/documents.py` |
| Ingest | `/ingest` | `api/ingest.py` |
| Knowledge bases | `/knowledge-bases` | `api/knowledge_bases.py` |
| Tags | `/tags` | `api/tags.py` |
| Attachments | `/attachments` | `api/attachments.py` |
| Notifications | `/notifications` | `api/notifications.py` |
| Users | `/users` | `api/users.py` |
| Query/Sessions | `/query`, `/sessions` | `api/query.py` |
| MCP sub-app | `/mcp` | `api/mcp_http.py` |

### 2.3 基础设施端点

| 路径 | 处理器 | 用途 |
|------|---------|---------|
| `/metrics` | Prometheus metrics | 抓取 |
| `/health` | 健康检查 | Docker/HAProxy 探针 |
| `/docs` | OpenAPI UI | API 探索 |

---

## 3. 代码走读：查询端点

**模块：** `eagle_rag/api/query.py`

### 3.1 查询引擎单例

```python
_engine: EagleRouterQueryEngine | None = None

def get_query_engine() -> EagleRouterQueryEngine:
    global _engine
    if _engine is None:
        _engine = EagleRouterQueryEngine(top_k=settings.pixelrag.top_k)
    return _engine
```

懒单例避免 import 时连 Milvus/嵌入。

### 3.2 核心端点

| 方法 | 路径 | 引擎方法 | 响应 |
|--------|------|--------------|----------|
| POST | `/query` | `engine.query()` | `QueryResponse` |
| POST | `/query/stream` | `engine.query_stream()` | SSE |
| POST | `/search` | `engine.search()` | `SearchResponse` |
| POST | `/search/stream` | `engine.search_stream()` | SSE |

均接受 `QueryRequest`：

```python
class QueryRequest(BaseModel):
    query: str
    mode: str | None = "auto"
    kb_name: str | None = None
    top_k: int = 5
    scope: list[str] | None = None
    scope_filter: ScopeSelection | None = None
    filters: dict | None = None
    attachments: list[str] | None = None
    session_id: str | None = None
```

### 3.3 SSE 桥接

```python
async def _sse_generator(events: Iterator[dict]) -> AsyncGenerator[str, None]:
    for item in events:
        yield f"event: {item['event']}\ndata: {json.dumps(item['data'])}\n\n"
```

包在 `StreamingResponse(media_type="text/event-stream")` 中。

### 3.4 会话集成

`/query/stream` 提供 `session_id` 时：

1. 经 `sessions.store` 加载或创建会话。
2. 流式前持久化用户消息。
3. `done` 事件时持久化 assistant 消息（含 sources/steps）。
4. 产出 `session` 事件，含 `session_id` + `user_message_id`。

---

## 4. 代码走读：入库端点

**模块：** `eagle_rag/api/ingest.py`

| 方法 | 路径 | 动作 |
|--------|------|--------|
| POST | `/ingest` | Multipart 上传 → `runner.ingest()` |
| POST | `/ingest/url` | URL 入库 |
| GET | `/tasks/{job_id}` | 任务审计状态 |
| GET | `/tasks` | 列出近期任务 |

文件上传流程：

1. 从 `UploadFile` 读字节。
2. 调用 `ingest(file_bytes=..., filename=..., kb_name=...)`。
3. 返回带 job_id/document_id 的 `IngestResponse`。

---

## 5. 代码走读：证据端点

**模块：** `eagle_rag/api/documents.py`

| 方法 | 路径 | 数据来源 |
|--------|------|------------|
| GET | `/documents` | PostgreSQL registry |
| GET | `/documents/{id}` | 文档详情 |
| GET | `/documents/{id}/structure` | `extra` 中 `doc_nav` 或 Milvus 重建 |
| GET | `/documents/{id}/file` | MinIO 预签名 URL |
| GET | `/documents/{id}/chunks/{chunk_id}` | 按 ID 的 Milvus 文本节点 |
| DELETE | `/documents/{id}` | 级联删除 |

Structure 端点供前端文档树查看器使用，无需重新解析。

---

## 6. Milvus 交互（经服务层）

API 层不直接调 Milvus。检索器按请求参数组装过滤表达式：

```
# From QueryRequest.kb_name
kb_name == "finance"

# From QueryRequest.scope_filter
(kb_name in ["finance", "pharma"] or document_id in ["doc-1"])
```

见 [retrieval](retrieval.md) 与 [vector-stores](vector-stores.md)。

---

## 7. LlamaIndex 集成

API 层调用 `EagleRouterQueryEngine`，其内部使用：

- `VectorStoreIndex.as_retriever()` 做文本近似最近邻
- `CustomQueryEngine`（`EagleMultimodalQueryEngine`）做生成
- 流水线全程 `TextNode` / `ImageNode` / `NodeWithScore`

LlamaIndex 类型不泄漏到 API 响应 —— Pydantic schema 将节点映射为 `SourceText` / `SourceImage` DTO。

---

## 8. 设计张力与调参

| 张力 | 端点 / 层 | 效果 | 调节 |
| --- | --- | --- | --- |
| **SSE 线程桥接** | `query_stream` 在 executor 跑同步 VLM | 每个活跃流占一 OS 线程 —— 小 pod 并发用户上限 | 限制 ingress 并发；批处理用非流式 `/query` |
| **同步 query 尾延迟** | `POST /query` 阻塞至生成结束 | MCP 与 REST 同步调用等 rerank + VLM | UX 优先 `/query/stream`；客户端 timeout > 120s |
| **Source 载荷上限** | `_text_source` + `source_content_max_chars` | 证据面板截断 vs 模型上下文 | 提高 `router.source_content_max_chars`（仅响应） |
| **Scope 校验缺口** | Pydantic 接受任意 `scope_filter` 列表 | 超大 `document_ids` 可能超 Milvus expr 限制 | 保持低于 `max_scope_documents`；客户端校验 |
| **kb_name 回退** | 省略时 handler 用 `settings.kb_name` | 多租户 agent 误查错误 KB | agent 集成必须显式 `kb_name` |
| **证据 HTML 拉取** | `GET /chunks/{chunk_id}` MinIO 往返 | 大表 HTML 拖慢证据栏 | 前端缓存；懒加载 chunk 预览 |
| **Health vs admin 成本** | `/health` 带 timeout 探测全部依赖 | 频繁 K8s probe 负载 Milvus + Celery | 若拆分则用 `/health/live` 模式 |

---

## 9. 配置与调优

```yaml
app:
  host: 0.0.0.0
  port: 8000

pixelrag:
  top_k: 5              # default retrieval breadth for query engine singleton

router:
  source_content_max_chars: 4000

attachments:
  ttl_hours: 24
```

**环境：**

```
APP_PORT=8000
KB_NAME=default
```

---

## 10. 测试

| 测试文件 | 覆盖 |
|-----------|----------|
| `tests/test_api_query_sessions_documents_tasks.py` | Query、search、SSE、sessions、documents |
| `tests/test_api_ingest_queue_metrics.py` | Ingest + 任务列表 |
| `tests/test_api_admin_health.py` | Health + admin 端点 |
| `tests/test_api_kb_attachments_notifications_users.py` | KB、attachments、notifications |
| `tests/test_mcp_http_transport.py` | `/mcp` 挂载 |

---

## 11. 双数据库驱动

| 上下文 | 驱动 | 占位符 |
|---------|--------|-------------|
| FastAPI 处理器 | asyncpg | `$1`, `$2` |
| Celery / 同步 store | psycopg2 | `%s` |

会话与通知 store 为路由提供异步变体；入库/任务路径用同步 store。

---

## 12. 参考文献

- FastAPI: [fastapi.tiangolo.com](https://fastapi.tiangolo.com/)
- SSE specification: [html.spec.whatwg.org/multipage/server-sent-events.html](https://html.spec.whatwg.org/multipage/server-sent-events.html)
- Gao et al., *RAG Survey*, [arXiv:2312.10997](https://arxiv.org/abs/2312.10997)
- OpenTelemetry FastAPI: [opentelemetry.io/docs/instrumentation/python/fastapi](https://opentelemetry.io/docs/instrumentation/python/fastapi/)
- LlamaIndex query engines: [docs.llamaindex.ai/module_guides/deploying/query_engine](https://docs.llamaindex.ai/en/stable/module_guides/deploying/query_engine/)
