# :material-file-document: 编码规范

Eagle-RAG 后端与前端的风格与架构规则。机器可读 Agent 规则：[`AGENTS.md`](https://github.com/fintax-ai/eagle-rag/blob/master/AGENTS.md)。

## Python

| 设置 | 值 |
| --- | --- |
| 版本 | ≥ 3.12（[`pyproject.toml`](https://github.com/fintax-ai/eagle-rag/blob/master/pyproject.toml) 中 `requires-python`） |
| 包管理 | [uv](https://docs.astral.sh/uv/) —— `uv sync`、`uv run …` |
| Linter | Ruff —— `E`、`F`、`I`、`W`、`UP`；行宽 **100** |
| Formatter | Ruff format（同行宽） |
| 类型检查 | 仅对包 `eagle_rag` 运行 mypy |

```bash
task be:lint
task be:format
task be:typecheck
```

### 导入与模块风格

- 库模块使用 `from __future__ import annotations`。
- 导出稳定 API 的公共模块优先显式 `__all__`。
- 重型依赖在函数内惰性导入，保持 API 启动快速（见 `health.py`、retriever 中的模式）。
- 避免循环导入：`telemetry` 不得导入 `api` 或 `ingest`。

### 类型注解

- 公共函数与方法需标注类型；在边界（Celery、LlamaIndex）谨慎使用 `Any`。
- mypy 以 `ignore_missing_imports = true` 运行 —— 仍应标注自有代码。

### 错误处理

- API 路由：抛出带清晰 `detail` 的 `HTTPException`；不向客户端泄露堆栈。
- 探测与管理：优雅降级（空列表、`status=down`），除非 inspect 确实无法运行，否则不用 503。
- Celery 任务：使用 `@with_retry` 或 `retry_on_failure`；不应吞掉应进入死信的异常。

### 注释

- 代码注释与 docstring **仅英文**。
- 不要复述代码（禁止 `# increment i`）。
- 提交代码中无 `TODO`、`FIXME` 或个人备忘。
- 解释非显而易见的业务规则（如 scope filter 的 OR 语义、Knowhere fail-closed）。

## Docstring —— Google 风格

模块、类与公共函数使用 Google 约定。

```python
def get_queue_backlog_series(limit: int = 20) -> list[dict[str, Any]]:
    """Query the most recent ``queue_size`` samples and reshape them into a time series.

    Returns ``list[{"sampled_at": iso_str, "knowhere": float, ...}]`` sorted by
    ``sampled_at`` ASC.

    Args:
        limit: Maximum number of timestamp buckets to return.

    Returns:
        Time series rows; empty list when no samples exist.
    """
```

规则：

- 在 `def` / `class` 下一行使用三引号 `"""`。
- 适用时使用 `Args`、`Returns`、`Raises` 节。
- docstring 内联代码引用使用双反引号。
- 文件顶部模块 docstring 概括用途（见 `eagle_rag/api/health.py`）。

## API 层

- 路由位于 `eagle_rag/api/`；schema 位于 `eagle_rag/api/schemas/`。
- 每个路由声明 `response_model=`。
- 多租户端点接受 `kb_name`，回退到 `settings.kb_name`。
- 无鉴权层（内网部署）—— 未经项目决策勿向核心路由添加 API key。

### Schema

- Pydantic v2 模型；用 `Field(description=...)` 提升 OpenAPI 清晰度。
- `ScopeSelection` 等共享类型放在 `schemas/query.py` 或 `common.py`。
- JSONB 字典：API 模型使用 `dict[str, Any] | None`，与 SQLModel 一致。

## 数据库

- ORM：[`eagle_rag/db/models/`](https://github.com/fintax-ai/eagle-rag/tree/master/eagle_rag/db/models) 中的 SQLModel。
- 迁移：仅 Alembic —— `task db:migrate`。
- **禁止**在 store 或启动钩子中执行 `CREATE TABLE`。

### PostgreSQL JSONB —— `sessions.scope_filter`

[`Session.scope_filter`](https://github.com/fintax-ai/eagle-rag/blob/master/eagle_rag/db/models/sessions.py)：

```python
scope_filter: dict | None = Field(default=None, sa_column=Column(JSONB, nullable=True))
```

**为何用 JSONB**

- Scope 选择是结构化但会演进（`kb_names`、`document_ids`、`tags`），无需大量可空列。
- PostgreSQL JSONB 支持索引（GIN），日后可加路径索引；当前查询按 `session_id` 加载。
- API 将 `ScopeSelection` Pydantic 模型序列化为 `model_dump()` → JSONB；OR 语义在查询时由 `router_engine._resolve_scope_filter` 应用。

**贡献者规则**

- 保持键稳定：`kb_names`、`document_ids`、`tags`（列表）。
- 空过滤 → DB 中为 `None`，而非 `{}`。
- 不要在 JSONB 中存原始 Milvus 表达式 —— 仅存用户选择。

## Celery 任务

- 在 `celery_app.include` 与 `settings.yaml` 的 `task_routes` 中注册。
- 默认装饰器：[`dead_letter.py`](https://github.com/fintax-ai/eagle-rag/blob/master/eagle_rag/tasks/dead_letter.py) 中的 `@with_retry(name="…", queue="…")`。
- 在 kwargs 中传递 `kb_name`、`document_id`、`job_id` 用于追踪与审计。
- 跨服务派发使用 `send_task_with_trace`。
- `acks_late=True` —— 任务须容忍重投递；写入应幂等。

队列并发默认值（[`settings.yaml`](https://github.com/fintax-ai/eagle-rag/blob/master/eagle_rag/settings.yaml)）：

| 队列 | 并发 | 理由 |
| --- | --- | --- |
| `router_queue` | 4 | 快速路由 |
| `knowhere_queue` | 8 | HTTP 绑定 |
| `pixelrag_queue` | 1 | 视觉编码器内存密集 |

## Telemetry

为长操作加仪器：

```python
from eagle_rag.telemetry import trace_span, get_ai_logger

ai_logger = get_ai_logger(__name__)

with trace_span("operation_name"):
    ai_logger.info("event_name", field=value)
```

- 运维消息 → `get_logger`（loguru）。
- 分析事件 → `get_ai_logger`（JSONL）。
- LLM 调用 → `set_llm_span_attributes` 遵循 OpenTelemetry GenAI 语义。

参见 [OpenTelemetry Python 文档](https://opentelemetry.io/docs/languages/python/) 与 [GenAI 约定](https://opentelemetry.io/docs/specs/semconv/gen-ai/)。

## 前端（TypeScript）

| 工具 | 命令 |
| --- | --- |
| 运行时 | Bun |
| 框架 | Next.js 16、React 19 |
| Lint / 格式 | Biome —— `bun run lint`、`bun run format` |
| UI | HeroUI v3、Tailwind v4 |
| i18n | `next-intl` —— 维护 `messages/en.json` 与 `messages/zh.json` |

- **仅亮色主题** —— 不要暗色优先样式。
- 按现有页面的 Next.js 约定划分 server/client 组件。
- API 类型：与 OpenAPI 对齐或手工维护 `lib/` 类型 —— 仓库内暂无 Python 代码生成。

## 配置

- 所有可调项在 [`eagle_rag/settings.yaml`](https://github.com/fintax-ai/eagle-rag/blob/master/eagle_rag/settings.yaml)，使用 `${ENV:-default}`。
- 密钥仅通过环境 / `.env`（gitignore）。
- 非 env 标志使用 YAML 布尔字面量（`true`/`false`），避免字符串注入（见 `knowhere.parsing_params.ocr_enabled`）。

## AGENTS.md 约束与理由 {#agentsmd-constraints-and-rationale}

| 约束 | 理由 |
| --- | --- |
| **Knowhere 外部 HTTP** | 重型语义解析进程外运行；官方 SDK + 作业 API；在 `docker/knowhere-self-hosted/` 独立发布周期 |
| **仅 PixelRAG 库** | 消除 pixelrag-serve 运维负担；向量直写 Milvus `eagle_visual`；Chrome + torch 隔离在 `worker-pixelrag` |
| **无 FAISS / pixelrag-serve** | 视觉 ANN 与标量过滤在 Milvus；摄入不得调用已移除的 PixelRAG 服务 API |
| **仅 DeepSeek + Qwen** | LLM/VLM/嵌入/重排单一厂商栈；减少适配面与密钥管理 |
| **无金融硬编码** | `kb_name` 多租户产品 —— 领域逻辑在 KB 内容，不在代码分支 |
| **`source_type` 仅元数据** | 路由用格式 + PDF 探测；避免文件名关键词误导路由 |
| **四个融合锚点字段** | 将视觉 tile 链接到 Knowhere 骨架，用于引用与父文档检索 |
| **`scope_filter` OR 并集** | 用户选择多个 tag/KB/文档时期望更广召回 |
| **附件惰性解析、不写 Milvus** | 临时聊天上下文 —— 与 KB 摄入生命周期不同 |
| **MCP 工具注册表** | `TOOL_DEFINITIONS` 保持 HTTP `/mcp/tools` 与 FastMCP 同步 |
| **不主动写文档** | 除非行为变更，避免文档漂移 |

完整矩阵：[`AGENTS.md`](https://github.com/fintax-ai/eagle-rag/blob/master/AGENTS.md)。

## 已移除模式 —— 勿重新引入

| 已移除 | 替代 |
| --- | --- |
| LibreOffice | Knowhere 原生 Office 解析 |
| pixelrag-serve | worker 中 `pixelrag_render` + `pixelrag_embed` |
| FAISS | Milvus `eagle_visual` |
| OpenAI / Cohere 适配器 | 经 LlamaIndex 包的 DashScope + DeepSeek |

## 文件组织

- 每个模块一个主职责（如 `admin/metrics.py` 仅队列采样）。
- 路由保持精简 —— 委托给 store、engine、适配器。
- 测试在 `tests/test_<area>_*.py` 中镜像 `eagle_rag` 包名。

## 提交前习惯

推送前：

```bash
task be:lint && task be:typecheck && task be:test
cd frontend && bun run lint
```

## 相关

- [贡献 —— PR 清单](contributing.md#pr-checklist)
- [测试](testing.md)
- [项目结构](project-structure.md)
