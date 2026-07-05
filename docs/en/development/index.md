# :material-code-braces: Development

Guide for engineers contributing to Eagle-RAG. The backend is Python 3.12+ ([`eagle_rag/`](https://github.com/fintax-ai/eagle-rag/tree/master/eagle_rag)); the frontend is Next.js 16 with Bun ([`frontend/`](https://github.com/fintax-ai/eagle-rag/tree/master/frontend)).

Canonical constraints for humans and coding agents: [`AGENTS.md`](https://github.com/fintax-ai/eagle-rag/blob/master/AGENTS.md). Product overview: [`README.md`](https://github.com/fintax-ai/eagle-rag/blob/master/README.md).

## First-time setup

```bash
git clone https://github.com/fintax-ai/eagle-rag.git
cd eagle-rag
task setup          # .env, knowhere/.env, knowhere-net, uv sync, bun install
# Edit .env — VLM_API_KEY, LLM_API_KEY, embedding keys, etc.
task up             # Docker full stack (knowhere + eagle-rag dev)
task db:migrate     # Alembic against running Postgres
```

Local hybrid (infra in Docker, code on host):

```bash
task knowhere:up
docker compose up -d postgres redis minio milvus etcd
task be:api         # terminal 1
task be:worker      # terminal 2
task fe:dev         # terminal 3
```

## Documentation map

| Page | Contents |
| --- | --- |
| [Project structure](project-structure.md) | Directory layout, module dependency graph |
| [Contributing](contributing.md) | PR workflow, review checklist, CI gates |
| [Coding standards](coding-standards.md) | Python/TS style, docstrings, AGENTS.md rationale |
| [Testing](testing.md) | pytest layout, fixtures, unit vs integration |

Operations (Docker, observability, backup): [docs/en/ops/](../ops/index.md).

## Toolchain

| Tool | Role | Install |
| --- | --- | --- |
| [uv](https://docs.astral.sh/uv/) | Python deps + venv | `curl -LsSf …` or brew |
| [Bun](https://bun.sh/) | Frontend package manager | brew / curl |
| [Task](https://taskfile.dev/) | Task runner | brew / go install |
| Docker Compose | Full stack | Docker Desktop / engine |

Backend dev dependencies (`uv sync --group dev`):

- `pytest`, `pytest-asyncio`
- `ruff`, `mypy`

## Quality gates (run before PR)

```bash
task be:lint        # ruff check
task be:format      # ruff format
task be:typecheck   # mypy eagle_rag
task be:test        # pytest

cd frontend && bun run lint && bun run format
```

All five should pass. See [Contributing — PR checklist](contributing.md#pr-checklist).

## Architecture constraints (summary)

From [`AGENTS.md`](https://github.com/fintax-ai/eagle-rag/blob/master/AGENTS.md):

| Topic | Rule |
| --- | --- |
| Parsers | Knowhere HTTP `:5005` via official SDK; PixelRAG in-process library only |
| Removed | No LibreOffice, pixelrag-serve, FAISS, OpenAI, Cohere adapters |
| Models | DeepSeek + Qwen only (LLM, VLM, embeddings, rerank) |
| Multi-tenancy | Propagate `kb_name`; dedup `(sha256, kb_name)` |
| DB | SQLModel + Alembic; no DDL in stores |
| API | No auth (intranet); `response_model` on routers |
| Celery | Three queues; `@with_retry` + dead letter |

Full rationale: [Coding standards — AGENTS.md](coding-standards.md#agentsmd-constraints-and-rationale).

## Configuration

Single source: [`eagle_rag/settings.yaml`](https://github.com/fintax-ai/eagle-rag/blob/master/eagle_rag/settings.yaml) with `${ENV:-default}` placeholders, loaded by [`eagle_rag/config.py`](https://github.com/fintax-ai/eagle-rag/blob/master/eagle_rag/config.py).

When adding a setting:

1. Add YAML key with env placeholder.
2. Extend pydantic model in `config.py`.
3. Document in README / architecture docs if behaviour-facing.
4. Never commit secrets in YAML — use `.env`.

## Database workflow

```bash
# After changing eagle_rag/db/models/
uv run alembic revision --autogenerate -m "describe change"
task db:migrate
```

Deploy migrations: `task db:migrate` in CI/CD or container entrypoint — not at import time in stores.

## API development

- Schemas: [`eagle_rag/api/schemas/`](https://github.com/fintax-ai/eagle-rag/tree/master/eagle_rag/api/schemas)
- Routers mounted in [`eagle_rag/api/app.py`](https://github.com/fintax-ai/eagle-rag/blob/master/eagle_rag/api/app.py)
- OpenAPI: `http://localhost:8000/docs` when API running

Streaming endpoints:

- `POST /query/stream` — SSE (`session`, `step`, `sources`, `token`, `done`)
- `POST /search/stream` — retrieval-only stream

## Frontend development

```bash
cd frontend
bun run dev       # :3000
bun run lint      # Biome
bun run format
```

Stack: Next.js 16, React 19, HeroUI v3, Tailwind v4, `next-intl` (zh/en), **light theme only**.

`NEXT_PUBLIC_API_URL` must point at the API origin the browser can reach.

## MCP tools

Register new tools in:

1. [`eagle_rag/api/mcp_server.py`](https://github.com/fintax-ai/eagle-rag/blob/master/eagle_rag/api/mcp_server.py) — `@mcp.tool()` handler
2. `TOOL_DEFINITIONS` list (mirrors OpenAPI for `/mcp/tools`)
3. Tests under `tests/test_mcp_*.py`

Decorate with `@with_metrics("tool_name")` when exposing via standalone MCP HTTP.

## Celery task development

Task modules are explicitly included in [`celery_app.py`](https://github.com/fintax-ai/eagle-rag/blob/master/eagle_rag/tasks/celery_app.py) `include=[...]`.

Pattern:

```python
from eagle_rag.tasks.dead_letter import with_retry

@with_retry(name="eagle_rag.tasks.my_task", queue="knowhere_queue")
def my_task(self, document_id: str, kb_name: str) -> None:
    ...
```

Dispatch with trace propagation:

```python
from eagle_rag.telemetry import send_task_with_trace

send_task_with_trace("eagle_rag.tasks.my_task", queue="knowhere_queue", kwargs={...})
```

After editing task code in Docker dev, restart workers (no Celery autoreload):

```bash
docker compose restart worker-router worker-knowhere worker-pixelrag
```

## Telemetry in new code

```python
from eagle_rag.telemetry import get_logger, get_ai_logger, trace_span, bind_context

logger = get_logger(__name__)
ai_logger = get_ai_logger(__name__)

with trace_span("my_operation"):
    ai_logger.info("step_done", key=value)
```

See [Observability](../ops/observability.md).

## Docs site

```bash
task docs:serve     # http://127.0.0.1:8001
task docs:build     # mkdocs build --strict
```

Edit `docs/en/` and `docs/zh/`; navigation in `mkdocs.yml`. Do not create markdown docs unless requested ([`AGENTS.md`](https://github.com/fintax-ai/eagle-rag/blob/master/AGENTS.md)).

## Architecture change checklist

When behaviour changes, sync:

- [`README.md`](https://github.com/fintax-ai/eagle-rag/blob/master/README.md)
- [`AGENTS.md`](https://github.com/fintax-ai/eagle-rag/blob/master/AGENTS.md)
- `docs/en/architecture/multimodal-fusion.md` (+ zh)
- `eagle_rag/settings.yaml`

## Getting help

| Question | Where |
| --- | --- |
| How does ingest route? | `eagle_rag/ingest/router.py`, docs/backend |
| Milvus schema | `eagle_rag/index/milvus_*_store.py` |
| Ops / probes | [docs/en/ops/](../ops/index.md) |
| Agent rules | [`AGENTS.md`](https://github.com/fintax-ai/eagle-rag/blob/master/AGENTS.md) |
