# ADR-003: MCP Tool Naming and Registration

**Status:** Accepted

## Decision

- Tool names: `{namespace}_{name}` with underscores (`core_ingest`, `biomed_query_entities`).
- `PluginManager.register_mcp_tools()` exposes only `core_*` + tools from `default_namespace` plugin (G3).
- No legacy aliases for pre-plugin tool names.
