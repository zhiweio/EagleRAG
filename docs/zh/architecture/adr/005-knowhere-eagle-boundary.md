# ADR-005: Knowhere vs Eagle Query Boundary

**Status:** Accepted

## Decision

- Eagle 仅将 Knowhere 用于 **parse** 与 `doc_nav`。
- 查询热路径：Eagle Milvus 多 collection + RRF — **不**调用 Knowhere `RetrievalAgent` / `WorkflowOrchestrator`。
- 父文档检索：`KnowhereGraphRetriever` 在 `eagle_text` 上两阶段召回。
- **结构解析仅属 Knowhere**：任意行业文档的章节树、目录、typed chunks、层级 `path` 均须保留自 Knowhere `ParseResult`。
- **领域 `CHUNK` / `PARSE` hook 只做 enrich**（元数据、软标签、typed 标注）。不得丢弃或改写 Knowhere 骨架字段（`path`、块正文、`doc_nav`、`section_summary` 节点）。
- 若领域需要不同的切分 / 层级边界：在 Knowhere parse（上游 / parse-sdk）二次开发，Eagle 只消费新的 `ParseResult` — **禁止**在 Eagle 手写从零 chunker。
