# :material-file-document: Coding standards

Style and architectural rules for Eagle-RAG backend and frontend. Machine-readable agent rules: [`AGENTS.md`](https://github.com/fintax-ai/eagle-rag/blob/master/AGENTS.md).

## Python

| Setting | Value |
| --- | --- |
| Version | ≥ 3.12 (`requires-python` in [`pyproject.toml`](https://github.com/fintax-ai/eagle-rag/blob/master/pyproject.toml)) |
| Package manager | [uv](https://docs.astral.sh/uv/) — `uv sync`, `uv run …` |
| Linter | Ruff — `E`, `F`, `I`, `W`, `UP`; line length **100** |
| Formatter | Ruff format (same line length) |
| Type checker | mypy on package `eagle_rag` only |

```bash
task be:lint
task be:format
task be:typecheck
```

### Import and module style

- Use `from __future__ import annotations` in library modules.
- Prefer explicit `__all__` on public modules when exporting a stable API.
- Lazy-import heavy deps inside functions when needed to keep API startup fast (pattern in `health.py`, retrievers).
- Avoid circular imports: `telemetry` must not import `api` or `ingest`.

### Type hints

- Public functions and methods are typed; use `Any` sparingly at boundaries (Celery, LlamaIndex).
- mypy runs with `ignore_missing_imports = true` — still type your own code.

### Error handling

- API routes: raise `HTTPException` with clear `detail`; do not leak stack traces to clients.
- Probes and admin: degrade gracefully (empty lists, `status=down`) instead of 503 unless inspect truly cannot run.
- Celery tasks: use `@with_retry` or `retry_on_failure`; never swallow exceptions that should dead-letter.

### Comments

- **English only** in code comments and docstrings.
- Do not restate the code (`# increment i` forbidden).
- No `TODO`, `FIXME`, or personal notes in committed code.
- Explain non-obvious business rules (e.g. scope filter OR semantics, fail-closed Knowhere).

## Docstrings — Google style

Use Google convention for modules, classes, and public functions.

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

Rules:

- Triple-quoted `"""` on the line after `def` / `class`.
- `Args`, `Returns`, `Raises` sections when applicable.
- Use double backticks for inline code references in docstrings.
- Module docstring at top of file summarises purpose (see `eagle_rag/api/health.py`).

## API layer

- Routers live under `eagle_rag/api/`; schemas under `eagle_rag/api/schemas/`.
- Every route declares `response_model=`.
- Multi-tenant endpoints accept `kb_name` with fallback to `settings.kb_name`.
- No authentication layer (intranet deployment) — do not add API keys to core routes without project decision.

### Schemas

- Pydantic v2 models; use `Field(description=...)` for OpenAPI clarity.
- `ScopeSelection` and similar shared types belong in `schemas/query.py` or `common.py`.
- JSONB-backed dicts: `dict[str, Any] | None` on API models matching SQLModel.

## Database

- ORM: SQLModel in [`eagle_rag/db/models/`](https://github.com/fintax-ai/eagle-rag/tree/master/eagle_rag/db/models).
- Migrations: Alembic only — `task db:migrate`.
- **Never** run `CREATE TABLE` from stores or startup hooks.

### PostgreSQL JSONB — `sessions.scope_filter`

[`Session.scope_filter`](https://github.com/fintax-ai/eagle-rag/blob/master/eagle_rag/db/models/sessions.py):

```python
scope_filter: dict | None = Field(default=None, sa_column=Column(JSONB, nullable=True))
```

**Why JSONB**

- Scope selection is structured but evolves (`kb_names`, `document_ids`, `tags`) without wide nullable columns.
- PostgreSQL JSONB supports indexing (GIN) if we add path indexes later; current queries load by `session_id`.
- API serialises `ScopeSelection` Pydantic model → `model_dump()` → JSONB; OR semantics applied at query time in `router_engine._resolve_scope_filter`.

**Contributor rules**

- Keep keys stable: `kb_names`, `document_ids`, `tags` (lists).
- Empty filter → `None` in DB, not `{}`.
- Do not store Milvus expressions raw in JSONB — store user selections only.

## Celery tasks

- Register in `celery_app.include` and `settings.yaml` `task_routes`.
- Default decorator: `@with_retry(name="…", queue="…")` from [`dead_letter.py`](https://github.com/fintax-ai/eagle-rag/blob/master/eagle_rag/tasks/dead_letter.py).
- Pass `kb_name`, `document_id`, `job_id` in kwargs for tracing and audit.
- Dispatch cross-service with `send_task_with_trace`.
- `acks_late=True` — tasks must tolerate redelivery; make writes idempotent.

Queue concurrency defaults ([`settings.yaml`](https://github.com/fintax-ai/eagle-rag/blob/master/eagle_rag/settings.yaml)):

| Queue | Concurrency | Rationale |
| --- | --- | --- |
| `router_queue` | 4 | Fast routing |
| `knowhere_queue` | 8 | HTTP-bound |
| `pixelrag_queue` | 1 | Memory-bound visual encoder |

## Telemetry

Instrument long operations:

```python
from eagle_rag.telemetry import trace_span, get_ai_logger

ai_logger = get_ai_logger(__name__)

with trace_span("operation_name"):
    ai_logger.info("event_name", field=value)
```

- Ops messages → `get_logger` (loguru).
- Analytics events → `get_ai_logger` (JSONL).
- LLM calls → `set_llm_span_attributes` for OpenTelemetry GenAI semantics.

See [OpenTelemetry Python docs](https://opentelemetry.io/docs/languages/python/) and [GenAI conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/).

## Frontend (TypeScript)

| Tool | Command |
| --- | --- |
| Runtime | Bun |
| Framework | Next.js 16, React 19 |
| Lint / format | Biome — `bun run lint`, `bun run format` |
| UI | HeroUI v3, Tailwind v4 |
| i18n | `next-intl` — maintain `messages/en.json` and `messages/zh.json` |

- **Light theme only** — no dark-mode-first styling.
- Prefer server/client component split per Next.js conventions in existing pages.
- API types: align with OpenAPI or hand-maintained types in `lib/` — no Python codegen in repo today.

## Configuration

- All tunables in [`eagle_rag/settings.yaml`](https://github.com/fintax-ai/eagle-rag/blob/master/eagle_rag/settings.yaml) with `${ENV:-default}`.
- Secrets only via environment / `.env` (gitignored).
- Boolean YAML literals (`true`/`false`) for non-env flags to avoid string injection (see `knowhere.parsing_params.ocr_enabled`).

## AGENTS.md constraints and rationale {#agentsmd-constraints-and-rationale}

| Constraint | Rationale |
| --- | --- |
| **Knowhere external HTTP** | Heavy semantic parsing out-of-process; official SDK + job API; independent release cycle in `docker/knowhere-self-hosted/` |
| **PixelRAG library only** | Eliminates pixelrag-serve ops burden; vectors go straight to Milvus `eagle_visual`; Chrome + torch isolated on `worker-pixelrag` |
| **No FAISS / pixelrag-serve** | Visual ANN and scalar filters live in Milvus; ingest must not call removed PixelRAG server APIs |
| **DeepSeek + Qwen only** | Single vendor stack for LLM/VLM/embed/rerank; reduces adapter surface and key management |
| **No finance hardcoding** | `kb_name` multi-tenant product — domain logic belongs in KB content, not code branches |
| **`source_type` metadata only** | Routing uses format + PDF probe; prevents misleading routes from filename keywords |
| **Four fusion anchor fields** | Links visual tiles to Knowhere skeleton for citation and parent-document retrieval |
| **`scope_filter` OR union** | Users expect broader recall when selecting multiple tags/KBs/docs |
| **Attachments lazy parse, no Milvus** | Ephemeral chat context — different lifecycle from KB ingest |
| **MCP tools registry** | `TOOL_DEFINITIONS` keeps HTTP `/mcp/tools` and FastMCP in sync |
| **No proactive docs** | Avoid doc drift unless behaviour changes |

Full matrix: [`AGENTS.md`](https://github.com/fintax-ai/eagle-rag/blob/master/AGENTS.md).

## Removed patterns — do not reintroduce

| Removed | Replacement |
| --- | --- |
| LibreOffice | Knowhere native Office parsing |
| pixelrag-serve | `pixelrag_render` + `pixelrag_embed` in worker |
| FAISS | Milvus `eagle_visual` |
| OpenAI / Cohere adapters | DashScope + DeepSeek via LlamaIndex packages |

## File organisation

- One primary concern per module (e.g. `admin/metrics.py` for queue sampling only).
- Keep routers thin — delegate to stores, engines, adapters.
- Tests mirror `eagle_rag` package names in `tests/test_<area>_*.py`.

## Pre-commit habit

Before push:

```bash
task be:lint && task be:typecheck && task be:test
cd frontend && bun run lint
```

## Related

- [Contributing — PR checklist](contributing.md#pr-checklist)
- [Testing](testing.md)
- [Project structure](project-structure.md)
