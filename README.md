<div align="center">

  <img
    src="docs/images/banner.png"
    alt="Eagle-RAG — Enterprise RAG Platform for Smarter AI Applications"
    width="1000"
    style="max-width: 1000px; width: 100%; height: auto;"
  />

  <h1>Eagle-RAG</h1>

  <p>
    <a href="https://github.com/zhiweio/EagleRAG/stargazers"><img src="https://img.shields.io/github/stars/zhiweio/EagleRAG?style=social" alt="GitHub stars"/></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg" alt="License"/></a>
    <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.12+-blue.svg" alt="Python"/></a>
  </p>

  <p>
    <img src="https://img.shields.io/badge/Milvus-2.6-00A6FB?logo=milvus&logoColor=white&style=flat-square" alt="Milvus"/>
    <img src="https://img.shields.io/badge/LlamaIndex-RAG-0A0A0A?style=flat-square" alt="LlamaIndex"/>
    <img src="https://img.shields.io/badge/Knowhere-Ontos--AI-9F2B68?style=flat-square" alt="Knowhere"/>
    <img src="https://img.shields.io/badge/PixelRAG-StarTrail--org-8A2BE2?style=flat-square" alt="PixelRAG"/>
    <img src="https://img.shields.io/badge/MinerU-OpenDataLab-FF6B35?style=flat-square" alt="MinerU"/>
    <img src="https://img.shields.io/badge/MCP-HTTP+stdio-6366F1?style=flat-square" alt="MCP"/>
  </p>

  <p>
    <a href="https://zhiweio.github.io/EagleRAG/"><strong>Documentation</strong></a>
    ·
    <a href="https://youtu.be/Bj6lI48p7Zw"><strong>Demo</strong></a>
    ·
    <a href="README.md">English</a> | <a href="README.zh.md">中文</a>
  </p>

</div>

> **Semantic Depth. Visual Clarity.**
>
> Search knowledge by what documents *mean* and how they *look* — not one or the other.  
> Weaving Knowhere semantic chunks with PixelRAG pixel-native perception into a multi-tenant data layer — built to ignite Agent intelligence.

Eagle-RAG uses a **microkernel + in-repo plugins** architecture: Core (`namespace=core`) provides ingest, multimodal retrieval, and MCP tools (`core_*`); domain plugins extend hooks, encoders, and MCP via `EAGLE_RAG_PROFILE` / `settings.plugins.enabled` + `default_namespace`. **`plugins/biomed` is experimental**; **`plugins/lakehouse_bi` is under development**. **Built-in UI = Core knowhere+pixelrag showcase only**; verticals are **backend + MCP** for downstream Agents. See [Plugin architecture](docs/en/architecture/plugin-architecture.md), [ADR-008](docs/en/architecture/adr/008-rag-only-plugin-platform.md), and [Authoring guide](docs/en/guides/authoring-industry-plugin.md).
Feed it PDFs, Office files, scans, or web pages — Eagle-RAG understands both the words and the visuals. Answers stream back with citations you can check, and multiple teams can each run their own knowledge base without mixing data.

## How It Work

<p align="center">
  <img
    src="docs/images/eaglerag-pipeline.png"
    alt="Eagle-RAG pipeline"
    width="1000"
    style="max-width: 1000px; width: 100%; height: auto; object-fit: contain;"
  />
</p>

## See it in action

