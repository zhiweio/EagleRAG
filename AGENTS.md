# AGENTS.md

> Rules and constraints for AI coding agents. Read this file before modifying the repository.

Eagle-RAG is an **industry-agnostic, multi-tenant (`kb_name`) multimodal RAG** data layer for Agents and LLMs. Do not reintroduce finance-specific hardcoding.

## Language

Follow conventional open-source practice: **English everywhere except Chinese documentation and user-facing Chinese UI copy**.

| Use English | Chinese allowed |
| --- | --- |
| Source code: comments, docstrings, identifiers | `docs/zh/**` |
| Commit messages, PR titles/bodies | `frontend/messages/zh.json` and `messages/fragments/*.zh.json` (i18n only) |
| API/MCP schema descriptions, log messages, config comments | |
| `README.md`, `AGENTS.md`, `docs/en/**`, inline code docs | |
| Taskfile / script descriptions aimed at contributors | |

- Do **not** add Chinese comments, docstrings, or contributor-facing prose in code or config.
- Bilingual docs: keep `docs/en/` and `docs/zh/` in sync when architecture changes; English is the canonical reference for agents and upstream contributors.
- UI strings belong in `next-intl` message files (`en` / `zh`), not hardcoded in components.

## Module boundaries

| Module | Role | Integration |
| --- | --- | --- |
| **Knowhere** ([Ontos-AI/knowhere](https://github.com/Ontos-AI/knowhere)) | Document semantic parser | `knowhere.mode`: **`api`** — `knowhere-python-sdk` → HTTP `:5005` (`Knowhere.parse` via `/v1/jobs`); **`parser`** — [`knowhere-parse-sdk`](https://github.com/zhiweio/knowhere-parse-sdk) in-process (`KnowhereParser.parse`). Both return type-compatible `ParseResult`. See `eagle_rag/ingest/knowhere_adapter.py` |
| **PixelRAG** | Visual encoder + slicer **library** (`pixelrag_render` + `pixelrag_embed`) | Lazy in-process import; fail-fast if missing (no mock). **No `pixelrag-serve`, no FAISS, no `pixelrag.build()`**. See `eagle_rag/ingest/pixelrag_adapter.py` |

**Removed** (do not reintroduce without owner approval): LibreOffice, pixelrag-serve, FAISS, OpenAI, Cohere.

## Routing matrix

`eagle_rag/ingest/router.py` routes by **format + content form**. `source_type` is metadata only.

| Input | Pipeline |
| --- | --- |
| Text-based PDF (form probe) | Knowhere |
| Scanned / image PDF | PixelRAG |
| Word / Excel / CSV / PPTX / Markdown / txt / json | Knowhere |
| Images / URLs / HTML | PixelRAG |
| Unknown extension | Knowhere (fallback) |

Override priority (high → low): filename prefix `knowhere:` / `pixelrag:` → `settings.router.mode` (`text`/`visual`/`hybrid`) → PDF form probe (`probe_pdf_form`) → extension/protocol defaults.

## Multi-tenancy (`kb_name`)

- Identifier per knowledge base (`finance`, `patent`, `pharma`, …); default `default` (`KB_NAME` env).
- Propagate through API, MCP tools, Celery kwargs, Milvus scalar filters, document registry.
- Dedup PK: `(sha256, kb_name)` — same file may exist in multiple KBs.
- Filter example: `expr="kb_name == 'pharma' and year in [2025,2026]"`.

## Models (DeepSeek + Qwen only)

| Use | Model | Dim |
| --- | --- | --- |
| Text LLM / routing | DeepSeek (`deepseek-v4-pro`) | — |
| VLM | Qwen-VL-Max | — |
| Text embedding | Qwen `text-embedding-v4` | 1536 |
| Visual embedding | Qwen3-VL-Embedding-2B (`_Qwen3VLVisualEncoder` singleton) | 2048 |
| Rerank | Qwen `qwen3-rerank` | — |

No OpenAI / Cohere / other vendor adapters. New models via LlamaIndex integration packages.

## Multimodal fusion

Knowhere produces semantic skeleton (`doc_nav.sections` + typed chunks); PixelRAG produces visual tiles (2048-d). Fusion uses **four anchor fields** on `eagle_visual`:

| Field | Purpose |
| --- | --- |
| `chunk_type` | `tile` / `image` / `table` |
| `parent_section` | Nearest text chunk `path` |
| `content_summary` | Knowhere visual summary |
| `source_chunk_id` | Knowhere chunk_id anchor |

Key Celery tasks: `knowhere_parse` (`knowhere_queue`) → text nodes + keyword catalog + visual dispatch + `doc_nav`; `knowhere_visual_chunks` / `pixelrag_build` (`pixelrag_queue`, concurrency 1).

Parent-document retrieval: recall `type="section_summary"` first, drill down by `path` prefix.

### Scope filter

`QueryRequest.scope_filter = ScopeSelection{kb_names, document_ids, tags}` — union (OR) semantics, pushed to Milvus via `router_engine._resolve_scope_filter`. Tag catalog: `document_keywords` table + `GET /tags`. Persisted in `sessions.scope_filter`.

## Coding conventions

- **Backend**: Python ≥ 3.12, `uv sync`. Pass `ruff check`, `ruff format`, `mypy eagle_rag`. Docstrings/comments in **English**, Google style (see [Language](#language)). No TODO/FIXME/personal notes or comments that restate the code.
- **DB**: Alembic + SQLModel (`eagle_rag/db/models/`). Deploy with `task db:migrate`. No DDL in stores.
- **API schemas**: `eagle_rag/api/schemas/`; routers use `response_model`.
- **Frontend**: Next.js 16, React 19, TypeScript, Bun, Biome, HeroUI v3, Tailwind v4, **light-only**, `next-intl` (zh/en). Pass `bun run lint` / `format`. Code comments in **English**; user-visible Chinese only via i18n message files.
- **Config**: `eagle_rag/settings.yaml` `${VAR:-default}` + `config.py` pydantic models.
- **API**: No auth (intranet). New endpoints supporting multi-tenant must accept `kb_name` (fallback `settings.kb_name`).
- **Attachments**: `POST /attachments` accepts a single PixelRAG image (default max 5MB, `attachments.max_image_bytes`); lazy parse on query/search (`eagle_rag/attachments/parser.py`), no Milvus write. MCP `query` / `retrieve_visual` accept inline `image_base64` (no `attachment_id`).
- **Streaming**: `POST /query/stream` SSE (`session`/`step`/`sources`/`token`/`done`); `POST /search` / `/search/stream` for retrieval-only.
- **Evidence**: `GET /documents/{id}/structure`, `/file`, `/chunks/{chunk_id}`.
- **Celery**: `router_queue` (4) / `knowhere_queue` (8) / `pixelrag_queue` (1); `with_retry` + dead letter.
- **MCP**: FastMCP at `/mcp` (HTTP default, stdio fallback). Core tools: `core_ingest`, `core_query`, `core_retrieve_text`, `core_retrieve_visual`. Domain plugins register `{namespace}_{name}` via `eagle_rag/plugins/mcp_registry.py`. Only `core_*` + `default_namespace` plugin tools are exposed per instance (G3).
- **Do not** proactively create `*.md` docs or commit `.env` secrets.

## Plugin architecture (microkernel)

- **Product red line**: Eagle-RAG is a **pure RAG** data layer (ingest / retrieve / assemble context). Domain plugins improve recall; they must **not** add Agent workflows or side-effect MCP tools. See ADR-008.
- **Frontend**: Built-in UI showcases **Core** knowhere + pixelrag hybrid retrieval only. Vertical domains ship as **backend + MCP only** (no domain UI in this repo).
- **Core** registers as namespace `core` via `eagle_rag.plugins.core_defaults` — same hook/MCP extension path as domain plugins.
- **PluginManager** (`eagle_rag/plugins/manager.py`): load from `settings.plugins.enabled` (in-repo modules only; no pip entry_points).
- **Instance binding**: `settings.plugins.default_namespace` = Milvus Database + PG repository filter. Single-domain deploy — no runtime domain switching.
- **HookBus** (`eagle_rag/plugins/hookbus.py`): `invoke_first` / `invoke_all` / `invoke_transform`. Hot-path `PARSE` / `CHUNK` / `QUERY_ASSEMBLE` via `eagle_rag/plugins/hotpath_hooks.py`.
- **Config**: per-plugin knobs under `settings.plugins.options[<namespace>]` (`plugin_options()`); Core `source_type.rules` default empty.
- **Ingest**: `IngestOrchestrator` + `CLASSIFY_*` / `EMBED_*` / `UPSERT_VECTORS` hooks (G22/G26).
- **Query**: `RetrieverOrchestrator` + `QueryRouteClassifier` + RRF merge (`eagle_rag/router/rerank_fusion.py`). Core default never auto-queries specialized collections (G4).
- **Models**: Core uses DeepSeek + Qwen for routing/generation; domain plugins may register domain encoders (e.g. PubMedBERT) via `EncoderRegistry`.
- **Domain plugins**: `plugins/biomed`, `plugins/lakehouse_bi` — enable via profile / `settings.plugins.enabled` + matching `default_namespace`. Template: `plugins/_template/` + `docs/zh/guides/authoring-industry-plugin.md`.

## Sync on architecture changes

Update `README.md`, `AGENTS.md`, `docs/en/architecture/multimodal-fusion.md`, `docs/zh/architecture/multimodal-fusion.md`, `docs/en/architecture/plugin-architecture.md`, `docs/zh/architecture/plugin-architecture.md`, and `eagle_rag/settings.yaml` when behavior changes.
