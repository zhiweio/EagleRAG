# ADR-005: Knowhere vs Eagle Query Boundary

**Status:** Accepted

## Decision

- Eagle uses Knowhere for **parse** and `doc_nav` only.
- Query hot path: Eagle Milvus multi-collection + RRF — **not** Knowhere `RetrievalAgent` / `WorkflowOrchestrator`.
- Parent-document retrieval: two-stage on `eagle_text` in `KnowhereGraphRetriever`.
