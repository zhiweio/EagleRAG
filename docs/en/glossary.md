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

A knowledge-base unit identified by `kb_name` **inside** one deployed domain (`plugin_namespace`). Each KB owns documents, vectors, sessions, tasks, and optional per-KB settings (e.g. `pdf_text_page_ratio`).

**Storage:** Namespace-scoped rows in `knowledge_bases`; vectors filtered by `kb_name` scalar on base collections (`eagle_text`, `eagle_visual`) and any domain specialized collections in the same Milvus Database.

### Multi-tenancy

Eagle-RAG isolates data on **two axes** — do not conflate them in API or UI copy:

| Axis | Identifier | Mechanism |
| --- | --- | --- |
| **Domain** | `plugin_namespace` | Milvus **Database** per domain + PostgreSQL repository filter (deploy-time; `settings.plugins.default_namespace` or `EAGLE_RAG_PROFILE`) |
| **Knowledge base** | `kb_name` | Scalar filter **inside** that Database (request-time) |

Within one domain Database, many KBs share base collections and are separated by `kb_name`. Cross-domain retrieval uses **multiple instances**, not Core fan-out across Milvus Databases.

**Propagation:** `plugin_namespace` from instance config; `kb_name` through API, Celery kwargs, Milvus scalar filters, PostgreSQL repositories, and dedup key `(sha256, kb_name, plugin_namespace)`.

**Critical tension:** correctness of `plugin_namespace` binding and `kb_name` / `scope_filter` pushdown on every query path — a missing filter in one code path is a data leak, not a performance issue.

See [Multi-tenancy](architecture/multi-tenancy.md) and [Plugin glossary](architecture/glossary-plugin.md).

### `plugin_namespace`

Deploy-time domain binding (= Milvus Database name). Fixed by `settings.plugins.default_namespace` or `EAGLE_RAG_PROFILE`; **not** a runtime UI switcher. Mismatched explicit `plugin_namespace` on a request returns **403** unless `plugins.allow_namespace_override` (tests only).

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

**Eagle-RAG usage:** `pixelrag_render` slices pages; `get_visual_encoder()` embeds tiles (`pixelrag` local HF or `dashscope` Bailian). **No** `pixelrag-serve`, **no** FAISS — vectors go to Milvus.

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

Free-form metadata tag (e.g. `policy` / `financial` / `other`, or deploy-specific labels). Inferred by `infer_source_type()`: prefers `source_type_hint`, else matches `settings.ingest.source_type.rules` (**Core defaults to `rules: []`** — no finance/tax hardcoding). **Does not influence routing.**

**Use:** Milvus scalar filter facet; QA scope UI.

---

## Storage and vectors

### Milvus

Vector database ([milvus-io/milvus](https://github.com/milvus-io/milvus)) on one cluster. Each **`plugin_namespace`** maps to a Milvus **Database** (`MilvusClientPool`, `db_name=` — no per-request DB switch). Every domain Database has base collections `eagle_text` and `eagle_visual`; domain plugins may add specialized collections (e.g. `eagle_text_biomed`) in the same Database. **KB isolation** is `kb_name` scalar filtering inside that Database, not separate collections per KB. Scalar inverted indexes on `kb_name`, `document_id`, `parent_section`, etc. enable hybrid filter + ANN in one query.

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

[Model Context Protocol](https://modelcontextprotocol.io/) — exposes **`core_ingest`**, **`core_query`**, **`core_retrieve_text`**, **`core_retrieve_visual`** to Agents at `/mcp` (HTTP) or stdio. Domain plugins register `{namespace}_{name}` tools; each instance exposes only `core_*` plus `default_namespace` tools (G3). Tools are **RAG-only** (retrieve / assemble context — no side-effect names).

**Code:** `eagle_rag/api/mcp_server.py`, `eagle_rag/plugins/mcp_registry.py`, `TOOL_DEFINITIONS`.

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

No service connects at import. `get_settings()`, Milvus clients, `get_visual_encoder()` construct on first use — `@lru_cache` or module-level singletons.

### Graceful degradation

External failure degrades a **feature**, not the process. Examples: retriever exception → `[]`; tag resolution failure → ignore tags; visual dispatch failure → text index still succeeds.

### `unknown` vs `down` (health)

`/health` probe status: `unknown` = not configured / not probed; `down` = probed and failed. PixelRAG reports `unknown` when visual provider is not `pixelrag`.

### Microkernel plugins / `plugins.options`

In-process, in-repo plugins (`settings.plugins.enabled`). Vertical knobs live under `plugins.options.<namespace>`, read via `plugin_options()`. See [plugin glossary](architecture/glossary-plugin.md), [ADR-008](architecture/adr/008-rag-only-plugin-platform.md).

### Hot-path hooks

`PARSE` / `CHUNK` / `QUERY_ASSEMBLE` must run on ingest/query hot paths (`hotpath_hooks.py`) — subscribe-only is not enough.

### RAG-only MCP

MCP tools retrieve and assemble context only. Side-effect names like `execute_sql` are rejected (`assert_rag_only_tool_name`). Core tools use the `core_*` prefix.

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
