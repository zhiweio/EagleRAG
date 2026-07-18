# Glossary — Plugin Architecture (implementation)

| Term | Meaning |
| --- | --- |
| `plugin_namespace` | Instance domain binding (= Milvus Database). Fixed by deploy config; not a runtime UI switcher (G1). |
| `kb_name` | Knowledge-base scalar filter inside one Milvus Database. |
| `EAGLE_RAG_PROFILE` | Activates `settings.yaml` `profiles:` overlay (`core` / `biomed` / `lakehouse-bi`). |
| `plugins.options.<ns>` | Per-plugin knobs (dict); read via `plugin_options(ns)`. Not Core-typed settings. |
| Hot-path hooks | `PARSE` / `CHUNK` / `QUERY_ASSEMBLE` invoked on ingest/query via `hotpath_hooks.py`. |
| RAG-only MCP | Tools retrieve/assemble context only; `assert_rag_only_tool_name` bans side-effect names. |
| Frontend scope | Built-in UI = Core knowhere + pixelrag showcase; domain plugins have no UI in-repo. |
| Base collections | Always-on `eagle_text` + `eagle_visual` inside each domain DB. |
| Specialized collections | Biomed-only extras (`eagle_text_biomed`, `eagle_chemical`, `eagle_medical_*`). |
| Encoder mode | `auto` / `require_native` / `deterministic` — medical encoders never use Qwen3-VL. |
| UMLS subset | Local ontology in `plugins/biomed/routing_rules.yaml` for G15 routing + MCP. |
| Lakehouse connector | User-owned exporter (`LakehouseMetadataConnector`); EagleRAG only ingests files. |
| `_template` | Minimal industry RAG plugin skeleton under `plugins/_template/`. |
