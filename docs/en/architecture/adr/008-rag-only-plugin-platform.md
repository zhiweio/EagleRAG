# ADR-008: RAG-Only Plugin Platform + Frontend Scope Lock

- **Status**: Accepted
- **Date**: 2026-07-14
- **Context**: Close dead hooks, Core industry coupling, and thin plugin DX while keeping EagleRAG a pure RAG data layer (not a business Agent platform).

## Decision

1. **Product red line**: EagleRAG does ingest / retrieve / assemble-context / admin-metadata only. Domain plugins improve recall quality; they must not grow Agent behavior or side-effect MCP tools.
2. **Hot-path hooks**: `PARSE`, `CHUNK`, and `QUERY_ASSEMBLE` are invoked on ingest/query paths via `eagle_rag/plugins/hotpath_hooks.py`.
3. **Core decoupling**: Per-plugin knobs under `settings.plugins.options[<namespace>]`. Core `source_type.rules` default empty. Reconstruct fans out specialized collections from the plugin manifest.
4. **MCP**: Explicit `register_mcp_tools()`; RAG-only naming (`assert_rag_only_tool_name`); G3 namespace filter.
5. **Frontend scope**: Built-in UI = **Core** knowhere + pixelrag hybrid showcase. Domain plugins = **backend + MCP only**.
6. **SDK**: `plugins/_template/` + Chinese authoring guide under `docs/zh/guides/`.

## Consequences

- New verticals ship as module + profile + MCP without Core edits or frontend.
- Documentation separates Core UI vs domain MCP.
