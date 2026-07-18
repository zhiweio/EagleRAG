# ADR-001: Milvus Database Isolation

**Status:** Accepted

## Context

Multi-industry deployments need physical isolation between domains without cross-tenant scalar filter bugs.

## Decision

- `plugin_namespace` maps to a Milvus **Database** (`core` -> `default`, `lakehouse-bi` -> `lakehouse_bi`).
- Each DB has base collections `eagle_text` + `eagle_visual`; plugins add specialized collections.
- `kb_name` remains a scalar filter within a DB.

## Consequences

- No `plugin_namespace` Milvus scalar field.
- `MilvusClientPool` binds `db_name` at client construction; no `close()` on pooled clients.

## Evidence (pymilvus semantics, G17/G24)

Verified against pymilvus official docs/examples (`manage_milvus_client/how_to_manage_milvus_client.md`):

- `MilvusClient(uri, db_name=...)` binds the client to a specific Database context. The
  `db_name` parameter is part of the constructor signature.
- Multiple `MilvusClient` instances on the **same URI share the same underlying connection**
  (same alias). Each client keeps its own DB context, so operations hit different databases
  over a single connection.
- `close()` on one client **invalidates all clients sharing that connection** (alias ≠
  independent TCP). This is why `MilvusClientPool` forbids `close()` and pools per-DB
  clients for the process lifetime.
- LlamaIndex `MilvusVectorStore` does **not** expose `db_name`, so the text store is a thin
  `MilvusClient(uri, db_name=)` wrapper (aligned with the visual store), not
  `MilvusVectorStore`.
