# :material-test-tube: Testing

Pytest suite for Eagle-RAG. Tests live in [`tests/`](https://github.com/fintax-ai/eagle-rag/tree/master/tests); configuration in [`pyproject.toml`](https://github.com/fintax-ai/eagle-rag/blob/master/pyproject.toml) `[tool.pytest.ini_options]`.

```bash
task be:test          # uv run pytest
uv run pytest -k mcp  # subset
uv run pytest -v tests/test_api_admin_health.py
```

## Pytest configuration

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- `pytest-asyncio` runs async tests without manual markers in most cases.
- Dev deps: `uv sync --group dev`.

## Testcontainers

**Eagle-RAG does not use [testcontainers](https://testcontainers.com/)** in this repository. There is no `testcontainers` dependency in `pyproject.toml` and no container-based integration harness in CI.

Integration with real Postgres, Milvus, Redis, or MinIO is done manually via `task up` or ad-hoc scripts — not in the default pytest run.

## Testing strategy overview

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

| Layer | What runs | External deps |
| --- | --- | --- |
| **Unit** | Pure logic, adapters with mocks | None |
| **API contract** | FastAPI TestClient / async client | Mocked stores |
| **Component** | Router engine, retrievers with `MagicMock` | No Milvus |
| **Integration (manual)** | Ingest + query against Docker stack | Real services |
| **E2E (manual)** | Frontend + API + workers | Full compose |

Default `pytest` target: **unit + API contract** only.

## Shared fixtures — `conftest.py`

[`tests/conftest.py`](https://github.com/fintax-ai/eagle-rag/blob/master/tests/conftest.py) defines **autouse** fixtures:

### `_reset_telemetry_state`

Runs before and after **every** test.

Resets:

- `eagle_rag.telemetry._configured`
- `logging_setup._configured`, `_enabled`, `_ai_logger_factory`
- `context._enabled`, contextvars dict
- `tracing._tracer`, `_tracing_enabled`
- structlog `contextvars`
- stdlib logger `eagle_ai_telemetry` handlers

**Why:** Telemetry configures global state once; without reset, order-dependent failures occur in `test_telemetry_*` and tracing tests. OpenTelemetry `TracerProvider` is process-global — tests only reset the module `_tracer` reference so `trace_span` no-ops until reconfigured.

### `_kb_registered`

Patches:

```python
patch("eagle_rag.kb.registry.kb_exists_sync", return_value=True)
patch("eagle_rag.kb.registry.get_pdf_ratio_sync", return_value=None)
```

**Why:** Ingest and query tests should not require a live Postgres `knowledge_bases` row.

## Test file map

| File | Focus | Style |
| --- | --- | --- |
| `test_api_admin_health.py` | `/health`, `/admin/*` probes | Async client, mocked backends |
| `test_api_query_sessions_documents_tasks.py` | Query, sessions, documents | API contract |
| `test_api_ingest_queue_metrics.py` | Ingest API, metrics | API + mocks |
| `test_api_kb_attachments_notifications_users.py` | KB CRUD, attachments | API contract |
| `test_router_generation.py` | `EagleRouterQueryEngine`, VLM mock | Unit + mock retrievers |
| `test_retrievers.py` | Retriever behaviour | Mock Milvus |
| `test_ingest_smoke.py` | Router dispatch smoke | Mocks |
| `test_ingest_assets.py` | Asset paths | Unit |
| `test_ingest_url_validation.py` | URL prefetch rules | Unit |
| `test_knowhere_sections.py` | Section tree parsing | Unit / fixture files |
| `test_knowhere_visual_chunks.py` | Visual chunk dispatch | Mock |
| `test_attachments_parser.py` | Attachment lazy parse | Unit |
| `test_milvus_structure_fetch.py` | Document structure API | Mock Milvus |
| `test_mcp_server.py` (via `test_mcp_*`) | MCP tools, auth, cache, HTTP | Mixed |
| `test_mcp_metrics.py` | Prometheus `with_metrics` | Unit |
| `test_mcp_http_transport.py` | Streamable HTTP | Async |
| `test_mcp_resilience.py` | Circuit breaker, retry | Unit |
| `test_mcp_config.py` | MCP settings | Unit |
| `test_mcp_auth.py` | Token auth | Unit |
| `test_mcp_cache.py` | Tool result cache | Unit |
| `test_telemetry_logging.py` | loguru / structlog setup | Unit, tmp paths |
| `test_telemetry_tracing.py` | `trace_span`, middleware | Unit |
| `test_telemetry_hotspots.py` | Span coverage on hot paths | Unit / smoke |

## Unit vs integration classification

### Unit tests

- No network; no Docker.
- `unittest.mock.patch`, `MagicMock`, `pytest.fixture` for small data.
- Examples: URL validator, routing heuristics, metrics status inference (`_infer_status`), dead-letter payload shape, schema validation.

### API contract tests

- Use FastAPI `TestClient` or `httpx.AsyncClient` against `app`.
- External services patched at import boundary (e.g. `MilvusClient`, `asyncpg`, Redis).
- Verify status codes, `response_model` shape, error handling.

### Integration tests (informal)

Not a separate pytest marker today. These **require running services**:

| Scenario | How to run |
| --- | --- |
| Full ingest → Milvus | `task up`, upload via API, inspect `/admin/milvus` |
| Knowhere parse | `task knowhere:up`, real document |
| PixelRAG visual | `worker-pixelrag` with GPU/CPU torch |
| Query streaming | `curl -N` on `/query/stream` |

Mark future automated integration tests with `@pytest.mark.integration` if introduced — skip by default in CI.

## Mocking patterns

### Retrievers

`test_router_generation.py` injects mocks:

```python
mock_text = MagicMock()
mock_text.retrieve.return_value = [node1, node2]
engine = EagleRouterQueryEngine(text_retriever=mock_text, visual_retriever=mock_visual)
```

### VLM / DashScope

Patch `dashscope.MultiModalConversation.call` or inject `MagicMock` with `complete` / stream iterator.

### Milvus

Patch `eagle_rag.index.milvus_text_store` / `milvus_visual_store` module functions or `MilvusClient` at call site.

### Knowhere

Patch `knowhere` SDK or HTTP client in `knowhere_adapter` tests — no live `:5005` in pytest.

### Celery

Tasks tested synchronously by calling the underlying function or using `celery_app.conf.task_always_eager = True` only when explicitly set in a test (not global today).

## Async tests

`asyncio_mode = "auto"` — async def tests run in an event loop without `@pytest.mark.asyncio` in most pytest-asyncio versions.

Admin health tests use async HTTP against lifespan-managed app.

## Writing new tests

1. Place file as `tests/test_<domain>_<feature>.py`.
2. Prefer one behaviour per test function name: `test_query_scope_filter_persists_to_session`.
3. Use autouse telemetry reset — do not call `configure_telemetry` without tmp log paths unless you cleanup.
4. Patch at the **lowest stable boundary** (the module under test imports from).
5. No real API keys — use env patches or empty keys with mocked upstream.

Example skeleton:

```python
from unittest.mock import patch
import pytest

@pytest.mark.asyncio
async def test_my_endpoint(client):
    with patch("eagle_rag.some.module.external_call", return_value={"ok": True}):
        resp = await client.get("/my-path")
    assert resp.status_code == 200
```

## Coverage gaps (intentional)

| Area | Why not fully automated |
| --- | --- |
| Milvus ANN quality | Requires vectors + tuning |
| Knowhere job polling | Long-running HTTP integration |
| Chrome PixelRAG render | Heavy deps in CI |
| OpenTelemetry OTLP export | Manual collector verification |

## Telemetry test notes

- `test_telemetry_logging.py` uses temporary log directories.
- Reset fixture clears loguru handlers — if adding tests that configure telemetry, use `tmp_path` for `op_log_file` / `ai_log_file`.
- TracerProvider cannot be unset globally; tests assert on span behaviour when `configure_tracing` runs in-test.

## MCP metrics tests

`test_mcp_metrics.py` validates:

- `with_metrics` increments `mcp_tool_calls_total{status}`
- Circuit state gauge updates
- Cache hit overrides status to `cache_hit`

Uses prometheus_client registry in-process (no scrape server required).

## Running subsets

```bash
uv run pytest tests/test_telemetry_tracing.py -v
uv run pytest -k "scope_filter"
uv run pytest --tb=short -q
```

## CI recommendation for maintainers

A minimal CI job should run:

```bash
uv sync --group dev
uv run ruff check
uv run ruff format --check
uv run mypy eagle_rag
uv run pytest
```

Frontend:

```bash
cd frontend && bun install && bun run lint
```

## Manual verification checklist (release)

After large ingest or retrieval changes:

1. `task be:test` green.
2. `task up` — `task health` ok.
3. Upload sample PDF (text + scanned).
4. `POST /query` and `/query/stream`.
5. `GET /admin/celery` — queues drain.
6. Check `logs/ai_telemetry.jsonl` for `query_completed`.

## Related

- [Contributing — PR checklist](contributing.md#pr-checklist)
- [Coding standards](coding-standards.md)
- [Operations troubleshooting](../ops/troubleshooting.md)
