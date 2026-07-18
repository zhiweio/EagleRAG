# Authoring an industry RAG plugin

Eagle-RAG is a **pure RAG data layer**: industry plugins only improve vertical **recall quality / precision / asset structure**, then hand context to downstream Agents via **MCP (primary) / API**. This repository **does not provide or require** domain frontends.

Chinese canonical copy: [`docs/zh/guides/authoring-industry-plugin.md`](../../zh/guides/authoring-industry-plugin.md).

## Product boundary

| Do | Don't |
| --- | --- |
| Ingest / chunk / encode / multi-collection retrieve / RRF / provenance | Business workflows, multi-step Agent planning |
| Return structured context packs + sources | Text-to-SQL execution, DB mutation, email, orders |
| Domain chunking, specialized encoders, entity expansion | Domain Agent UI / demo pages |

**Built-in frontend = Core showcase** (knowhere semantic structure + pixelrag visual hybrid). Verticals are backend + MCP only.

## Deliverables checklist

1. `plugins/<namespace>/` — implement the `Plugin` protocol (copy [`plugins/_template/`](../../../plugins/_template/))
2. `register_hooks` — subscribe to hot-path hooks (matrix below)
3. `register_mcp_tools()` — explicit entrypoint; tools via `@register_mcp_tool`, name `{namespace}_{name}`
4. `settings.yaml` → `profiles.<name>` — `enabled` + `default_namespace` + `milvus.db_name`
5. Contract tests (hot-path hooks invoked; MCP bans execution-class names)

Success metric = **recall quality and provenance**, not UI completeness.

## Hook matrix (RAG hot paths)

| Hook | Mode | Insert point | Typical use |
| --- | --- | --- | --- |
| `PARSE` | transform | After Knowhere parse | Parse enrich / DDL → typed |
| `CHUNK` | transform | Before IngestOrchestrator | Domain chunking / metadata |
| `CLASSIFY_CHUNK` / `CLASSIFY_VISUAL` | first | Orchestrator | Route to specialized collections |
| `CLASSIFY_QUERY` | first | Query routing | Multi-collection plans |
| `QUERY_ASSEMBLE` | all (degrade OK) | Before ANN | Query expand / entity hints |
| `EMBED_*` / `UPSERT_VECTORS` | first / transform | Before write | Domain encoders |
| `RERANK` | … | After recall | Domain rerank |

Core invokes `PARSE` / `CHUNK` / `QUERY_ASSEMBLE` on MCP/API hot paths (`eagle_rag/plugins/hotpath_hooks.py`).

## MCP conventions (RAG-only)

- Tool names: `{namespace}_{verb_noun}`, e.g. `biomed_query_entities`, `acme_retrieve_assets`
- Allowed: `retrieve_*`, `query_*`, `list_*`, `get_*_context`, `assemble_*`
- Forbidden: `execute_sql`, `run_sql`, `send_email`, `place_order`, `write_db`, `mutate_*` (blocked by `assert_rag_only_tool_name`)
- One instance exposes `core_*` + `default_namespace` tools only (G3)

## Configuration

```yaml
# settings.yaml
plugins:
  options:
    acme:                    # not a Core-typed field; read via plugin_options("acme")
      some_knob: true

profiles:
  acme:
    plugins:
      enabled: [eagle_rag.plugins.core_defaults, plugins.acme]
      default_namespace: acme
    milvus:
      db_name: acme
```

Enable with `EAGLE_RAG_PROFILE=acme`.

## Minimal steps

1. `cp -r plugins/_template plugins/acme` and rename namespace / class / MCP prefix
2. Implement classifiers or `QUERY_ASSEMBLE` as needed
3. Add a profile; set `EAGLE_RAG_PROFILE=acme` in compose / env
4. Verify recall via MCP or `/search` — **do not** add frontend for acceptance

## Reference implementations

- `plugins/biomed` — specialized collections + encoders + entity MCP
- `plugins/lakehouse_bi` — semantic-layer context packs (read-only retrieval)
- ADR-008: [`docs/en/architecture/adr/008-rag-only-plugin-platform.md`](../architecture/adr/008-rag-only-plugin-platform.md)
