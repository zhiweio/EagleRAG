# Eagle-RAG Backend (`eagle_rag/`)

Python package for the Eagle-RAG multimodal RAG data layer: ingestion, indexing, retrieval, generation, API, and MCP tools.

## Layout

| Package | Responsibility |
| --- | --- |
| `api/` | FastAPI routers, Pydantic schemas, MCP server |
| `ingest/` | Routing matrix, Knowhere/PixelRAG adapters, Celery task entry |
| `index/` | Milvus text/visual stores, tag catalog, document structure |
| `retrievers/` | Knowhere graph + PixelRAG visual retrievers |
| `router/` | Query routing engine and selector chain |
| `generation/` | Multimodal answer synthesis (Qwen-VL-Max) |
| `tasks/` | Celery app, task state, dead-letter handling |
| `db/` | SQLModel models and Alembic metadata |
| `kb/` | Knowledge-base lifecycle, stats, health |
| `storage/` | MinIO client, deduplication |
| `attachments/` | Lazy QA attachment parsing |
| `admin/` | Ops metrics, probes, MCP call logs |
| `telemetry/` | Structured logging and OpenTelemetry |

## Key entry points

- **API**: `eagle_rag.api.app:app` (uvicorn)
- **Workers**: `eagle_rag.tasks.celery_app`
- **MCP**: `python -m eagle_rag.api.mcp_server`
- **Config**: `eagle_rag/settings.yaml` + `eagle_rag/config.py`

## Development

```bash
uv sync
task be:lint && task be:format && task be:typecheck
task be:test
task be:api
task be:worker QUEUES=knowhere_queue CONCURRENCY=8
```

## Constraints

See [AGENTS.md](../AGENTS.md): Knowhere vs PixelRAG boundaries, `kb_name` multi-tenancy, DeepSeek + Qwen models only, English docstrings/comments.

## Documentation

- [Backend docs](../docs/en/backend/index.md)
- [Architecture](../docs/en/architecture/index.md)
