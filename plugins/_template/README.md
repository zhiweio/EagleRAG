# Industry plugin template (RAG-only)

Copy this directory to `plugins/<your_namespace>/`, rename the package, and set
`namespace` / `EAGLE_RAG_PROFILE` so `default_namespace` matches.

## What to ship

| Deliverable | Required |
| --- | --- |
| Backend Python module under `plugins/` | Yes |
| Hook subscribers (PARSE / CHUNK / CLASSIFY_* / QUERY_ASSEMBLE / …) | As needed |
| MCP tools via `@register_mcp_tool` + `register_mcp_tools()` | Yes (for Agent consumers) |
| Deployment profile in `settings.yaml` `profiles:` | Yes |
| Frontend / demo UI | **No** — domain plugins are backend + MCP only |

## Allowed

- Domain chunking, typed metadata, specialized encoders/collections
- Query expansion / entity hints via `QUERY_ASSEMBLE`
- Read-only MCP tools that return context packs + sources

## Forbidden

- Business Agent workflows, multi-step planning, approvals
- Side-effect MCP tools (`execute_sql`, `send_email`, …)
- Vertical frontend pages in this repository

See `docs/zh/guides/authoring-industry-plugin.md`.
