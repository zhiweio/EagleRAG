# API (`eagle_rag/api/`)

FastAPI application, REST/SSE routes, Pydantic schemas, and MCP tool server.

## Purpose

- Expose QA, search, ingest, documents, sessions, tags, health/admin, and attachments.
- Stream progress via SSE (`/query/stream`, `/search/stream`, `/tasks/{id}/stream`).
- Mount MCP at `/mcp` (streamable HTTP) with stdio fallback.

## Key files

| File | Role |
| --- | --- |
| `app.py` | FastAPI app, router aggregation, CORS, MCP mount |
| `query.py` | `/query`, `/search`, sessions/messages |
| `ingest.py` | `/ingest`, `/tasks*` |
| `documents.py` | `/documents`, `/images` |
| `tags.py` | `/tags` tag catalog for scope filter UI |
| `health.py` | `/health`, `/admin/*` ops dashboards |
| `mcp_server.py` | FastMCP tools: `ingest`, `query`, `retrieve_text`, `retrieve_visual` |
| `schemas/` | OpenAPI models (`QueryRequest`, `ScopeSelection`, task audit, etc.) |

## Integration points

- **Router / generation**: `eagle_rag.router`, `eagle_rag.generation` for Q&A and search.
- **Ingest**: `eagle_rag.ingest.runner` from `/ingest` and MCP `ingest`.
- **Stores**: `eagle_rag.sessions`, `eagle_rag.index`, `eagle_rag.kb`, `eagle_rag.tasks.state`.
- **Frontend**: OpenAPI → `frontend` types via `bun run api:gen`.

## Constraints (from AGENTS.md)

- No auth middleware (intranet only).
- Multi-tenant endpoints accept `kb_name` (fallback `settings.kb_name`).
- `scope_filter` = union (OR) of `kb_names`, `document_ids`, `tags`; persisted on sessions.
- English docstrings and `Field(description=...)` on schemas; user-facing generation may stay zh/en.
- Register new MCP tools in `mcp_server.py` + `TOOL_DEFINITIONS`.
