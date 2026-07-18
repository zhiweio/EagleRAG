# ADR-005: Knowhere vs Eagle Query Boundary

**Status:** Accepted

## Decision

- Eagle uses Knowhere for **parse** and `doc_nav` only.
- Query hot path: Eagle Milvus multi-collection + RRF — **not** Knowhere `RetrievalAgent` / `WorkflowOrchestrator`.
- Parent-document retrieval: two-stage on `eagle_text` in `KnowhereGraphRetriever`.
- **Structural parse is Knowhere-only** for every industry document: section tree, TOC, typed chunks, and hierarchical `path` must be preserved from Knowhere `ParseResult`.
- **Domain `CHUNK` / `PARSE` hooks enrich only** (metadata, soft labels, optional typed annotations). They must not discard or rewrite Knowhere skeleton fields (`path`, chunk body, `doc_nav`, `section_summary` nodes).
- If a domain needs different split / hierarchy boundaries, change Knowhere parse (upstream / parse-sdk) and consume the new `ParseResult` in Eagle — **do not** implement a from-scratch Eagle chunker.
