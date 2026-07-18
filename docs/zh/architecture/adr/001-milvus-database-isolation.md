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

## Evidence (pymilvus 语义，G17/G24)

经 pymilvus 官方文档/示例（`manage_milvus_client/how_to_manage_milvus_client.md`）验证：

- `MilvusClient(uri, db_name=...)` 在构造时绑定客户端到指定 Database 上下文；`db_name` 是构造器参数。
- 同一 URI 上的多个 `MilvusClient` **共享同一底层连接**（同 alias）。每个客户端保留各自的 DB 上下文，故操作经单连接命中不同数据库。
- 对一个客户端调用 `close()` **会使共享该连接的全部客户端失效**（alias ≠ 独立 TCP 连接）。因此 `MilvusClientPool` 禁止 `close()`，按 DB 缓存进程级客户端。
- LlamaIndex `MilvusVectorStore` **不**暴露 `db_name`，故 text store 为 `MilvusClient(uri, db_name=)` 薄封装（与 visual store 对齐），不依赖 `MilvusVectorStore`。
