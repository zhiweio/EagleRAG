# :material-folder: Project structure

Repository layout and **module dependency graph** for Eagle-RAG. Paths are relative to the repository root unless noted.

Entry points: [`README.md`](https://github.com/fintax-ai/eagle-rag/blob/master/README.md), [`AGENTS.md`](https://github.com/fintax-ai/eagle-rag/blob/master/AGENTS.md).

## Top-level tree

```
eagle-rag/
├── eagle_rag/              # Python backend package (primary)
├── frontend/               # Next.js 16 app (Bun)
├── tests/                  # Pytest suite
├── alembic/                # Database migrations
│   └── versions/
├── docker/                 # Dockerfiles + knowhere-self-hosted/
├── docs/                   # MkDocs (en/ + zh/)
├── design/                 # Design artefacts
├── data/                   # Runtime dir (gitignored): uploads, HF cache
├── docker-compose.yml
├── docker-compose.override.yml
├── Taskfile.yml
├── pyproject.toml          # uv / hatchling / ruff / mypy / pytest
├── mkdocs.yml
├── eagle_rag/settings.yaml
├── AGENTS.md
└── README.md
```

## `eagle_rag/` package map

| Directory | Responsibility |
| --- | --- |
| `api/` | FastAPI app, routers, MCP, Pydantic schemas |
| `ingest/` | Routing, Knowhere/PixelRAG adapters, Celery task bodies |
| `retrievers/` | LlamaIndex retrievers (text graph, visual) |
| `router/` | `EagleRouterQueryEngine`, LLM routing, scope filter resolution |
| `generation/` | Multimodal answer synthesis (VLM streaming) |
| `index/` | Milvus text/visual stores, tag catalog, document structure |
| `db/` | SQLModel models, async/sync DB helpers |
| `storage/` | MinIO client, dedup registry |
| `kb/` | Knowledge-base registry, lifecycle, stats |
| `sessions/` | Session + message persistence |
| `attachments/` | Ephemeral attachment parse (no Milvus write) |
| `notifications/` | User notification store |
| `tasks/` | Celery app, dead letter, task state audit |
| `admin/` | Queue metrics sampling, MCP log, system settings |
| `telemetry/` | loguru, structlog, OpenTelemetry |
| `metrics.py` | Prometheus MCP metrics (standalone app) |
| `config.py` | Settings loader |

## Module dependency graph

High-level import / call direction (runtime). External systems on the boundary.

```mermaid
flowchart TB
    subgraph clients["Clients"]
        FE["frontend"]
        MCPc["MCP clients"]
        HTTP["HTTP / curl"]
    end

    subgraph api_layer["eagle_rag.api"]
        APP["app.py"]
        Q["query.py"]
        ING["ingest.py"]
        DOC["documents.py"]
        HL["health.py"]
        MCP["mcp_server.py"]
        SCH["schemas/"]
    end

    subgraph orchestration["Orchestration"]
        RE["router/router_engine.py"]
        GEN["generation/multimodal_engine.py"]
        RET_K["retrievers/knowhere_graph_retriever.py"]
        RET_P["retrievers/pixelrag_visual_retriever.py"]
    end

    subgraph ingest_pipe["Ingest pipeline"]
        RTR["ingest/router.py"]
        KA["ingest/knowhere_adapter.py"]
        PA["ingest/pixelrag_adapter.py"]
        RUN["ingest/runner.py"]
    end

    subgraph tasks_layer["eagle_rag.tasks"]
        CEL["celery_app.py"]
        DL["dead_letter.py"]
        ST["state.py"]
    end

    subgraph data_layer["Data layer"]
        MTX["index/milvus_text_store.py"]
        MVX["index/milvus_visual_store.py"]
        MIN["storage/minio_client.py"]
        DED["storage/dedup.py"]
        DBM["db/models/*"]
        SESS["sessions/store.py"]
    end

    subgraph external["External services"]
        KH["Knowhere :5005"]
        MV["Milvus"]
        PG["PostgreSQL"]
        RD["Redis"]
        S3["MinIO"]
        DS["DashScope / DeepSeek APIs"]
    end

    subgraph observability["Observability"]
        TEL["telemetry/*"]
        ADM["admin/metrics.py"]
        PM["metrics.py"]
    end

    FE & MCPc & HTTP --> APP
    APP --> Q & ING & DOC & HL & MCP
    Q --> RE --> GEN
    RE --> RET_K & RET_P
    RET_K --> MTX
    RET_P --> MVX
    GEN --> DS
    ING --> RUN --> RTR
    RTR --> CEL
    CEL --> KA & PA
    KA --> KH
    KA --> MTX
    PA --> MVX
    KA & PA --> MIN
    RUN --> DED --> DBM
    Q --> SESS --> DBM
    HL --> ADM
    MCP --> PM
    APP & CEL --> TEL
    DBM --> PG
    CEL --> RD
    MTX & MVX --> MV
    MIN --> S3
```

### Layer rules

1. **`api/`** may call `router`, `ingest/runner`, `sessions`, `kb`, `admin` — not Milvus directly from routers (go through stores/retrievers).
2. **`ingest/`** tasks write via `index/` + `storage/`; dispatch uses `send_task_with_trace`.
3. **`router/`** + **`generation/`** read vectors only through retrievers and image store.
4. **`db/models/`** — no business logic; Alembic owns schema.
5. **`telemetry/`** — no imports from api/ingest (avoid cycles); consumers import telemetry.

## Request path (query)

```mermaid
sequenceDiagram
    participant C as Client
    participant API as api/query.py
    participant S as sessions/store
    participant R as router_engine
    participant T as knowhere_graph_retriever
    participant V as pixelrag_visual_retriever
    participant G as multimodal_engine
    participant LLM as DashScope VLM

    C->>API: POST /query/stream
    API->>S: load/create session (scope_filter JSONB)
    API->>R: route + retrieve
    R->>T: text ANN + graph
    R->>V: visual ANN
    R->>G: fused context
    G->>LLM: stream tokens
    G-->>C: SSE tokens + sources
```

## Ingest path

```mermaid
sequenceDiagram
    participant API as api/ingest.py
    participant RUN as ingest/runner.py
    participant RT as ingest/router.py
    participant CQ as router_queue
    participant KQ as knowhere_queue
    participant PQ as pixelrag_queue
    participant KH as Knowhere HTTP
    participant PR as pixelrag lib
    participant M as Milvus

    API->>RUN: register document
    RUN->>CQ: ingest_router
    CQ->>RT: probe format
    alt text pipeline
        RT->>KQ: knowhere_parse
        KQ->>KH: SDK parse job
        KQ->>M: eagle_text
        KQ->>PQ: knowhere_visual_chunks
    else visual pipeline
        RT->>PQ: pixelrag_build
        PQ->>PR: render + embed
        PQ->>M: eagle_visual
    end
```

## `frontend/` structure

```
frontend/
├── app/                 # Next.js App Router (locale segments)
├── components/          # UI components (HeroUI)
├── lib/                 # API client helpers
├── messages/            # next-intl zh/en
├── package.json
└── biome.json
```

Frontend talks to backend only via HTTP (`NEXT_PUBLIC_API_URL`). No shared Python/TS types — OpenAPI is the contract.

## `tests/` structure

Flat layout — `tests/test_*.py` mirrors domains:

| Pattern | Area |
| --- | --- |
| `test_api_*` | FastAPI routes (TestClient / async) |
| `test_router_*`, `test_retrievers` | Retrieval and generation |
| `test_ingest_*` | Routing, URL validation, smoke |
| `test_mcp_*` | MCP tools, HTTP transport, metrics |
| `test_telemetry_*` | Logging and tracing |
| `test_knowhere_*`, `test_milvus_*` | Adapter edge cases |

Shared fixtures: [`tests/conftest.py`](https://github.com/fintax-ai/eagle-rag/blob/master/tests/conftest.py). Details: [Testing](testing.md).

## `docker/` layout

```
docker/
├── Dockerfile.api
├── Dockerfile.worker
├── Dockerfile.frontend
├── Dockerfile.docs
└── knowhere-self-hosted/
    ├── compose.yaml
    ├── .env.example
    └── env.defaults
```

## `alembic/` layout

```
alembic/
├── env.py               # Imports SQLModel metadata
├── script.py.mako
└── versions/
    ├── 0001_*.py
    └── 0002_health_module_tables.py
```

Models live in `eagle_rag/db/models/`; migrations are the only DDL path.

## Key files quick reference

| File | Why read it |
| --- | --- |
| [`ingest/router.py`](https://github.com/fintax-ai/eagle-rag/blob/master/eagle_rag/ingest/router.py) | Format + PDF probe routing matrix |
| [`router/router_engine.py`](https://github.com/fintax-ai/eagle-rag/blob/master/eagle_rag/router/router_engine.py) | `_resolve_scope_filter`, hybrid retrieval |
| [`tasks/celery_app.py`](https://github.com/fintax-ai/eagle-rag/blob/master/eagle_rag/tasks/celery_app.py) | Queues, beat schedule, ack semantics |
| [`tasks/dead_letter.py`](https://github.com/fintax-ai/eagle-rag/blob/master/eagle_rag/tasks/dead_letter.py) | Retry + dead letter |
| [`api/health.py`](https://github.com/fintax-ai/eagle-rag/blob/master/eagle_rag/api/health.py) | Probes and admin |
| [`telemetry/tracing.py`](https://github.com/fintax-ai/eagle-rag/blob/master/eagle_rag/telemetry/tracing.py) | `trace_span`, Celery propagation |
| [`db/models/sessions.py`](https://github.com/fintax-ai/eagle-rag/blob/master/eagle_rag/db/models/sessions.py) | `scope_filter` JSONB |

## Data stores per module

| Module | PostgreSQL | Milvus | MinIO | Redis |
| --- | --- | --- | --- | --- |
| `sessions/` | sessions, messages | — | — | — |
| `storage/dedup` | dedup registry | — | objects | — |
| `index/milvus_*` | — | eagle_text, eagle_visual | — | — |
| `tasks/` | task_audit | — | — | broker |
| `admin/metrics` | metric_sample | — | — | LLEN queues |
| `attachments/` | attachments meta | — | temp files | — |

## Adding a new feature (where to put code)

| Feature type | Touch |
| --- | --- |
| REST endpoint | `api/schemas/`, `api/<router>.py`, `app.py` include |
| MCP tool | `mcp_server.py`, `TOOL_DEFINITIONS`, tests |
| Ingest format | `ingest/router.py`, settings `ingest.routing`, adapter |
| Retrieval mode | `router/`, `retrievers/`, `settings.yaml` router section |
| Persistent entity | `db/models/`, Alembic revision, store module |
| Background job | `ingest/*_adapter.py` or new module, `celery_app.include`, `task_routes` |

## Related

- [Development index](index.md)
- [Coding standards](coding-standards.md)
- [Architecture docs](../architecture/index.md)
