# :material-test-tube: 测试

Eagle-RAG 的 Pytest 套件。测试在 [`tests/`](https://github.com/fintax-ai/eagle-rag/tree/master/tests)；配置在 [`pyproject.toml`](https://github.com/fintax-ai/eagle-rag/blob/master/pyproject.toml) `[tool.pytest.ini_options]`。

```bash
task be:test          # uv run pytest
uv run pytest -k mcp  # subset
uv run pytest -v tests/test_api_admin_health.py
```

## Pytest 配置

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- `pytest-asyncio` 在多数情况下无需手动 marker 即可运行 async 测试。
- 开发依赖：`uv sync --group dev`。

## Testcontainers

**本仓库不使用 [testcontainers](https://testcontainers.com/)**。`pyproject.toml` 无 `testcontainers` 依赖，CI 中无基于容器的集成 harness。

与真实 Postgres、Milvus、Redis、MinIO 的集成通过 `task up` 或临时脚本手动完成 —— 不在默认 pytest 运行中。

## 测试策略概览

```mermaid
quadrantChart
    title Test pyramid (Eagle-RAG)
    x-axis Low fidelity --> High fidelity
    y-axis Fast --> Slow
    quadrant-1 Manual Docker E2E
    quadrant-2 Integration (sparse)
    quadrant-3 Unit (majority)
    quadrant-4 Telemetry / MCP contract
    Unit tests: [0.25, 0.75]
    API contract tests: [0.45, 0.65]
    Mocked retrieval: [0.35, 0.7]
    Manual stack E2E: [0.9, 0.2]
```

| 层 | 运行内容 | 外部依赖 |
| --- | --- | --- |
| **单元** | 纯逻辑、带 mock 的适配器 | 无 |
| **API 契约** | FastAPI TestClient / async client | Mock store |
| **组件** | 带 `MagicMock` 的 Router engine、retriever | 无 Milvus |
| **集成（手动）** | 对 Docker 栈 ingest + query | 真实服务 |
| **E2E（手动）** | 前端 + API + workers | 全 compose |

默认 `pytest` 目标：**仅单元 + API 契约**。

## 共享 fixtures —— `conftest.py`

[`tests/conftest.py`](https://github.com/fintax-ai/eagle-rag/blob/master/tests/conftest.py) 定义 **autouse** fixtures：

### `_reset_telemetry_state`

在**每个**测试前后运行。

重置：

- `eagle_rag.telemetry._configured`
- `logging_setup._configured`、`_enabled`、`_ai_logger_factory`
- `context._enabled`、contextvars dict
- `tracing._tracer`、`_tracing_enabled`
- structlog `contextvars`
- stdlib logger `eagle_ai_telemetry` handlers

**原因：** 遥测一次配置全局状态；不重置会导致 `test_telemetry_*` 与追踪测试顺序依赖失败。OpenTelemetry `TracerProvider` 为进程全局 —— 测试仅重置模块 `_tracer` 引用，使 `trace_span` 在重新配置前 no-op。

### `_kb_registered`

Patch：

```python
patch("eagle_rag.kb.registry.kb_exists_sync", return_value=True)
patch("eagle_rag.kb.registry.get_pdf_ratio_sync", return_value=None)
```

**原因：** Ingest 与查询测试不应要求 live Postgres `knowledge_bases` 行。

## 测试文件地图

| 文件 | 焦点 | 风格 |
| --- | --- | --- |
| `test_api_admin_health.py` | `/health`、`/admin/*` 探测 | Async client、mock 后端 |
| `test_api_query_sessions_documents_tasks.py` | 查询、会话、文档 | API 契约 |
| `test_api_ingest_queue_metrics.py` | Ingest API、指标 | API + mocks |
| `test_api_kb_attachments_notifications_users.py` | KB CRUD、附件 | API 契约 |
| `test_router_generation.py` | `EagleRouterQueryEngine`、VLM mock | 单元 + mock retriever |
| `test_retrievers.py` | Retriever 行为 | Mock Milvus |
| `test_ingest_smoke.py` | 路由分发冒烟 | Mocks |
| `test_ingest_assets.py` | 资源路径 | 单元 |
| `test_ingest_url_validation.py` | URL 预取规则 | 单元 |
| `test_knowhere_sections.py` | 章节树解析 | 单元 / fixture 文件 |
| `test_knowhere_visual_chunks.py` | 视觉分块分发 | Mock |
| `test_attachments_parser.py` | 附件惰性解析 | 单元 |
| `test_milvus_structure_fetch.py` | 文档结构 API | Mock Milvus |
| `test_mcp_server.py`（经 `test_mcp_*`） | MCP 工具、auth、cache、HTTP | 混合 |
| `test_mcp_metrics.py` | Prometheus `with_metrics` | 单元 |
| `test_mcp_http_transport.py` | Streamable HTTP | Async |
| `test_mcp_resilience.py` | 断路器、重试 | 单元 |
| `test_mcp_config.py` | MCP 设置 | 单元 |
| `test_mcp_auth.py` | Token auth | 单元 |
| `test_mcp_cache.py` | 工具结果缓存 | 单元 |
| `test_telemetry_logging.py` | loguru / structlog 设置 | 单元、tmp 路径 |
| `test_telemetry_tracing.py` | `trace_span`、middleware | 单元 |
| `test_telemetry_hotspots.py` | 热路径 span 覆盖 | 单元 / 冒烟 |

## 单元 vs 集成分类

### 单元测试

- 无网络；无 Docker。
- `unittest.mock.patch`、`MagicMock`、`pytest.fixture` 小数据。
- 示例：URL 校验器、路由启发式、指标状态推断（`_infer_status`）、死信载荷形状、schema 校验。

### API 契约测试

- 对 `app` 用 FastAPI `TestClient` 或 `httpx.AsyncClient`。
- 在 import 边界 patch 外部服务（如 `MilvusClient`、`asyncpg`、Redis）。
- 验证状态码、`response_model` 形状、错误处理。

### 集成测试（非正式）

今日无单独 pytest marker。这些**需要运行服务**：

| 场景 | 如何运行 |
| --- | --- |
| 完整 ingest → Milvus | `task up`，经 API 上传，查 `/admin/milvus` |
| Knowhere 解析 | `task knowhere:up`，真实文档 |
| PixelRAG 视觉 | 带 GPU/CPU torch 的 `worker-pixelrag` |
| 查询流式 | `curl -N` `/query/stream` |

若引入未来自动化集成测试，用 `@pytest.mark.integration` 标记 —— CI 默认跳过。

## Mock 模式

### Retriever

`test_router_generation.py` 注入 mock：

```python
mock_text = MagicMock()
mock_text.retrieve.return_value = [node1, node2]
engine = EagleRouterQueryEngine(text_retriever=mock_text, visual_retriever=mock_visual)
```

### VLM / DashScope

Patch `dashscope.MultiModalConversation.call` 或注入带 `complete` / stream 迭代器的 `MagicMock`。

### Milvus

Patch `eagle_rag.index.milvus_text_store` / `milvus_visual_store` 模块函数或调用点的 `MilvusClient`。

### Knowhere

在 `knowhere_adapter` 测试中 patch `knowhere` SDK 或 HTTP 客户端 —— pytest 中无 live `:5005`。

### Celery

通过调用底层函数同步测任务，或仅在测试中显式设 `celery_app.conf.task_always_eager = True`（今日非全局）。

## Async 测试

`asyncio_mode = "auto"` —— async def 测试在事件循环中运行，多数 pytest-asyncio 版本无需 `@pytest.mark.asyncio`。

管理健康测试对 lifespan 管理的 app 使用 async HTTP。

## 编写新测试

1. 文件命名为 `tests/test_<domain>_<feature>.py`。
2. 每个测试函数名偏好单一行为：`test_query_scope_filter_persists_to_session`。
3. 使用 autouse 遥测重置 —— 除非用 tmp 日志路径，勿调用 `configure_telemetry` 而不清理。
4. 在**最低稳定边界** patch（被测模块 import 自处）。
5. 无真实 API 密钥 —— 用 env patch 或空密钥 + mock 上游。

骨架示例：

```python
from unittest.mock import patch
import pytest

@pytest.mark.asyncio
async def test_my_endpoint(client):
    with patch("eagle_rag.some.module.external_call", return_value={"ok": True}):
        resp = await client.get("/my-path")
    assert resp.status_code == 200
```

## 覆盖缺口（有意）

| 领域 | 为何未全自动化 |
| --- | --- |
| Milvus ANN 质量 | 需要向量与调参 |
| Knowhere 作业轮询 | 长时 HTTP 集成 |
| Chrome PixelRAG 渲染 | CI 中重型依赖 |
| OpenTelemetry OTLP 导出 | 手动 collector 验证 |

## 遥测测试说明

- `test_telemetry_logging.py` 使用临时日志目录。
- 重置 fixture 清除 loguru handlers —— 若添加配置遥测的测试，对 `op_log_file` / `ai_log_file` 用 `tmp_path`。
- TracerProvider 无法全局 unset；测试在测试内运行 `configure_tracing` 时断言 span 行为。

## MCP 指标测试

`test_mcp_metrics.py` 验证：

- `with_metrics` 递增 `mcp_tool_calls_total{status}`
- 断路器状态 gauge 更新
- 缓存命中将 status 覆盖为 `cache_hit`

进程内使用 prometheus_client registry（无需 scrape 服务器）。

## 运行子集

```bash
uv run pytest tests/test_telemetry_tracing.py -v
uv run pytest -k "scope_filter"
uv run pytest --tb=short -q
```

## 维护者 CI 建议

最小 CI 作业应运行：

```bash
uv sync --group dev
uv run ruff check
uv run ruff format --check
uv run mypy eagle_rag
uv run pytest
```

前端：

```bash
cd frontend && bun install && bun run lint
```

## 手动验证清单（发布）

大范围 ingest 或检索变更后：

1. `task be:test` 绿。
2. `task up` —— `task health` ok。
3. 上传样例 PDF（文本 + 扫描）。
4. `POST /query` 与 `/query/stream`。
5. `GET /admin/celery` —— 队列排空。
6. 查 `logs/ai_telemetry.jsonl` 中 `query_completed`。

## 相关

- [贡献 — PR 清单](contributing.md#pr-checklist)
- [编码规范](coding-standards.md)
- [运维排障](../ops/troubleshooting.md)
