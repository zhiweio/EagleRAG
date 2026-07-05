# Ingest (`eagle_rag/ingest/`)

Routes uploaded files and URLs into Knowhere or PixelRAG parsing pipelines, then dispatches Celery work.

## Purpose

- Decide pipeline(s) from **format + content form** (not `source_type` metadata).
- Invoke Knowhere SDK or PixelRAG library adapters.
- Emit text nodes, visual chunk jobs, and document registry updates.

## Key files

| File | Role |
| --- | --- |
| `router.py` | `route()` + `ingest_router` Celery entry; strategy chain in `selectors.py` |
| `selectors.py` | Prefix / forced mode / URI / PDF probe / extension / content-type selectors |
| `knowhere_adapter.py` | Knowhere SDK `parse()` → text nodes, `doc_nav`, visual dispatch |
| `pixelrag_adapter.py` | `pixelrag_render` + `pixelrag_embed` → visual tiles (2048-d) |
| `runner.py` | `ingest_file()` API/MCP entry; dedup, KB validation, task enqueue |
| `preprocess.py` | Local temp files, MIME hints |
| `url_validator.py` | URL reachability checks for `/ingest` |

## Integration points

- **Celery**: `ingest_router` (`router_queue`) → `knowhere_parse` (`knowhere_queue`) / `pixelrag_build` (`pixelrag_queue`, concurrency 1).
- **Index**: `eagle_rag.index.milvus_*_store` upserts; MinIO for originals and tiles.
- **KB**: `eagle_rag.kb.registry` validates `kb_name` before ingest.
- **API**: `eagle_rag.api.ingest` (`POST /ingest`, task audit routes).

## Constraints (from AGENTS.md)

- Knowhere = external HTTP `:5005` via official SDK; no mock on failure.
- PixelRAG = in-process library only; no `pixelrag-serve`, no FAISS, no `pixelrag.build()`.
- Override order: `knowhere:` / `pixelrag:` filename prefix → `settings.router.mode` → PDF form probe → extension defaults.
- Propagate `kb_name` on every task kwargs; dedup PK is `(sha256, kb_name)`.
- Do not reintroduce LibreOffice or finance-specific routing keywords.
