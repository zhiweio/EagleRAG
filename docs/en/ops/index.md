# :material-server: Operations

Eagle-RAG ships as a layered Docker Compose stack: infrastructure (etcd, MinIO, Milvus, PostgreSQL, Redis), a self-hosted [Knowhere](https://github.com/Ontos-AI/knowhere) document-parser sub-stack, the FastAPI API, three Celery workers, and a Next.js frontend. This section is for operators who deploy, observe, troubleshoot, and back up the system in production.

The project entry points are [`Taskfile.yml`](https://github.com/fintax-ai/eagle-rag/blob/master/Taskfile.yml) and [`docker-compose.yml`](https://github.com/fintax-ai/eagle-rag/blob/master/docker-compose.yml). Contributor and agent constraints live in [`AGENTS.md`](https://github.com/fintax-ai/eagle-rag/blob/master/AGENTS.md); the product overview is in [`README.md`](https://github.com/fintax-ai/eagle-rag/blob/master/README.md).

## Quick commands

```bash
task setup          # copy .env files, uv sync, bun install, create knowhere-net
task up             # dev profile (auto-merges docker-compose.override.yml)
task up:prod        # prod profile (excludes the dev override)
task down           # stop eagle-rag + knowhere compose projects
task health         # curl http://localhost:8000/health
task ps             # docker compose ps (both projects)
task logs           # docker compose logs -f
task db:migrate     # alembic upgrade head
task knowhere:health # probe Knowhere HTTP :5005
```

### Taskfile task groups

| Group | Representative tasks | Purpose |
| --- | --- | --- |
| Frontend | `fe:dev`, `fe:build`, `fe:lint`, `fe:format` | Bun / Next.js local dev and Biome gates |
| Backend | `be:api`, `be:worker`, `be:test`, `be:lint`, `be:format`, `be:typecheck` | uvicorn, Celery, pytest, ruff, mypy |
| Docker | `up`, `up:prod`, `down`, `build`, `logs`, `ps`, `clean` | Compose lifecycle |
| Knowhere | `knowhere:up`, `knowhere:down`, `knowhere:health`, `knowhere:logs` | Independent parser sub-stack |
| Docs | `docs:serve`, `docs:build`, `docs:up` | MkDocs local preview and container |
| Data | `db:migrate` | Alembic migrations against PostgreSQL |

`task be:worker` accepts parameters:

```bash
task be:worker QUEUES=router_queue,knowhere_queue,pixelrag_queue CONCURRENCY=4
```

On a laptop this collapses all three pipeline queues into one process. In Docker, each queue has a dedicated container with tuned `CONCURRENCY` (see [Docker](docker.md)).

## What's in this section

| Page | Topic |
| --- | --- |
| [Docker](docker.md) | Compose topology, Dockerfiles, healthcheck-gated startup, dev override |
| [Observability](observability.md) | `/health`, `/metrics`, `/admin/*`, queue sampling, SSE logs, OpenTelemetry |
| [Troubleshooting](troubleshooting.md) | Symptom → cause → fix matrix mapped to probes and log lines |
| [Backup & restore](backup-restore.md) | PostgreSQL, MinIO, Milvus, Knowhere, Redis — per-store with compose volume names |

## Operational model

The stack has three layers that start in dependency order. Application services use `depends_on` with `condition: service_healthy` so a broken dependency pauses startup instead of producing connection-error cascades.

```mermaid
flowchart TB
    subgraph L1["Layer 1 — Infrastructure (always on)"]
        etcd["etcd"]
        minio["minio"]
        milvus["milvus"]
        pg["postgres"]
        redis["redis"]
    end

    subgraph L2["Layer 2 — Knowhere sub-stack (knowhere-net)"]
        kh["knowhere :5005"]
        kh_pg["postgres 15"]
        kh_redis["redis"]
        kh_ls["localstack"]
    end

    subgraph L3["Layer 3 — Application (dev/test/prod profile)"]
        api["api :8000"]
        wr["worker-router c=4"]
        wk["worker-knowhere c=8"]
        wp["worker-pixelrag c=1"]
        fe["frontend :3000"]
    end

    etcd --> milvus
    minio --> milvus
    pg --> api
    redis --> api
    minio --> api
    milvus --> api
    redis --> wr & wk & wp
    milvus --> wr & wk & wp
    api --> fe
    kh -.->|knowhere-net DNS| api & wk
```

| Layer | Services | Notes |
| --- | --- | --- |
| Infrastructure | `etcd`, `minio`, `milvus`, `postgres`, `redis` | etcd + MinIO feed Milvus 2.6.19; PostgreSQL 16 and Redis 7 are shared by the app |
| Knowhere sub-stack | `app`, `postgres`, `redis`, `localstack` in `docker/knowhere-self-hosted/` | Self-hosted parser with its own Postgres 15 (`Knowhere` DB), Redis (2 GB LRU), LocalStack 3.8; reached over external network `knowhere-net` |
| Application | `api`, `worker-router`, `worker-knowhere`, `worker-pixelrag`, `frontend`, `docs` | API `:8000`; three Celery workers share one image, parameterised by `QUEUES` / `CONCURRENCY`; frontend `:3000` |

### Why three Celery workers?

Ingest is a three-stage pipeline:

1. **`router_queue`** (concurrency 4) — route by format + content form, dispatch downstream tasks.
2. **`knowhere_queue`** (concurrency 8) — HTTP calls to Knowhere for structured parsing; I/O-bound, higher parallelism.
3. **`pixelrag_queue`** (concurrency 1) — in-process `pixelrag_render` + `pixelrag_embed` + Qwen3-VL encoder; memory-bound, strictly serialised.

Splitting workers prevents a long visual encode from starving router dispatch and keeps OOM risk isolated behind a 4 GB memory limit on `worker-pixelrag`. See [Docker — pixelrag_queue](docker.md#why-pixelrag_queue-concurrency-is-1).

## Profiles and the dev override

Infrastructure services carry **no profile** and start with any invocation. Application services belong to `[dev, test, prod]`; `docs` belongs to `[docs, prod]`.

```bash
docker compose --profile dev up -d
COMPOSE_FILE=docker-compose.yml docker compose --profile prod up -d
docker compose --profile docs up -d docs
```

[`docker-compose.override.yml`](https://github.com/fintax-ai/eagle-rag/blob/master/docker-compose.override.yml) merges automatically when Compose is invoked without an explicit `-f` / `COMPOSE_FILE`. It enables `uvicorn --reload`, mounts `eagle_rag/` read-only, exposes infrastructure ports, and runs the frontend through Bun. **Prod deployments must lock the compose file list** with `COMPOSE_FILE=docker-compose.yml` to prevent dev mounts and `--reload` from leaking into production.

## Networks and external dependencies

| Network | Scope | Purpose |
| --- | --- | --- |
| `eagle-net` | eagle-rag compose project | Internal DNS for etcd, minio, milvus, postgres, redis, api, workers, frontend |
| `knowhere-net` | **external**, shared | DNS alias `knowhere` → Knowhere API `:5005`; created by `task setup` or `task net:ensure` |

Knowhere is **not** in the main `docker-compose.yml` because it is maintained as an independent compose project under `docker/knowhere-self-hosted/`. Eagle-RAG cannot `depends_on` a service in another compose file; instead the API and `worker-knowhere` join `knowhere-net` and use `KNOWHERE_BASE_URL=http://knowhere:5005`. When Knowhere is down, parse tasks **fail closed** (status `FAILED`) rather than silently falling back.

## Configuration injection

[`eagle_rag/settings.yaml`](https://github.com/fintax-ai/eagle-rag/blob/master/eagle_rag/settings.yaml) uses `${VAR:-default}` placeholders for every external endpoint. Inside containers you must inject service DNS names — defaults like `localhost` will not reach compose services:

| Variable | Container value | Host dev value |
| --- | --- | --- |
| `MILVUS_HOST` | `milvus` | `localhost` |
| `CELERY_BROKER_URL` | `redis://redis:6379/0` | `redis://localhost:6379/0` |
| `POSTGRES_DSN` | `postgresql://eagle:eagle@postgres:5432/eagle_rag` | `postgresql://eagle:eagle@localhost:5432/eagle_rag` |
| `MINIO_ENDPOINT` | `minio:9000` | `localhost:9000` |
| `KNOWHERE_BASE_URL` | `http://knowhere:5005` | `http://localhost:5005` |

VLM / LLM / embedding API keys are injected from `.env` only; they are not hardcoded in compose.

## Health and readiness

| Endpoint | Consumer | Behaviour |
| --- | --- | --- |
| `GET /health` | Docker `api` healthcheck, `task health`, load balancers | Probes 8 dependencies concurrently; any `down` → `status: degraded` (HTTP 200) |
| `GET /admin/probes` | Admin UI, deep ops | Same probes plus `latency_ms`, host CPU/memory via psutil |
| `celery inspect ping` | Worker healthchecks | Per-container, scoped to `celery@$(hostname)` |
| `GET http://knowhere:5005/health` | Knowhere sub-stack | Independent of eagle-rag compose |

Worker containers use a 60 s `start_period` because Milvus and LlamaIndex clients warm up on first import. The API uses 40 s for the same reason.

## Data directories

| Path | Mount | Contents |
| --- | --- | --- |
| `./data` | `api` + all workers | `storage.data_dir` — uploads, HuggingFace cache (`HF_HOME=/app/data/huggingface`), Chrome/PixelRAG artefacts |
| Named volumes | Infrastructure only | See [Backup & restore](backup-restore.md) for `vol-*` names |

Never commit `.env` or secrets. `task setup` copies `.env.example` and `docker/knowhere-self-hosted/.env.example` with `cp -n`.

## Celery reliability (operator summary)

Eagle-RAG configures Celery for **at-least-once** delivery:

- `task_acks_late = True` — message is not removed from Redis until the task finishes.
- `worker_prefetch_multiplier = 1` — a worker does not hoard messages while busy.
- `task_reject_on_worker_lost = True` — killed workers requeue in-flight tasks.

Tasks decorated with `@with_retry` use exponential backoff (`retry_backoff * 2^retries`) and, on exhaustion, land in the **`dead_letter`** queue for admin inspection (`drain_dead_letter` / `replay_dead_letter`). The dead-letter queue is intentionally **not** consumed by business workers.

Full theory and replay procedures are documented in [Troubleshooting — Celery and dead letters](troubleshooting.md#celery-at-least-once-delivery-and-dead-letters).

## Observability (operator summary)

| Signal | Where | Use |
| --- | --- | --- |
| Ops logs | loguru → stderr + `logs/eagle_rag.log` (+ Redis `logs` channel) | Request errors, worker stack traces |
| AI events | structlog → `logs/ai_telemetry.jsonl` via `get_ai_logger` | Query/ingest business events (JSONL) |
| Traces | OpenTelemetry `trace_span` + optional OTLP export | End-to-end latency across API → Celery → retrieval |
| Prometheus | `mcp_tool_calls_total`, `mcp_tool_duration_seconds`, … on MCP standalone `/metrics` | MCP cloud scrape targets |
| Queue metrics | Celery beat → `metric_sample` table every 30 s | `/admin/celery` backlog time series |

Details: [Observability](observability.md).

## Multi-tenancy in operations

Every document, vector row, session, and Celery task carries `kb_name` (default `default`, overridable via `KB_NAME`). Operators backing up or restoring one tenant should filter by `kb_name` in PostgreSQL and Milvus scalar fields, not only by bucket prefix. Session scope filters (`sessions.scope_filter` JSONB) persist user-selected KB / document / tag unions — restore PostgreSQL before expecting scope-aware queries to work.

## Production checklist

1. Copy and fill `.env` and `docker/knowhere-self-hosted/.env` (API keys, passwords).
2. `docker network create knowhere-net` (idempotent).
3. `task up:prod` or equivalent with `COMPOSE_FILE=docker-compose.yml`.
4. `task db:migrate` against the production DSN.
5. Verify `task health` → all critical deps `up` (pixelrag may be `unknown` if vision extra omitted — see troubleshooting).
6. Confirm three workers healthy: `docker compose ps worker-router worker-knowhere worker-pixelrag`.
7. Scrape `/admin/celery` queue sizes; ensure beat is running if you need backlog charts (beat is not a separate compose service — run `celery -A eagle_rag.tasks.celery_app beat` if required).
8. Configure log rotation (compose `json-file` max 10 MB × 3 files per service).
9. Schedule backups per [Backup & restore](backup-restore.md).

## Local development without Docker

```bash
task setup
# Start infra only, or use existing local Postgres/Redis/Milvus/MinIO
task be:api          # terminal 1
task be:worker       # terminal 2 — all queues, CONCURRENCY=4
task fe:dev          # terminal 3
task knowhere:up     # if parsing is needed
```

Or `task dev` runs API + frontend in parallel (workers still need a separate terminal).

## Related documentation

- Architecture and multimodal fusion: `docs/en/architecture/`
- Backend module deep dives: `docs/en/backend/`
- Development workflow: `docs/en/development/`
