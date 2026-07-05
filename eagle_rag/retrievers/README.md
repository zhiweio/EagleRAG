# Retrievers (`eagle_rag/retrievers/`)

LlamaIndex retrievers over Milvus text and visual collections.

## Purpose

- **Text**: vector ANN + `connect_to` graph expansion on Knowhere chunks.
- **Visual**: embed query with Qwen3-VL encoder, search `eagle_visual` tiles.
- Push `kb_name` and scope filters down to Milvus scalar `expr`.

## Key files

| File | Role |
| --- | --- |
| `knowhere_graph_retriever.py` | Text retrieval + graph expansion; section_summary parent-document path |
| `pixelrag_visual_retriever.py` | Visual tile search; returns `ImageNode` with fusion anchors |

## Integration points

- **Index**: `eagle_rag.index.milvus_text_store`, `milvus_visual_store`.
- **Router**: `eagle_rag.router.router_engine` selects text/visual/hybrid and calls retrievers.
- **MCP**: `retrieve_text` / `retrieve_visual` tools wrap the same retrieval layer.
- **Scope**: `ScopeSelection` from API resolved in `router_engine._resolve_scope_filter`.

## Constraints (from AGENTS.md)

- Text embeddings: Qwen `text-embedding-v4` (1536-d); visual: Qwen3-VL-Embedding-2B (2048-d).
- Visual nodes carry fusion anchors: `chunk_type`, `parent_section`, `content_summary`, `source_chunk_id`.
- Fail-soft: retrievers return `[]` on dependency errors; router handles degradation.
- No OpenAI / Cohere adapters.
