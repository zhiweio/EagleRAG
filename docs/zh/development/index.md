# :material-code-braces: 开发

面向 Eagle-RAG 贡献工程师的指南。后端为 Python 3.12+（[`eagle_rag/`](https://github.com/fintax-ai/eagle-rag/tree/master/eagle_rag)）；前端为 Bun 上的 Next.js 16（[`frontend/`](https://github.com/fintax-ai/eagle-rag/tree/master/frontend)）。

人与编码 Agent 的规范约束：[`AGENTS.md`](https://github.com/fintax-ai/eagle-rag/blob/master/AGENTS.md)。产品概览：[`README.md`](https://github.com/fintax-ai/eagle-rag/blob/master/README.md)。

## 首次设置

```bash
git clone https://github.com/fintax-ai/eagle-rag.git
cd eagle-rag
task setup          # .env, knowhere/.env, knowhere-net, uv sync, bun install
# Edit .env — VLM_API_KEY, LLM_API_KEY, embedding keys, etc.
task up             # Docker full stack (knowhere + eagle-rag dev)
task db:migrate     # Alembic against running Postgres
```

本地混合（基础设施在 Docker，代码在宿主机）：

```bash
task knowhere:up
docker compose up -d postgres redis minio milvus etcd
task be:api         # terminal 1
task be:worker      # terminal 2
task fe:dev         # terminal 3
```

## 文档地图

| 页面 | 内容 |
| --- | --- |
| [项目结构](project-structure.md) | 目录布局、模块依赖图 |
| [贡献](contributing.md) | PR 流程、评审清单、CI 门禁 |
| [编码规范](coding-standards.md) | Python/TS 风格、docstring、AGENTS.md 理由 |
| [测试](testing.md) | pytest 布局、fixtures、单元 vs 集成 |

运维（Docker、可观测性、备份）：[docs/en/ops/](../ops/index.md)。

## 工具链

| 工具 | 角色 | 安装 |
| --- | --- | --- |
| [uv](https://docs.astral.sh/uv/) | Python 依赖 + venv | `curl -LsSf …` 或 brew |
| [Bun](https://bun.sh/) | 前端包管理 | brew / curl |
| [Task](https://taskfile.dev/) | 任务运行器 | brew / go install |
| Docker Compose | 全栈 | Docker Desktop / engine |

后端开发依赖（`uv sync --group dev`）：

- `pytest`、`pytest-asyncio`
- `ruff`、`mypy`

## 质量门禁（PR 前运行）

```bash
task be:lint        # ruff check
task be:format      # ruff format
task be:typecheck   # mypy eagle_rag
task be:test        # pytest

cd frontend && bun run lint && bun run format
```

五项均应通过。见[贡献 — PR 清单](contributing.md#pr-checklist)。

## 架构约束（摘要）

来自 [`AGENTS.md`](https://github.com/fintax-ai/eagle-rag/blob/master/AGENTS.md)：

| 主题 | 规则 |
| --- | --- |
| 解析器 | Knowhere HTTP `:5005` 经官方 SDK；仅 PixelRAG 进程内库 |
| 已移除 | 无 LibreOffice、pixelrag-serve、FAISS、OpenAI、Cohere 适配器 |
| 模型 | 仅 DeepSeek + Qwen（LLM、VLM、嵌入、重排） |
| 多租户 | 传播 `kb_name`；去重 `(sha256, kb_name)` |
| DB | SQLModel + Alembic；store 中无 DDL |
| API | 无鉴权（内网）；路由使用 `response_model` |
| Celery | 三队列；`@with_retry` + 死信 |

完整理由：[编码规范 — AGENTS.md](coding-standards.md#agentsmd-constraints-and-rationale)。

## 配置

单一来源：[`eagle_rag/settings.yaml`](https://github.com/fintax-ai/eagle-rag/blob/master/eagle_rag/settings.yaml) 含 `${ENV:-default}` 占位符，由 [`eagle_rag/config.py`](https://github.com/fintax-ai/eagle-rag/blob/master/eagle_rag/config.py) 加载。

新增设置时：

1. 在 YAML 添加带 env 占位符的键。
2. 在 `config.py` 扩展 pydantic 模型。
3. 若影响行为则更新 README / 架构文档。
4. 切勿在 YAML 提交密钥 —— 用 `.env`。

## 数据库工作流

```bash
# After changing eagle_rag/db/models/
uv run alembic revision --autogenerate -m "describe change"
task db:migrate
```

部署迁移：在 CI/CD 或容器入口运行 `task db:migrate` —— 不在 store import 时执行。

## API 开发

- Schema：[`eagle_rag/api/schemas/`](https://github.com/fintax-ai/eagle-rag/tree/master/eagle_rag/api/schemas)
- 路由挂载于 [`eagle_rag/api/app.py`](https://github.com/fintax-ai/eagle-rag/blob/master/eagle_rag/api/app.py)
- OpenAPI：API 运行时 `http://localhost:8000/docs`

流式端点：

- `POST /query/stream` —— SSE（`session`、`step`、`sources`、`token`、`done`）
- `POST /search/stream` —— 仅检索流

## 前端开发

```bash
cd frontend
bun run dev       # :3000
bun run lint      # Biome
bun run format
```

技术栈：Next.js 16、React 19、HeroUI v3、Tailwind v4、`next-intl`（zh/en），**仅浅色主题**。

`NEXT_PUBLIC_API_BASE` 须指向浏览器可访问的 API 源。

## MCP 工具

注册新工具于：

1. [`eagle_rag/api/mcp_server.py`](https://github.com/fintax-ai/eagle-rag/blob/master/eagle_rag/api/mcp_server.py) —— `@mcp.tool()` 处理器
2. `TOOL_DEFINITIONS` 列表（镜像 `/mcp/tools` 的 OpenAPI）
3. `tests/test_mcp_*.py` 下的测试

经独立 MCP HTTP 暴露时用 `@with_metrics("tool_name")` 装饰。

## Celery 任务开发

任务模块显式列入 [`celery_app.py`](https://github.com/fintax-ai/eagle-rag/blob/master/eagle_rag/tasks/celery_app.py) `include=[...]`。

模式：

```python
from eagle_rag.tasks.dead_letter import with_retry

@with_retry(name="eagle_rag.tasks.my_task", queue="knowhere_queue")
def my_task(self, document_id: str, kb_name: str) -> None:
    ...
```

带 trace 传播分发：

```python
from eagle_rag.telemetry import send_task_with_trace

send_task_with_trace("eagle_rag.tasks.my_task", queue="knowhere_queue", kwargs={...})
```

Docker dev 中编辑任务代码后重启 workers（Celery 无自动重载）：

```bash
docker compose restart worker-router worker-knowhere worker-pixelrag
```

## 新代码中的遥测

```python
from eagle_rag.telemetry import get_logger, get_ai_logger, trace_span, bind_context

logger = get_logger(__name__)
ai_logger = get_ai_logger(__name__)

with trace_span("my_operation"):
    ai_logger.info("step_done", key=value)
```

见[可观测性](../ops/observability.md)。

## 文档站

```bash
task docs:serve     # http://127.0.0.1:8001
task docs:build     # mkdocs build --strict
```

编辑 `docs/en/` 与 `docs/zh/`；导航在 `mkdocs.yml`。除非被要求，勿创建 markdown 文档（[`AGENTS.md`](https://github.com/fintax-ai/eagle-rag/blob/master/AGENTS.md)）。

## 架构变更检查清单

行为变更时同步：

- [`README.md`](https://github.com/fintax-ai/eagle-rag/blob/master/README.md)
- [`AGENTS.md`](https://github.com/fintax-ai/eagle-rag/blob/master/AGENTS.md)
- `docs/en/architecture/multimodal-fusion.md`（+ zh）
- `eagle_rag/settings.yaml`

## 获取帮助

| 问题 | 位置 |
| --- | --- |
| ingest 如何路由？ | `eagle_rag/ingest/router.py`，docs/backend |
| Milvus schema | `eagle_rag/index/milvus_*_store.py` |
| 运维 / 探测 | [docs/en/ops/](../ops/index.md) |
| Agent 规则 | [`AGENTS.md`](https://github.com/fintax-ai/eagle-rag/blob/master/AGENTS.md) |
