# ADR-006: Ingest–Query Routing Contract

**Status:** Accepted

## Decision

- Ingest writes `documents.extra.collections_used` and `knowledge_bases.collections_used` on success only (G30).
- Query `scope-aware` union forces specialized collection plans when scope KBs/documents/tags catalog includes them (G21/G23/G29).
- Tags resolve via `resolve_tags_to_document_ids(plugin_namespace, tags)` then document catalog union.
