# AGENTS.md

> Rules and constraints for AI coding agents. Read this file before modifying the repository.

Eagle-RAG is an **industry-agnostic, multi-tenant (`kb_name`) multimodal RAG** data layer for Agents and LLMs. Do not reintroduce finance-specific hardcoding.

## Module boundaries

| Module | Role | Integration |
| --- | --- | --- |
| **Knowhere** ([Ontos-AI/knowhere](https://github.com/Ontos-AI/knowhere)) | Document semantic parser, external HTTP `:5005` | Official `knowhere-python-sdk` (`import knowhere`): `Knowhere(api_key, base_url).parse(file=...)` → in-memory `ParseResult` via `/v1/jobs` (create→upload→poll→download). See `eagle_rag/ingest/knowhere_adapter.py` |
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

- **Backend**: Python ≥ 3.12, `uv sync`. Pass `ruff check`, `ruff format`, `mypy eagle_rag`. Docstrings/comments in **English**, Google style. No TODO/FIXME/personal notes or comments that restate the code.
- **DB**: Alembic + SQLModel (`eagle_rag/db/models/`). Deploy with `task db:migrate`. No DDL in stores.
- **API schemas**: `eagle_rag/api/schemas/`; routers use `response_model`.
- **Frontend**: Next.js 16, React 19, TypeScript, Bun, Biome, HeroUI v3, Tailwind v4, **light-only**, `next-intl` (zh/en). Pass `bun run lint` / `format`.
- **Config**: `eagle_rag/settings.yaml` `${VAR:-default}` + `config.py` pydantic models.
- **API**: No auth (intranet). New endpoints supporting multi-tenant must accept `kb_name` (fallback `settings.kb_name`).
- **Attachments**: `POST /attachments`; lazy parse on query (`eagle_rag/attachments/parser.py`), no Milvus write.
- **Streaming**: `POST /query/stream` SSE (`session`/`step`/`sources`/`token`/`done`); `POST /search` / `/search/stream` for retrieval-only.
- **Evidence**: `GET /documents/{id}/structure`, `/file`, `/chunks/{chunk_id}`.
- **Celery**: `router_queue` (4) / `knowhere_queue` (8) / `pixelrag_queue` (1); `with_retry` + dead letter.
- **MCP**: FastMCP at `/mcp` (HTTP default, stdio fallback). Tools: `ingest`, `query`, `retrieve_text`, `retrieve_visual`. Register new tools in `eagle_rag/api/mcp_server.py` + `TOOL_DEFINITIONS`.
- **Do not** proactively create `*.md` docs or commit `.env` secrets.

## Sync on architecture changes

Update `README.md`, `AGENTS.md`, `docs/en/architecture/multimodal-fusion.md`, `docs/zh/architecture/multimodal-fusion.md`, and `eagle_rag/settings.yaml` when behavior changes.
