# ADR-004: Multi-Encoder RRF Fusion

**Status:** Accepted

## Decision

- Core `QueryRouteClassifier` never auto-queries specialized collections (G4).
- `RetrieverOrchestrator` runs per-plan ANN; per-plan `RERANK`; merge via `merge_rrf` (G8).
- Cross-collection dedupe by `source_chunk_id` or `(document_id, path)` (G32).
- Single-plan failures are best-effort skipped (G14).
