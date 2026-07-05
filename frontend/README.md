# Eagle-RAG Frontend

Next.js 16 (App Router) web UI for multimodal Q&A, document ingestion, knowledge-base management, and service health monitoring.

## Stack

| Layer | Choice |
| --- | --- |
| Framework | Next.js 16, React 19, TypeScript 5 |
| UI | HeroUI v3, Tailwind CSS v4 |
| State | TanStack Query (server), Zustand (client prefs/scope) |
| i18n | `next-intl` (en / zh), light theme only |
| API | OpenAPI-generated client (`lib/api/generated/`) + hand-written SSE helpers |
| Tooling | Bun, Biome |

## Layout

```
frontend/
├── app/[locale]/          # Locale-prefixed routes (QA, ingest, KB, health)
├── components/            # Feature components (qa/, ingest/, health/, …)
├── lib/
│   ├── api/               # Generated SDK + client wrappers
│   ├── hooks/             # TanStack Query hooks
│   ├── stores/            # Zustand stores (scope, prefs)
│   └── types/             # Shared TypeScript types
└── messages/              # i18n fragments (en / zh)
```

## Development

```bash
bun install
bun run dev          # http://localhost:3000
bun run lint
bun run format
bun run api:gen      # Regenerate OpenAPI client from backend /openapi.json
```

Set `NEXT_PUBLIC_API_BASE_URL` (default `http://localhost:8000`) to point at the FastAPI backend.

## Constraints

- **Light-only** — do not add dark theme.
- **Do not edit** `lib/api/generated/` by hand; run `bun run api:gen`.
- User-facing strings belong in `messages/` (zh/en), not hardcoded in components.

## Documentation

- [Frontend docs](../docs/en/frontend/index.md)
- [QA module](../docs/en/frontend/qa-module.md)
