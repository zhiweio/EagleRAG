# ADR-007: Plugin Architecture Implementation Status

- **Status**: Accepted
- **Date**: 2026-07-14
- **Context**: Record deploy/runtime choices that complement the live [plugin architecture](../plugin-architecture.md) docs.

## Decision

1. **Docker packages `plugins/`** in API/worker/MCP images and mounts `./plugins` in compose override so domain plugins are importable without image rebuild in dev.
2. **Deployment profiles** via `EAGLE_RAG_PROFILE=core|biomed|lakehouse-bi` merge `settings.yaml` `profiles:` (P2-4).
3. **Medical encoders never fall back to Qwen3-VL**. Modes: `deterministic` (CI), `require_native` (prod fail-fast), `auto` (native with optional `EAGLE_BIOMED_ALLOW_DETERMINISTIC=1`).
4. **Biomed UMLS** ships as an expandable local subset (`plugins/biomed/routing_rules.yaml` + `umls.py`); compound MCP uses MolFormer ANN on `eagle_chemical`.
5. **Lakehouse-bi** remains retrieval-only; `FileExportLakehouseConnector` is the reference user-extension for metadata export → ingest.

## Consequences

- Default compose profile remains `core` (safe for existing deployments).
- Enabling biomed requires `EAGLE_RAG_PROFILE=biomed` and restart; first native encoder load may pull HF weights.
- Architecture docs describe the implemented microkernel (not a planning blueprint).

## Follow-up

See [ADR-008](008-rag-only-plugin-platform.md) for hot-path hook wiring, `plugins.options`, RAG-only MCP naming, and frontend = Core only.
