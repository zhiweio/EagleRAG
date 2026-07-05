# 术语表

Eagle-RAG 文档统一术语。代码标识符与配置键保持英文。

---

## 核心概念

### RAG（Retrieval-Augmented Generation，检索增强生成）

从**检索到的知识**作答，而非仅靠参数化记忆。由 [Lewis 等，2020](https://arxiv.org/abs/2005.11401) 表述：嵌入查询、从向量索引检索 top-\(k\) 块、以这些块条件化 LLM、带引用生成。

**Eagle-RAG：** `EagleRouterQueryEngine.retrieve()` → `EagleMultimodalQueryEngine.custom_query()`。

### Eagle-RAG

本项目：面向 Agent 与 LLM 的、行业无关、多租户多模态 RAG **数据层**。非独立聊天产品 — 向上游 Agent 与 Next.js 前端暴露 REST、SSE 与 MCP。

### 知识库（KB）

以 `kb_name` 标识的租户隔离单元。每个 KB 拥有文档、向量、会话、任务及可选每 KB 设置（如 `pdf_text_page_ratio`）。

**存储：** `knowledge_bases` 表行；向量在共享 Milvus collection 中过滤。

### 多租户（Multi-tenancy）

`kb_name` 贯穿 API、Celery kwargs、Milvus 标量过滤、PostgreSQL 列与去重复合键 `(sha256, kb_name)` 的隔离模型。

**隔离模型：** `kb_name` 贯穿 API、Celery kwargs、Milvus 标量过滤、PostgreSQL 列与去重键 `(sha256, kb_name)`。

**关键张力：** 每条查询路径上 `kb_name` / `scope_filter` 下推的正确性 — 某条代码路径缺过滤是数据泄漏，而非性能问题。

### `kb_name`

知识库标识符，匹配 `^[a-z0-9_]+$`。默认：`default`（`KB_NAME` 环境变量）。创建后不可变。

**代码：** API 省略租户时 `get_settings().kb_name` 回退；Agent 建议每请求显式 `kb_name`。

### 混合搜索（Hybrid search）

向量 ANN 与元数据过滤和/或图扩展的组合。

| 层 | Eagle-RAG 混合机制 |
| --- | --- |
| 向量 + 标量 | Milvus `expr`：`kb_name`、`document_id`、`chunk_type`、`parent_section` |
| 图扩展 | Knowhere 文本节点 `metadata["connect_to"]` — `KnowhereGraphRetriever` |

参考：[Milvus 混合搜索](https://milvus.io/docs/multi-vector-search.md)；[Gao RAG 综述](https://arxiv.org/abs/2312.10997)。

### 多模态（Multimodal）

检索与生成同时使用**文本**与**图像**。文本块在 `eagle_text`（1536 维）；视觉切片在 `eagle_visual`（2048 维）。VLM（Qwen-VL-Max）在同一提示中读取两者。

动机：[MuRAG，Chen 等，2022](https://arxiv.org/abs/2210.02928)。

### 父文档检索（Parent-document retrieval）

长结构化文档的两阶段模式：

1. **阶段 1：** 从 `sections_to_text_nodes()` 召回 `type="section_summary"` 节点（id `sec_{sha1(document_id:path)[:16]}`）。
2. **阶段 2：** 按 `path` 前缀匹配下钻到细粒度块。

避免在章节摘要足够时检索数百叶子块。

### ANN（Approximate Nearest Neighbor，近似最近邻）

高维亚线性相似度搜索。Eagle-RAG 在 `eagle_visual` 使用 Milvus **HNSW**（默认）或 **DiskANN**；文本 collection 经 LlamaIndex `MilvusVectorStore`。

| 索引 | 论文 | 适用场景 |
| --- | --- | --- |
| HNSW | [Malkov & Yashunin，2016](https://arxiv.org/abs/1603.09320) | 内存内、低延迟 |
| DiskANN | [Subramanya 等，2019](https://papers.nips.cc/paper/2019/hash/09853c7ff1cb93b59a86b8e886786b9b-Abstract.html) | 向量超出内存 |

---

## 管线与解析器

### Knowhere

外部文档语义解析器（[Ontos-AI/knowhere](https://github.com/Ontos-AI/knowhere)），HTTP `:5005`。

**集成：** `knowhere-python-sdk` — `Knowhere(api_key, base_url).parse(file=...)` → 经 `/v1/jobs`（创建 → 上传 → 轮询 → 下载）得到内存 `ParseResult`。

**代码：** `eagle_rag/ingest/knowhere_adapter.py` — `parse_with_knowhere_sdk()`、`knowhere_parse` Celery 任务。

**输出：** 类型化块（`text` / `image` / `table`）、`doc_nav.sections` 语义树、`connect_to` 图边。

### PixelRAG

视觉编码器 + 切片库（[StarTrail-org/PixelRAG](https://github.com/StarTrail-org/PixelRAG)）。

**Eagle-RAG 用法：** `pixelrag_render` 切页；`_Qwen3VLVisualEncoder` 嵌入切片。**无** `pixelrag-serve`、**无** FAISS — 向量写入 Milvus。

**代码：** `eagle_rag/ingest/pixelrag_adapter.py` — `pixelrag_build`、`knowhere_visual_chunks`。

### 语义树锚定融合（Semantic-tree anchored fusion）

通过 `eagle_visual` 上四个锚定字段，将 PixelRAG 视觉切片回链到 Knowhere 语义骨架。支持章节范围视觉搜索与 VLM 上下文，无需 SQL JOIN。

见 [多模态融合](architecture/multimodal-fusion.md)。

### 路由矩阵（Routing matrix）

`eagle_rag/ingest/router.py` 中四级优先**摄入**决策链：

1. 文件名前缀（`knowhere:` / `pixelrag:`）
2. `settings.router.mode` 非 `auto` 时
3. PDF 形态探测（`probe_pdf_form`）
4. 扩展名 / 内容类型 / 默认

**不同于** `route_query()` 的查询时路由。

### 摄入（Ingest）

端到端：接受文档 → 去重 → 上传 MinIO → `ingest_router` → `route()` → 解析 → 嵌入 → Milvus upsert → 注册表 `ready`。

**入口：** `POST /ingest` → `eagle_rag/ingest/runner.py`。

### `source_type`

仅元数据标签：`policy` / `financial` / `business` / `bidding` / `tax` / `other`。由 `infer_source_type()` 从文件名/URI 关键词推断。**不影响路由。**

**用途：** Milvus 标量过滤面；QA 范围 UI。

---

## 存储与向量

### Milvus

向量数据库（[milvus-io/milvus](https://github.com/milvus-io/milvus)），单集群托管 `eagle_text` 与 `eagle_visual`。对 `kb_name`、`document_id`、`parent_section` 等建立标量倒排索引，支持单次查询中混合过滤 + ANN。

### `eagle_text`

**1536 维**文本向量（Qwen `text-embedding-v4`）的 Milvus collection。经 `eagle_rag/index/milvus_text_store.py` 中 LlamaIndex `MilvusVectorStore` 管理。

**节点：** Knowhere 块 + `section_summary` 节点；元数据含 `path`、`connect_to`、`kb_name`、`document_id`。

### `eagle_visual`

**2048 维**视觉向量（Qwen3-VL-Embedding-2B）的 Milvus collection。经 `eagle_rag/index/milvus_visual_store.py` 中 `pymilvus.MilvusClient` 管理。

**索引：** HNSW `M=16`、`efConstruction=256`、`metric_type=IP`（L2 归一化 → 余弦）。

### HNSW

分层可导航小世界图索引。`eagle_visual` 默认。查询参数 `ef=64`。

### DiskANN

磁盘驻留 Vamana 图。视觉实体数超内存预算（`kb.visual_entity_limit`）时设 `MILVUS_VISUAL_INDEX_TYPE=diskann`。

### 图扩展（Graph expansion）

文本节点 ANN 命中后，`KnowhereGraphRetriever` 从 `metadata["connect_to"]` 拉取相关节点 — Knowhere 跨块知识图。

### 内积（IP）vs 余弦

L2 归一化向量 \(\|\mathbf{a}\| = \|\mathbf{b}\| = 1\)：\(\mathbf{a} \cdot \mathbf{b} = \cos\theta\)。Eagle-RAG upsert 前归一化视觉嵌入；Milvus 使用 `metric_type=IP`。

---

## 融合锚定字段（`eagle_visual`）

| 字段 | 定义 | Milvus 过滤 |
| --- | --- | --- |
| **`chunk_type`** | `tile`（PixelRAG 页切片）/ `image`（Knowhere 图块）/ `table`（Knowhere 表块） | EQ |
| **`parent_section`** | 最近前序文本块 `path` — 章节归属 | LIKE |
| **`content_summary`** | Knowhere 视觉摘要 — VLM 提示文本上下文 | — |
| **`source_chunk_id`** | Knowhere `chunk_id` — 跨 collection 链到 `eagle_text` | EQ |

**写入方：** `extract_visual_chunks()` 或 `pixelrag_build` 后的 `upsert_visual()` / `upsert_visual_batch()`。

### `section_summary`

`sections_to_text_nodes()` 章节摘要 `TextNode` 的 `type` 元数据。稳定 id：`sec_{sha1(document_id:path)[:16]}`。

---

## 查询与生成

### 路由引擎（Router Engine）

`eagle_rag/router/router_engine.py` 中的 `EagleRouterQueryEngine`。按 `route_query()` 决策组合 `KnowhereGraphRetriever` 与 `PixelRAGVisualRetriever`。

### 范围过滤（Scope filter）

`ScopeSelection{kb_names, document_ids, tags}` — 并集（OR）语义。由 `_resolve_scope_filter()` 解析；标签 → 文档 ID 经 `resolve_tags_to_document_ids()`。持久化于 `sessions.scope_filter`。

### VLM（Vision-Language Model，视觉语言模型）

Qwen-VL-Max（经 `vlm.model` 可配）。在 `EagleMultimodalQueryEngine` 中基于文本块与图像切片生成答案。

### 重排（Rerank）

检索后重排：DashScope `qwen3-rerank`（`qwen3-rerank` 系列）。在 VLM 提示构造前应用。

---

## 运维与集成

### MCP（Model Context Protocol）

[Model Context Protocol](https://modelcontextprotocol.io/) — 在 `/mcp`（HTTP）或 stdio 向 Agent 暴露 `ingest` / `query` / `retrieve_text` / `retrieve_visual`。

**代码：** `eagle_rag/api/mcp_server.py`、`TOOL_DEFINITIONS`。

### SSE（Server-Sent Events）

查询答案（`session` / `step` / `sources` / `token` / `done`）、任务进度与实时日志的流式传输。

### 任务状态机（Task state machine）

`PENDING → RENDERING → EMBEDDING → INDEXING → SUCCESS`（+ `RETRYING` / `FAILED`）。由 `eagle_rag/tasks/state.py` 中 `ALLOWED_TRANSITIONS` 强制。

### 死信队列（Dead letter queue）

重试耗尽消息的 Celery 队列 `dead_letter`。经 `drain_dead_letter()` 检查；经 `replay_dead_letter()` 重放。

**装饰器：** `ingest_router`、`knowhere_parse`、`pixelrag_build` 上的 `@with_retry`。

### 旁路缓存（Sidecar cache）

`{storage_path}.parsed.json` 缓存附件解析结果。重复查询避免重解析。配置：`attachments.parse.cache_enabled`。

### 懒初始化（Lazy initialization）

导入时不连接服务。`get_settings()`、Milvus 客户端、`_Qwen3VLVisualEncoder` 首次使用时构造 — `@lru_cache` 或模块级单例。

### 优雅降级（Graceful degradation）

外部失败降级**功能**而非进程。例：检索器异常 → `[]`；标签解析失败 → 忽略标签；视觉派发失败 → 文本索引仍成功。

### `unknown` vs `down`（健康）

`/health` 探测状态：`unknown` = 未配置/未探测；`down` = 已探测且失败。视觉提供方非 `pixelrag` 时 PixelRAG 报 `unknown`。

---

## Celery 队列

| 队列 | 并发 | 任务 |
| --- | --- | --- |
| `router_queue` | 4 | `ingest_router` |
| `knowhere_queue` | 8 | `knowhere_parse` |
| `pixelrag_queue` | 1 | `pixelrag_build`、`knowhere_visual_chunks` |

`pixelrag_queue` 并发**必须保持低** — Chromium 渲染易 OOM。

---

## 参考文献

- [Lewis 等，2020](https://arxiv.org/abs/2005.11401)
- [Gao 等，2023](https://arxiv.org/abs/2312.10997)
- [MuRAG](https://arxiv.org/abs/2210.02928)
- [HNSW](https://arxiv.org/abs/1603.09320)
- [Milvus 文档](https://milvus.io/docs)
- [LlamaIndex 术语](https://docs.llamaindex.ai/)
- [Knowhere](https://github.com/Ontos-AI/knowhere)
- [PixelRAG](https://github.com/StarTrail-org/PixelRAG)
- [MCP 规范](https://modelcontextprotocol.io/)
