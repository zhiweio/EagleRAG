# Authoring an industry RAG plugin

Eagle-RAG is a **pure RAG data layer**: industry plugins only improve vertical **recall quality / precision / asset structure**, then hand context to downstream Agents via **MCP (primary) / API**. This repository **does not provide or require** domain frontends.

Chinese canonical copy: `docs/zh/guides/authoring-industry-plugin.md`.

## Product boundary

| Do | Don't |
| --- | --- |
| Ingest / chunk / encode / multi-collection retrieve / RRF / provenance | Business workflows, multi-step Agent planning |
| Return structured context packs + sources | Text-to-SQL execution, DB mutation, email, orders |
| Domain metadata enrich on Knowhere nodes, specialized encoders, entity expansion | Domain Agent UI / demo pages |

**Built-in frontend = Core showcase** (knowhere semantic structure + pixelrag visual hybrid). Verticals are backend + MCP only.

## Deliverables checklist

1. `plugins/<namespace>/` — implement the `Plugin` protocol (copy `plugins/_template/`)
2. `register_hooks` — subscribe to hot-path hooks (matrix below)
3. `register_mcp_tools()` — explicit entrypoint; tools via `@register_mcp_tool`, name `{namespace}_{name}`
4. `settings.yaml` → `profiles.<name>` — `enabled` + `default_namespace` + `milvus.db_name`
5. Contract tests (hot-path hooks invoked; MCP bans execution-class names)

Success metric = **recall quality and provenance**, not UI completeness.

## Hook matrix (RAG hot paths)

| Hook | Mode | Insert point | Typical use |
| --- | --- | --- | --- |
| `PARSE` | transform | After Knowhere parse | Parse enrich / DDL → typed |
| `CHUNK` | transform | Before IngestOrchestrator | Domain metadata enrich only (preserve Knowhere `path` / body / `doc_nav` / `chunk_id`) |
| `INGEST_VISUAL_EXTRACT` | first | Visual ingest | Extract visual chunks + four-anchor fields |
| `CLASSIFY_CHUNK` / `CLASSIFY_VISUAL` | first | Orchestrator | Route to specialized collections; optional `exclusive_group` to skip dual-write |
| `CLASSIFY_QUERY` | first | Query routing | Multi-collection plans |
| `QUERY_ASSEMBLE` | all (degrade OK) | Before ANN | Query expand / entity hints |
| `QUERY_DENSE_EXPAND` | first | Before per-plan ANN | Dense rewrite + sparse terms + `QueryRetrievalIntent` |
| `RERANK` | first | After per-plan ANN | Tier-1 domain rerank (entity filter/boost in plugin) |
| `RETRIEVE_SUPPLEMENT` | all | After per-plan rerank | Entity-anchored or scoped supplemental ANN |
| `RRF_POST_MERGE` | first | After RRF merge | Inject supplement candidates into rerank pool |
| `RERANK_MERGED` | first | After RRF (+ inject) | Cross-encoder / domain merged rerank |
| `EMBED_TEXT` / `EMBED_VISUAL` | first | Before write | Domain encoders via `EncoderRegistry` |
| `UPSERT_VECTORS` | transform | Before write | Persist vectors (default writes Milvus) |
| `RETRIEVE_VISUAL_FILTER` | first | Visual retrieve | Visual filter overrides |
| `CELERY_TASKS` | all | Worker boot | Extra Celery include modules |
| `INGEST_ROUTE_SELECTORS` | first | Format router | Extra format → pipeline selectors |

Core invokes `PARSE` / `CHUNK` / `QUERY_ASSEMBLE` on MCP/API hot paths (`eagle_rag/plugins/hotpath_hooks.py`). `RetrieverOrchestrator` invokes the query hooks above — **Core must not import domain plugins** on that path.

### Query retrieval hook pattern (reference: biomed)

```text
QUERY_DENSE_EXPAND → ANN (+ hybrid if configured) → RERANK
  → RETRIEVE_SUPPLEMENT → RRF → RRF_POST_MERGE → RERANK_MERGED
```

Register handlers in `plugins/<namespace>/retrieval_hooks.py`; domain scoring in a separate module (e.g. `scoring.py`). Declare hybrid collections via `EncoderRegistry.register_collection(..., hybrid_enabled=True)` and/or `settings.router.hybrid_text_collections` in the profile.

Eval harness for biomed: `eval/biomed/` — `RETRIEVAL.md`, `EVAL.md`.

## Observability and audit

From any hook handler, use `ctx.audit.log_decision(...)` (`PluginContext.audit` → `PluginAudit`). Decisions fan out to AI JSONL, Redis recent window, memory ring, and Prometheus (best-effort). Verify load + routing via `GET /health/plugins` (`recent_decisions` / `audit_stats`).

See [ADR-007](../architecture/adr/007-plugin-implementation-status.md) for encoder labels, UMLS/MRCONSO, and PluginAudit sink details.

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
    # biomed example knobs (when namespace=biomed):
    # biomed:
    #   default_dual_text_search: false
    #   exploratory_search_collections: []
    #   encoder_mode: auto   # auto | require_native | deterministic

profiles:
  acme:
    plugins:
      enabled: [eagle_rag.plugins.core_defaults, plugins.acme]
      default_namespace: acme
    milvus:
      db_name: acme
```

Enable with `EAGLE_RAG_PROFILE=acme`.

Biomed-oriented env extras (reference): `EAGLE_BIOMED_ENCODER_MODE`, `EAGLE_BIOMED_*_MODEL`, `EAGLE_BIOMED_UMLS_MRCONSO_PATH`, `EAGLE_BIOMED_ALLOW_DETERMINISTIC`, and `uv sync --extra biomed` for BiomedCLIP/`open_clip`.

## Minimal steps

1. `cp -r plugins/_template plugins/acme` and rename namespace / class / MCP prefix
2. Implement classifiers or `QUERY_ASSEMBLE` as needed; enrich CHUNK metadata only (no from-scratch re-chunk)
3. Add a profile; set `EAGLE_RAG_PROFILE=acme` in compose / env
4. Verify recall via MCP or `/search`, and check `GET /health/plugins` — **do not** add frontend for acceptance

## Reference implementations

- `plugins/biomed` (**experimental**) - specialized collections + encoders + entity-anchored retrieval hooks + IMRaD CHUNK enrich. Full deep dive: [Biomed plugin](../architecture/biomed-plugin.md) + [Biomed retrieval](../architecture/biomed-retrieval.md); eval in `eval/biomed/`
- `plugins/lakehouse_bi` (**under development**) - semantic-layer context packs (read-only retrieval skeleton)
- ADR-007: [`docs/en/architecture/adr/007-plugin-implementation-status.md`](../architecture/adr/007-plugin-implementation-status.md)
- ADR-008: [`docs/en/architecture/adr/008-rag-only-plugin-platform.md`](../architecture/adr/008-rag-only-plugin-platform.md)
