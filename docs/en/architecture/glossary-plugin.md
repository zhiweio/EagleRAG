# Glossary — Plugin Architecture (implementation)

| Term | Meaning |
| --- | --- |
| `plugin_namespace` | Instance domain binding (= Milvus Database). Fixed by deploy config; not a runtime UI switcher (G1). |
| `kb_name` | Knowledge-base scalar filter inside one Milvus Database. |
| `EAGLE_RAG_PROFILE` | Activates `settings.yaml` `profiles:` overlay (`core` / `biomed` experimental / `lakehouse-bi` under development). |
| `plugins.options.<ns>` | Per-plugin knobs (dict); read via `plugin_options(ns)`. Not Core-typed settings. |
| Hot-path hooks | `PARSE` / `CHUNK` / `QUERY_ASSEMBLE` invoked on ingest/query via `hotpath_hooks.py`. |
| RAG-only MCP | Tools retrieve/assemble context only; `assert_rag_only_tool_name` bans side-effect names. |
| Frontend scope | Built-in UI = Core knowhere + pixelrag showcase; domain plugins have no UI in-repo. |
| Base collections | Always-on `eagle_text` + `eagle_visual` inside each domain DB. |
| Specialized collections | Biomed-only extras (`eagle_text_biomed`, `eagle_chemical`, `eagle_medical_*`). |
| Encoder labels | Biomed runtime names: `pubmedbert` (768), `molformer` (768), `medcpt-query` / `medcpt-article` (768), `medcpt-rerank` (cross-encoder), `medimageinsight` (1024 BiomedCLIP/`open_clip`), `uni2` (1536). |
| Encoder mode | `auto` / `require_native` / `deterministic` - medical encoders never use Qwen3-VL. `EAGLE_BIOMED_ALLOW_DETERMINISTIC=1` gates hash fallback in `auto` mode. |
| TDR | Tiered Document Router (`plugins/biomed/doc_profile.py`) - 3-tier biomedical vs general classification deciding PubMedBERT vs Core `text-embedding-v4`. |
| Prototype margin | TDR Tier-1 signal: `score_bio - score_gen` (PubMedBERT cosine vs biomedical/general prototype vectors). |
| IMRaD section tag | `biomed_section` metadata stamped by `chunker.biomed_chunk_transform` (`abstract` / `methods` / `results` / `claims` / `indications_and_usage` / `warnings` / `dosage` / `body`). |
| `primary_drugs` | Per-node drug list stamped at ingest (cap 8); enables zero-rescan `entity_boost_score` at query. |
| MedCPT CE | `medcpt-rerank` cross-encoder used in Tier-2 `RERANK_MERGED` (min-max normalized logits). |
| Cross-drug penalty | Tier-2 signal: 1.0 when `primary_drugs` metadata is disjoint from query drugs; multiplied by `w_xdrug_penalty` (2.0-3.0) and subtracted. |
| Entity-anchored supplement | `supplement_entity_anchored_hits` - PG registry name lookup + scoped ANN; filename-agnostic. Injected via `RRF_POST_MERGE` when `require_entity_match`. |
| Letter-boundary matching | `umls._entity_pattern` - `EGFR` won't fire inside `VEGFR`, `MET` won't fire inside `metastatic`; `VEGFR` still matches `VEGFR1-3`, `PD-1` preserved. |
| Chemical re-rerank | Tier-2 special path for `chemical` workflow: re-rank entity-matched nodes with MolFormer cosine; take the higher of (fused, MolFormer) score. |
| `exclusive_group` | On `ClassificationDecision`; skips dual-write within the same group (e.g. `biomed_text` -> `eagle_text_biomed` XOR `eagle_text`). |
| Rerank policy | `domain` (plugin `RERANK_MERGED`) / `general` (Core `qwen3-rerank`) / `none` (passthrough). Biomed default: `domain`. |
| BiomedCLIP / `open_clip` | `medimageinsight` encoder loaded via `open_clip` so text + image towers share one embedding space (enables text -> radiology cross-modal retrieval). |
| `EAGLE_BIOMED_*` env | `EAGLE_BIOMED_ENCODER_MODE`, `EAGLE_BIOMED_ALLOW_DETERMINISTIC`, `EAGLE_BIOMED_*_MODEL` (checkpoint overrides), `EAGLE_BIOMED_UMLS_MRCONSO_PATH`, `EAGLE_BIOMED_OPENCLIP_ARCH`/`_PRETRAINED`. |
| UMLS subset | Curated ontology in `plugins/biomed/routing_rules.yaml` + `umls.py` for G15 routing + MCP. |
| MRCONSO merge | Optional `EAGLE_BIOMED_UMLS_MRCONSO_PATH` — ENG + `ISPREF=Y` aliases/CUIs (NLM license). |
| PluginAudit | Multi-sink decision telemetry (`audit.py`): AI JSONL + Redis `eagle:plugin_audit:{ns}:recent` + memory ring + Prometheus. |
| Audit categories | e.g. `classify_chunk`, `route_query`, `scope_routing_error`, `hook_failure`. |
| Lakehouse connector | User-owned exporter (`LakehouseMetadataConnector`); EagleRAG only ingests files. |
| `_template` | Minimal industry RAG plugin skeleton under `plugins/_template/`. |
