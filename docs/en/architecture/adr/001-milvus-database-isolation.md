# ADR-001: Milvus Database Isolation

**Status:** Accepted

## Context

Multi-industry deployments need physical isolation between domains without cross-tenant scalar filter bugs.

## Decision

- `plugin_namespace` maps to a Milvus **Database** (`core` → `default`, `lakehouse-bi` → `lakehouse_bi`).
- Each DB has base collections `eagle_text` + `eagle_visual`; plugins add specialized collections.
- `kb_name` remains a scalar filter within a DB.

## Consequences

- No `plugin_namespace` Milvus scalar field.
- `MilvusClientPool` binds `db_name` at client construction; no `close()` on pooled clients.