[Watch the demo on YouTube](https://youtu.be/Bj6lI48p7Zw) — multimodal Q&A with cited sources.

## Core capabilities

- **Dual ingestion pipelines** — [Knowhere](https://github.com/Ontos-AI/knowhere) (external HTTP service `:5005`, invoked via the official `knowhere-python-sdk`) handles text / structured documents (text-based PDF / Word / Excel / CSV / PPTX / Markdown / txt / json); **PixelRAG** (in-process library `pixelrag_render` + `pixelrag_embed`) handles scanned PDFs / images / web pages.
- **Two-layer isolation** — deploy binds `plugin_namespace` to a Milvus **Database** (+ PG repository filter); within that domain, `kb_name` scalar-filters KBs. Dedup PK is `(sha256, kb_name, plugin_namespace)`. Multi-industry = multiple instances (`EAGLE_RAG_PROFILE`), not runtime domain switching.
- **Hybrid retrieval** — multi-collection ANN inside the domain DB (base `eagle_text` / `eagle_visual`, plus optional specialized collections), RRF merge across encoders, graph expansion on text nodes, and scalar filters such as `kb_name` / `document_id` / `year` / `source_type`.
- **Multimodal generation** — DeepSeek-V4-Pro handles routing and text generation; Qwen-VL-Max generates answers over both text chunks and image tiles, with qwen3-rerank reranking.
- **MCP tool server** — exposes `core_ingest` / `core_query` / `core_retrieve_text` / `core_retrieve_visual` over streamable HTTP (default `/mcp`) with stdio fallback; domain profiles add `{namespace}_*` RAG tools for Agents.
- **Observable operations** — concurrent dependency probes (`/admin/probes`), live SSE log streaming, queue-metric time series, and per-service admin dashboards.

## System architecture

```
                         CLIENT TIER
              ┌─────────────────┐   ┌─────────────────┐
              │  Next.js UI     │   │ External Agents │
              │  QA·Ingest·KB   │   │  (MCP / HTTP)   │
              └────────┬────────┘   └────────┬────────┘
                       │ REST / SSE          │ MCP
                       └──────────┬──────────┘
                                  ▼
              ┌───────────────────────────────────────────┐
              │  FastAPI :8000  —  REST · SSE · MCP       │
              │  PluginManager · HookBus · Orchestrators  │
              │  Router Engine → Multimodal Engine        │
              └───────┬───────────────────────┬───────────┘
                      │ query / retrieve      │ ingest
                      │                       ▼
                      │            ┌──────────────────────┐
                      │            │  Celery workers      │
                      │            │  router_queue    ×4  │
                      │            │  knowhere_queue  ×8  │
                      │            │  pixelrag_queue  ×1  │
                      │            └──────┬───────┬───────┘
                      │                   │       │
                      │                   ▼       ▼
                      │     ┌─────────────────────────┐ ┌──────────┐
                      │     │ Knowhere (KNOWHERE_MODE)│ │ PixelRAG │
                      │     │  api    → HTTP :5005    │ │ in-proc  │
                      │     │  parser → parse-sdk     │ │ render   │
                      │     │  text + KG              │ │          │
                      │     └───────────┬─────────────┘ └────┬─────┘
                      │         1536d text│           2048d visual
                      │                 └──────┬─────┘
                      ▼                        ▼
              ┌───────────────────────────────────────────┐
              │  STORAGE (per plugin_namespace)           │
              │  Milvus DB    eagle_text + eagle_visual   │
              │               [+ specialized collections] │
              │  PostgreSQL   namespace-scoped repos      │
              │  MinIO        originals · visual tiles    │
              │  Redis 7      Celery broker · task logs   │
              └───────────────────────────────────────────┘
```

Infrastructure: Milvus (one **Database** per `plugin_namespace`) + PostgreSQL (namespace-scoped repositories) + Redis + MinIO. Knowhere backend is selected by `KNOWHERE_MODE` (`api` = `knowhere-python-sdk` → HTTP `:5005`; `parser` = in-process `knowhere-parse-sdk`).

## Technology stack

| Layer | Technologies |
| --- | --- |
| **Backend** | Python ≥ 3.12, FastAPI, Celery 5, LlamaIndex, Pydantic v2, SQLModel, Alembic |
| **Frontend** | Next.js 16 (App Router), React 19, TypeScript 5, HeroUI v3, Tailwind v4, TanStack Query, Zustand 5, next-intl (zh / en, light-only) |
| **AI models** | DeepSeek-V4-Pro (text LLM / routing), Qwen-VL-Max (VLM), `text-embedding-v4` (text 1536-d), Qwen3-VL visual embedding 2048-d via `get_visual_encoder()` (`provider=pixelrag` local HF or `dashscope` Bailian), `qwen3-rerank` (rerank). DeepSeek + Qwen only, no OpenAI / Cohere. |
| **Infrastructure** | Milvus 2.6 (DB per `plugin_namespace`; base `eagle_text` + `eagle_visual`), PostgreSQL 16, Redis 7, MinIO, Docker Compose |
| **Integration** | MCP (Model Context Protocol) over HTTP (default `/mcp`) + stdio fallback, OpenAPI-generated TypeScript SDK |

> **Multimodal fusion architecture**: visual tiles are stored in `eagle_visual` using Milvus's built-in HNSW / DiskANN engine (replacing PixelRAG's native FAISS), and anchored back to the Knowhere semantic tree via four semantic-tree anchor fields (`chunk_type` / `parent_section` / `content_summary` / `source_chunk_id`) — see [Multimodal Fusion Architecture](docs/zh/architecture/multimodal-fusion.md).

## Prerequisites

### Runtime dependencies

| Dependency | Notes |
| --- | --- |
| Python ≥ 3.12 | Backend runtime; package management via [`uv`](https://docs.astral.sh/uv/) |
| Node.js + Bun | Frontend runtime and package manager (`bun install`) |
| Docker + Docker Compose | One-command full-stack startup (infrastructure included) |
| Milvus 2.6+ | Vector store; one Database per domain; base `eagle_text` (1536-d) / `eagle_visual` (2048-d) |
| PostgreSQL 16 | Sessions / dedup / task audit |
| Redis 7 | Celery broker / result backend |
| MinIO | Tile PNG and original-file object storage |

### External services

- **Knowhere parsing** (`KNOWHERE_MODE`, default `api`):
  - **`api`** — document semantic parsing via [Ontos-AI/knowhere](https://github.com/Ontos-AI/knowhere) HTTP `:5005` and `knowhere-python-sdk` (`KNOWHERE_BASE_URL` defaults to `http://localhost:5005`). Synchronously returns an in-memory `ParseResult` over `/v1/jobs` with no disk writes to `~/.knowhere/`.
  - **`parser`** — in-process parsing via [`knowhere-parse-sdk`](https://github.com/zhiweio/knowhere-parse-sdk) (`KnowhereParser.parse`); no `:5005` service required. Requires MinerU (`MINERU_API_KEYS`) and LLM credentials (mapped from global `llm` / `vlm` settings or `knowhere.parser` overrides).
  - Both modes fail closed: `KnowhereError` → task `FAILED`, no mock fallback.
  > Note the distinction: modern Milvus ships a built-in HNSW / DiskANN vector search engine that carries visual-vector storage and nearest-neighbour search (replacing PixelRAG's native FAISS; DiskANN breaks the memory ceiling). The `Ontos-AI/knowhere` repository in this stack is the document parsing service, which is unrelated.
- **PixelRAG library (core dependency)**: `pixelrag_render` / `pixelrag_embed`, declared under `[project.dependencies]` in `pyproject.toml` and installed by default via `uv sync`; when `provider=="pixelrag"` is not configured it fails fast (no mock fallback, no random-vector fallback). **`pixelrag-serve` is no longer deployed and FAISS is no longer used.**

> **Removed**: LibreOffice (Excel now goes through Knowhere directly), pixelrag-serve, FAISS, OpenAI / Cohere.

### Model API keys

DeepSeek + Qwen only:

| Purpose | Model | Environment variables |
| --- | --- | --- |
| Text LLM / routing | DeepSeek-V4-Pro | `LLM_API_KEY`, `LLM_BASE_URL` |
| VLM (chart reading) | Qwen-VL-Max | `VLM_API_KEY`, `VLM_BASE_URL` |
| Text embedding 1536-d | Qwen `text-embedding-v4` | `DASHSCOPE_API_KEY`, `DASHSCOPE_BASE_URL` |
| Visual embedding 2048-d | Qwen3-VL-Embedding-2B (`pixelrag_embed`) | Hosted by the PixelRAG library |
| Text rerank | Qwen `qwen3-rerank` | `DASHSCOPE_API_KEY` |

### Key environment variables

> Governed by `eagle_rag/settings.yaml` (supports `${VAR:-default}` placeholders). `EAGLE_RAG_PROFILE` binds the domain (`plugin_namespace` / Milvus Database); `KB_NAME` selects a KB inside that domain; `KNOWHERE_MODE` / `KNOWHERE_BASE_URL` select the Knowhere backend. **`LIBREOFFICE_PATH` and `PIXELRAG_SERVE_URL` are no longer used**.

| Variable | Default | Description |
| --- | --- | --- |
| `EAGLE_RAG_PROFILE` | `core` | Deploy profile: `core` / `biomed` (experimental) / `lakehouse-bi` (in development); sets `default_namespace` + Milvus `db_name` |
| `KB_NAME` | `default` | Default knowledge-base id **inside** the bound domain, e.g. `finance` / `patent` / `pharma` |
| `KNOWHERE_MODE` | `api` | Knowhere backend: `api` (HTTP `:5005` via `knowhere-python-sdk`) or `parser` (in-process `knowhere-parse-sdk`) |
| `KNOWHERE_BASE_URL` | `http://localhost:5005` | Knowhere HTTP parsing service URL (`api` mode only) |
| `MINERU_API_KEYS` | — | MinerU API key for PDF parsing (`parser` mode) |
| `LLM_API_KEY` / `LLM_BASE_URL` | — | DeepSeek |
| `VLM_API_KEY` / `VLM_BASE_URL` | — | Qwen-VL-Max (DashScope) |
| `DASHSCOPE_API_KEY` | — | Shared by Qwen text embedding / rerank |
| `MILVUS_HOST` / `MILVUS_PORT` | `localhost` / `19530` | Milvus |
| `MILVUS_VISUAL_INDEX_TYPE` | `hnsw` | Visual index type, `hnsw` / `diskann` |
| `ROUTER_MODE` | `auto` | `auto` / `text` / `visual` / `hybrid` |
| `POSTGRES_DSN` | `postgresql://eagle:eagle@localhost:5432/eagle_rag` | PostgreSQL connection string |
| `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` | `redis://localhost:6379/0` / `1` | Celery |
| `MINIO_ENDPOINT` / `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` | `localhost:9000` / `minioadmin` / `minioadmin` | MinIO |

## Quick start

```bash
# 1. Initialize (copy .env, install backend + frontend dependencies)
task setup
# Edit .env to fill in LLM_API_KEY / VLM_API_KEY / DASHSCOPE_API_KEY and DB credentials

# 2a. Docker full stack (recommended, infrastructure included)
task up                 # dev profile (auto-merges docker-compose.override.yml)
task up:prod            # prod profile (excludes dev override)

# 2b. Local development (start Milvus / PostgreSQL / Redis / MinIO / Knowhere yourself)
task dev                # parallel hot-reload of frontend + backend
task be:worker QUEUES=router_queue CONCURRENCY=4
task be:worker QUEUES=knowhere_queue CONCURRENCY=8
task be:worker QUEUES=pixelrag_queue CONCURRENCY=1   # strict low concurrency to avoid OOM

# 3. Verify
task health             # curl http://localhost:8000/health
```

## Common commands (Taskfile)

| Command | Description |
| --- | --- |
| `task setup` | Copy `.env`, `uv sync`, `bun install` |
| `task up` / `task up:prod` / `task down` | Docker start / stop (dev / prod profile) |
| `task dev` | Local parallel start of frontend + backend (hot-reload) |
| `task be:api` / `task be:worker` | Backend API / Celery Worker (parameterized queue and concurrency) |
| `task be:test` / `task be:lint` / `task be:typecheck` | Tests / Ruff / Mypy |
| `task fe:dev` / `task fe:build` / `task fe:lint` | Frontend dev / build / Biome |
| `task docs:serve` / `task docs:build` | MkDocs doc site (`:8001`) |
| `task db:migrate` | Alembic migrate to latest revision (`alembic upgrade head`) |
| `task health` | Check API health |

## MCP tools

The MCP Server (FastMCP, default streamable HTTP transport mounted at `/mcp`, with stdio fallback) exposes **namespaced** tools (`{namespace}_{name}`). Core tools are always registered; domain tools appear only when `EAGLE_RAG_PROFILE` / `default_namespace` matches (G3).

| Tool | Parameters | Returns |
| --- | --- | --- |
| `core_ingest` | `source_uri`, `source_type?`, `kb_name?` | `{job_id, status, document_id, dedup_hit}` |
| `core_query` | `query`, `mode?`, `scope?`, `kb_name?`, `scope_filter?` | `{answer, sources, route, steps}` |
| `core_retrieve_text` | `query`, `scope?`, `top_k=5`, `kb_name?` | `[{node_id, text, score, metadata}]` |
| `core_retrieve_visual` | `query`, `scope?`, `top_k=5`, `kb_name?` | `[{image_id, document_id, page, position, score}]` |
| `biomed_query_entities` | `entity`, `kb_name?` | entity aliases / pathways (biomed profile, **experimental**) |
| `biomed_retrieve_compounds` | `smiles_or_name`, `top_k?`, `kb_name?` | chemical ANN hits (biomed profile, **experimental**) |
| `lakehouse_bi_query_semantic_context` | `question`, `kb_name?` | semantic context pack (lakehouse-bi profile, **in development**) |
| `lakehouse_bi_retrieve_historical_analysis` | `topic`, `kb_name?` | historical analysis chunks (**in development**) |

When `kb_name` is omitted it falls back to `settings.kb_name`. Enable a domain with `EAGLE_RAG_PROFILE=biomed` (**experimental**) or `EAGLE_RAG_PROFILE=lakehouse-bi` (**in development**) — see `eagle_rag/settings.yaml` `profiles:`. Production default remains `core`.

## Directory structure

```
eagle-rag/
├─ eagle_rag/            # backend
│  ├─ admin/             # admin dashboards (probes / metrics / system_setting / mcp_log)
│  ├─ api/               # FastAPI routes (app / query / ingest / documents / health / mcp_server / mcp_http)
│  ├─ attachments/       # lazy parse of QA attachments
│  ├─ db/                # SQLModel + Alembic models
│  ├─ generation/        # multimodal generation engine
│  ├─ images/            # image store
│  ├─ index/             # Milvus stores (milvus_text_store / milvus_visual_store / registry)
│  ├─ ingest/            # ingestion pipeline (router / selectors / knowhere_adapter / pixelrag_adapter / runner / preprocess)
│  ├─ kb/                # knowledge-base lifecycle and health
│  ├─ notifications/     # notifications
│  ├─ plugins/           # microkernel (PluginManager / HookBus / orchestrators / core_defaults)
│  ├─ retrievers/        # retrievers (knowhere_graph_retriever / pixelrag_visual_retriever)
│  ├─ router/            # router engine (router_engine / llm_factory / models / selectors)
│  ├─ sessions/          # session store
│  ├─ storage/           # MinIO client + dedup
│  ├─ tasks/             # Celery (celery_app / dead_letter / state)
│  ├─ telemetry/         # structured logging + OpenTelemetry
│  └─ config.py  settings.yaml
├─ plugins/              # in-repo domain plugins (biomed experimental / lakehouse_bi in-dev / _template)
├─ frontend/             # Next.js + Bun + HeroUI v3 (Core showcase only)
├─ docker/               # Dockerfiles (api / worker / frontend / docs / mcp) + knowhere-self-hosted
├─ tests/  examples/  design/
├─ docs/                 # MkDocs Material bilingual (zh / en)
├─ docker-compose.yml  Taskfile.yml  mkdocs.yml  pyproject.toml
└─ README.md  README.zh.md  AGENTS.md
```

## Documentation

- **English docs** → [docs/en/index.md](docs/en/index.md)
- **中文文档** → [docs/zh/index.md](docs/zh/index.md)
- **Learning path** → [docs/en/learning-path.md](docs/en/learning-path.md) (curated RAG reading order)
- **Architecture** → [docs/en/architecture/index.md](docs/en/architecture/index.md) · [Plugin architecture](docs/en/architecture/plugin-architecture.md) · [Multimodal fusion](docs/en/architecture/multimodal-fusion.md)
- **API reference** → [docs/en/api/index.md](docs/en/api/index.md)
- **MCP tools** → [docs/en/api/mcp-tools.md](docs/en/api/mcp-tools.md)

## Knowledges

Eagle-RAG builds on the following open-source projects and services:

| Project | Role in Eagle-RAG |
| --- | --- |
| [**Milvus**](https://milvus.io/docs) | Vector database for dual collections `eagle_text` (1536-d text) and `eagle_visual` (2048-d visual); HNSW / DiskANN ANN plus scalar filters on `kb_name`, `document_id`, and semantic-tree anchor fields. |
| [**Ontos-AI/Knowhere**](https://github.com/Ontos-AI/knowhere) | External document semantic parser (`:5005`, `knowhere-python-sdk`); produces typed chunks, section tree (`doc_nav`), and knowledge-graph edges for the text pipeline. |
| [**PixelRAG**](https://github.com/StarTrail-org/PixelRAG) | In-process visual encoder + slicer (`pixelrag_render` + `pixelrag_embed`); renders scanned PDFs / images / web pages into tiles and Qwen3-VL-Embedding-2B vectors for `eagle_visual`. |
| [**MinerU**](https://github.com/opendatalab/MinerU) | PDF layout/OCR engine used by the Knowhere self-hosted stack for first-pass PDF parsing (`MINERU_API_KEYS` / `MINERU_URL` in `docker/knowhere-self-hosted/`); not invoked directly by Eagle-RAG, but required when Knowhere is deployed with MinerU-backed PDF extraction. |

## License

[Apache License 2.0](LICENSE). See [NOTICE](NOTICE) for third-party attributions (Milvus, Knowhere, PixelRAG, MinerU, LlamaIndex).
