# Index (`eagle_rag/index/`)

Milvus-backed storage, document registry, tag catalog, and structure reconstruction.

## Purpose

- Maintain dual collections: `eagle_text` (1536-d) and `eagle_visual` (2048-d).
- Register documents, chunk counts, and `doc_nav` semantic trees.
- Expose tag catalog and per-document structure for scope filter and evidence UI.

## Key files

| File | Role |
| --- | --- |
| `milvus_text_store.py` | Text upsert/search, `ensure_collection`, kb_name filters |
| `milvus_visual_store.py` | Visual upsert/search, HNSW/DiskANN, fusion anchor fields |
| `registry.py` | Document metadata registry (PostgreSQL-backed) |
| `tag_catalog.py` | Keyword/tag aggregates for `GET /tags` |
| `document_structure.py` | Reconstruct `doc_nav` sections for evidence viewer |

## Integration points

- **Ingest**: Knowhere/PixelRAG tasks call `upsert_text_nodes` / `upsert_visual`.
- **Retrievers**: `get_text_index()`, `search_visual()`, embed_query paths.
- **API**: `/documents`, `/documents/{id}/structure`, `/tags`.
- **Dedup**: composite PK `(sha256, kb_name)` coordinated with `eagle_rag.storage`.

## Constraints (from AGENTS.md)

- Milvus scalar filter example: `expr="kb_name == 'pharma' and year in [2025,2026]"`.
- Visual index type via `MILVUS_VISUAL_INDEX_TYPE` (`hnsw` / `diskann`); no FAISS.
- Schema changes via Alembic/SQLModel only — no DDL in store modules.
- `nullable=True` on new Milvus fields; migrate with `add_collection_field`, avoid drop-rebuild when possible.
