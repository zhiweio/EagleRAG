# Glossary

Consistent terminology used across Eagle-RAG documentation. Code identifiers and configuration keys remain in English.

---

## Core concepts

### RAG (Retrieval-Augmented Generation)

Answering from **retrieved knowledge** rather than parametric memory alone. Formulated by [Lewis et al., 2020](https://arxiv.org/abs/2005.11401): embed the query, retrieve top-\(k\) chunks from a vector index, condition the LLM on those chunks, generate with citations.

**Eagle-RAG:** `EagleRouterQueryEngine.retrieve()` → `EagleMultimodalQueryEngine.custom_query()`.

### Eagle-RAG

This project: an industry-agnostic, multi-tenant multimodal RAG **data layer** for Agents and LLMs. Not a standalone chat product — it exposes REST, SSE, and MCP for upstream agents and the Next.js frontend.

### Knowledge Base (KB)

A tenant isolation unit identified by `kb_name`. Each KB owns documents, vectors, sessions, tasks, and optional per-KB settings (e.g. `pdf_text_page_ratio`).

**Storage:** Rows in `knowledge_bases` table; vectors filtered in shared Milvus collections.

### Multi-tenancy

Isolation model where `kb_name` threads through API, Celery kwargs, Milvus scalar filters, PostgreSQL columns, and the dedup composite key `(sha256, kb_name)`.

**Isolation model:** `kb_name` threads through API, Celery kwargs, Milvus scalar filters, PostgreSQL columns, and dedup key `(sha256, kb_name)`.

**Critical tension:** correctness of `kb_name` / `scope_filter` pushdown on every query path — a missing filter in one code path is a data leak, not a performance issue.

### `kb_name`

Knowledge base identifier matching `^[a-z0-9_]+$`. Default: `default` (`KB_NAME` env). Immutable after creation.

**Code:** `get_settings().kb_name` fallback when API omits tenant; explicit `kb_name` per request recommended for agents.

### Hybrid search

Combining vector ANN with metadata filters and/or graph expansion.

| Layer | Eagle-RAG hybrid mechanism |
| --- | --- |
| Vector + scalar | Milvus `expr` on `kb_name`, `document_id`, `chunk_type`, `parent_section` |
| Graph expansion | `metadata["connect_to"]` on Knowhere text nodes — `KnowhereGraphRetriever` |

References: [Milvus hybrid search](https://milvus.io/docs/multi-vector-search.md); [Gao RAG survey](https://arxiv.org/abs/2312.10997).

### Multimodal

Using both **text** and **image** modalities in retrieval and generation. Text chunks in `eagle_text` (1536-d); visual tiles in `eagle_visual` (2048-d). VLM (Qwen-VL-Max) reads both in one prompt.

Motivation: [MuRAG, Chen et al., 2022](https://arxiv.org/abs/2210.02928).

### Parent-document retrieval

Two-stage pattern for long structured documents:

1. **Stage 1:** Recall `type="section_summary"` nodes from `sections_to_text_nodes()` (id `sec_{sha1(document_id:path)[:16]}`).
2. **Stage 2:** Drill down to fine-grained chunks by `path` prefix match.

Avoids retrieving hundreds of leaf chunks when a section summary suffices.

### ANN (Approximate Nearest Neighbor)

Sub-linear similarity search in high dimensions. Eagle-RAG uses Milvus **HNSW** (default) or **DiskANN** on `eagle_visual`; text collection via LlamaIndex `MilvusVectorStore`.

| Index | Paper | When to use |
| --- | --- | --- |
| HNSW | [Malkov & Yashunin, 2016](https://arxiv.org/abs/1603.09320) | In-memory, low latency |
| DiskANN | [Subramanya et al., 2019](https://papers.nips.cc/paper/2019/hash/09853c7ff1cb93b59a86b8e886786b9b-Abstract.html) | Vectors exceed RAM |

---

## Pipelines and parsers

### Knowhere

External document semantic parser ([Ontos-AI/knowhere](https://github.com/Ontos-AI/knowhere)) on HTTP `:5005`.

**Integration:** `knowhere-python-sdk` — `Knowhere(api_key, base_url).parse(file=...)` → in-memory `ParseResult` via `/v1/jobs` (create → upload → poll → download).

**Code:** `eagle_rag/ingest/knowhere_adapter.py` — `parse_with_knowhere_sdk()`, `knowhere_parse` Celery task.

**Output:** Typed chunks (`text` / `image` / `table`), `doc_nav.sections` semantic tree, `connect_to` graph edges.

### PixelRAG

Visual encoder + slicer library ([StarTrail-org/PixelRAG](https://github.com/StarTrail-org/PixelRAG)).

**Eagle-RAG usage:** `pixelrag_render` slices pages; `_Qwen3VLVisualEncoder` embeds tiles. **No** `pixelrag-serve`, **no** FAISS — vectors go to Milvus.

**Code:** `eagle_rag/ingest/pixelrag_adapter.py` — `pixelrag_build`, `knowhere_visual_chunks`.

### Semantic-tree anchored fusion

Design linking PixelRAG visual tiles back to Knowhere's semantic skeleton via four anchor fields on `eagle_visual`. Enables section-scoped visual search and VLM context without SQL JOINs.

See [Multimodal fusion](architecture/multimodal-fusion.md).

### Routing matrix

Four-priority **ingest** decision chain in `eagle_rag/ingest/router.py`:

1. Filename prefix (`knowhere:` / `pixelrag:`)
2. `settings.router.mode` when not `auto`
3. PDF form probe (`probe_pdf_form`)
4. Extension / content-type / default

**Not** the same as query-time routing in `route_query()`.

### Ingest

End-to-end flow: accept document → dedup → upload MinIO → `ingest_router` → `route()` → parse → embed → Milvus upsert → registry `ready`.

**Entry:** `POST /ingest` → `eagle_rag/ingest/runner.py`.

### `source_type`

Metadata-only tag: `policy` / `financial` / `business` / `bidding` / `tax` / `other`. Inferred by `infer_source_type()` from filename/URI keywords. **Does not influence routing.**

**Use:** Milvus scalar filter facet; QA scope UI.

---

## Storage and vectors

### Milvus

Vector database ([milvus-io/milvus](https://github.com/milvus-io/milvus)) hosting `eagle_text` and `eagle_visual` on one cluster. Scalar inverted indexes on `kb_name`, `document_id`, `parent_section`, etc. enable hybrid filter + ANN in one query.

### `eagle_text`

Milvus collection for **1536-d** text vectors (Qwen `text-embedding-v4`). Managed via LlamaIndex `MilvusVectorStore` in `eagle_rag/index/milvus_text_store.py`.

**Nodes:** Knowhere chunks + `section_summary` nodes; metadata includes `path`, `connect_to`, `kb_name`, `document_id`.

### `eagle_visual`

Milvus collection for **2048-d** visual vectors (Qwen3-VL-Embedding-2B). Managed via `pymilvus.MilvusClient` in `eagle_rag/index/milvus_visual_store.py`.

**Index:** HNSW `M=16`, `efConstruction=256`, `metric_type=IP` (L2-normalized → cosine).

### HNSW

Hierarchical Navigable Small World graph index. Default for `eagle_visual`. Search param `ef=64` at query time.

### DiskANN

Disk-resident Vamana graph. Set `MILVUS_VISUAL_INDEX_TYPE=diskann` when visual entity count exceeds memory budget (`kb.visual_entity_limit`).

### Graph expansion

For each text node retrieved by ANN, `KnowhereGraphRetriever` pulls related nodes from `metadata["connect_to"]` — Knowhere's cross-chunk knowledge graph.

### Inner product (IP) vs cosine

For L2-normalized vectors \(\|\mathbf{a}\| = \|\mathbf{b}\| = 1\): \(\mathbf{a} \cdot \mathbf{b} = \cos\theta\). Eagle-RAG normalizes visual embeddings before upsert; Milvus uses `metric_type=IP`.

---

## Fusion anchor fields (`eagle_visual`)

| Field | Definition | Milvus filter |
| --- | --- | --- |
| **`chunk_type`** | `tile` (PixelRAG page slice) / `image` (Knowhere image chunk) / `table` (Knowhere table chunk) | EQ |
| **`parent_section`** | `path` of nearest preceding text chunk — section affiliation | LIKE |
| **`content_summary`** | Knowhere visual summary — text context for VLM prompt | — |
| **`source_chunk_id`** | Knowhere `chunk_id` — cross-collection link to `eagle_text` | EQ |

**Written by:** `upsert_visual()` / `upsert_visual_batch()` after `extract_visual_chunks()` or `pixelrag_build`.

### `section_summary`

`type` metadata on section-summary `TextNode`s from `sections_to_text_nodes()`. Stable id: `sec_{sha1(document_id:path)[:16]}`.

---

## Query and generation

### Router Engine

`EagleRouterQueryEngine` in `eagle_rag/router/router_engine.py`. Combines `KnowhereGraphRetriever` and `PixelRAGVisualRetriever` based on `route_query()` decision.

### Scope filter

`ScopeSelection{kb_names, document_ids, tags}` — union (OR) semantics. Resolved by `_resolve_scope_filter()`; tags → document IDs via `resolve_tags_to_document_ids()`. Persisted in `sessions.scope_filter`.

### VLM (Vision-Language Model)

Qwen-VL-Max (configurable via `vlm.model`). Generates answers over text chunks and image tiles in `EagleMultimodalQueryEngine`.

### Rerank

Post-retrieval reordering via DashScope `qwen3-rerank` (`qwen3-rerank` family). Applied before VLM prompt construction.

---

## Operations and integration

### MCP (Model Context Protocol)

[Model Context Protocol](https://modelcontextprotocol.io/) — exposes `ingest` / `query` / `retrieve_text` / `retrieve_visual` to Agents at `/mcp` (HTTP) or stdio.

**Code:** `eagle_rag/api/mcp_server.py`, `TOOL_DEFINITIONS`.

### SSE (Server-Sent Events)

Streaming transport for query answers (`session` / `step` / `sources` / `token` / `done`), task progress, and live logs.

### Task state machine

`PENDING → RENDERING → EMBEDDING → INDEXING → SUCCESS` (+ `RETRYING` / `FAILED`). Enforced by `ALLOWED_TRANSITIONS` in `eagle_rag/tasks/state.py`.

### Dead letter queue

Celery queue `dead_letter` for messages that exhausted retries. Inspectable via `drain_dead_letter()`; replay via `replay_dead_letter()`.

**Decorator:** `@with_retry` on `ingest_router`, `knowhere_parse`, `pixelrag_build`.

### Sidecar cache

`{storage_path}.parsed.json` caching attachment parse results. Avoids re-parsing on repeat queries. Config: `attachments.parse.cache_enabled`.

### Lazy initialization

No service connects at import. `get_settings()`, Milvus clients, `_Qwen3VLVisualEncoder` construct on first use — `@lru_cache` or module-level singletons.

### Graceful degradation

External failure degrades a **feature**, not the process. Examples: retriever exception → `[]`; tag resolution failure → ignore tags; visual dispatch failure → text index still succeeds.

### `unknown` vs `down` (health)

`/health` probe status: `unknown` = not configured / not probed; `down` = probed and failed. PixelRAG reports `unknown` when visual provider is not `pixelrag`.

---

## Celery queues

| Queue | Concurrency | Tasks |
| --- | --- | --- |
| `router_queue` | 4 | `ingest_router` |
| `knowhere_queue` | 8 | `knowhere_parse` |
| `pixelrag_queue` | 1 | `pixelrag_build`, `knowhere_visual_chunks` |

`pixelrag_queue` concurrency **must stay low** — Chromium rendering is OOM-prone.

---

## References

- [Lewis et al., 2020](https://arxiv.org/abs/2005.11401)
- [Gao et al., 2023](https://arxiv.org/abs/2312.10997)
- [MuRAG](https://arxiv.org/abs/2210.02928)
- [HNSW](https://arxiv.org/abs/1603.09320)
- [Milvus documentation](https://milvus.io/docs)
- [LlamaIndex glossary](https://docs.llamaindex.ai/)
- [Knowhere](https://github.com/Ontos-AI/knowhere)
- [PixelRAG](https://github.com/StarTrail-org/PixelRAG)
- [MCP specification](https://modelcontextprotocol.io/)
