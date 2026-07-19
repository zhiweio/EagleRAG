# ADR-007: Plugin Architecture Implementation Status

- **Status**: Accepted
- **Date**: 2026-07-14 (revised 2026-07-18: encoder labels + UMLS MRCONSO + namespace wiring + BiomedCLIP open_clip + PluginAudit multi-sink)
- **Context**: Record deploy/runtime choices that complement the live [plugin architecture](../plugin-architecture.md) docs.

## Decision

1. **Docker packages `plugins/`** in API/worker/MCP images and mounts `./plugins` in compose override so domain plugins are importable without image rebuild in dev.
2. **Deployment profiles** via `EAGLE_RAG_PROFILE=core|biomed|lakehouse-bi` merge `settings.yaml` `profiles:` (P2-4).
3. **Medical encoders never fall back to Qwen3-VL**. Modes: `deterministic` (CI), `require_native` (prod fail-fast), `auto` (native with optional `EAGLE_BIOMED_ALLOW_DETERMINISTIC=1`).
4. **Biomed encoder labels use public HF checkpoints as real defaults**: `pubmedbert` → microsoft/BiomedNLP-PubMedBERT-..., `molformer` → seyonec/ChemBERTa-zinc-base-v1, `medimageinsight` → microsoft/BiomedCLIP-PubMedBERT_256-... (open_clip), `uni2` → MahmoodLab/UNI2-h. Override via `EAGLE_BIOMED_*_MODEL`. **Radiology (BiomedCLIP) prefers `open_clip`** (`hf-hub:` + `create_model_from_pretrained` / `get_tokenizer`) so image and text towers share one space for text→image ANN on `eagle_medical_radiology`; HF `transformers` remains fallback. Pathology (`uni2`) stays on `transformers`. Optional extra: `uv sync --extra biomed` installs `open-clip-torch`. Core `eagle_visual` / Qwen is unchanged. Text+chemical encoders run without the extra.
5. **Biomed UMLS** ships as an expandable curated subset (~70 entities in `plugins/biomed/routing_rules.yaml` + `umls.py`); point `EAGLE_BIOMED_UMLS_MRCONSO_PATH` at a real UMLS MRCONSO RRF file (NLM license required) to merge additional English aliases/CUIs. Compound MCP uses the `chemical` encoder ANN on `eagle_chemical`.
6. **Lakehouse-bi is under development** and remains retrieval-only; `FileExportLakehouseConnector` is the reference user-extension for metadata export -> ingest. Not production-ready.
7. **`plugin_namespace` wiring closed end-to-end**: Celery ingest tasks (`knowhere_parse`/`pixelrag_build`/`knowhere_visual_chunks`), core retrievers (`KnowhereGraphRetriever`/`PixelRAGVisualRetriever`), the visual store read path (`search_visual`/`count`/`delete`/`fetch`/`distinct_years`), the `RetrieverOrchestrator` core text/visual dispatch, and MCP retrieval tool call sites all thread `plugin_namespace` so a non-core instance binds to its own Milvus Database (G17).
8. **PluginAudit is multi-sink decision telemetry** (`eagle_rag/plugins/audit.py`): every classification/routing/hook decision fans out to (1) AI JSONL via `get_ai_logger` (`event=plugin_audit_decision`, durable), (2) Redis LIST recent window (`LPUSH`+`LTRIM`, cross-process), (3) in-memory ring fallback, (4) Prometheus counters (`plugin_audit_decisions_total`, `plugin_audit_rrf_dedupe_total`). `GET /health/plugins` exposes `recent_decisions` + `audit_stats`. Sinks are best-effort and never fail the hot path. Categories: `scope_routing` tag-resolution failures → `scope_routing_error`; HookBus `invoke_all` degradations → `hook_failure`.

## Consequences

- Default compose profile remains `core` (safe for existing deployments).
- **`plugins/biomed` is experimental**; enabling it requires `EAGLE_RAG_PROFILE=biomed` and restart; first native encoder load may pull HF weights. APIs/collections may change.
- **`plugins/lakehouse_bi` is under development** — reference skeleton only; do not treat as production-stable.
- Architecture docs describe the implemented microkernel (not a planning blueprint).

## Follow-up

See [ADR-008](008-rag-only-plugin-platform.md) for hot-path hook wiring, `plugins.options`, RAG-only MCP naming, and frontend = Core only.
