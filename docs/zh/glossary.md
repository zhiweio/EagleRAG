# 术语表

Eagle-RAG 文档中使用的统一术语。代码标识符与配置键保持英文。

---

## 核心概念

### RAG（检索增强生成）

从**检索到的知识**而非仅靠参数化记忆来回答。[Lewis 等，2020](https://arxiv.org/abs/2005.11401) 的表述：嵌入查询，从向量索引中检索 top-\(k\) 块，以这些块为条件让 LLM 生成并附引用。

**Eagle-RAG：** `EagleRouterQueryEngine.retrieve()` → `EagleMultimodalQueryEngine.custom_query()`。

### Eagle-RAG

本项目：面向 Agent 与 LLM 的、行业无关、多租户的多模态 RAG **数据层**。不是独立聊天产品 — 通过 REST、SSE 和 MCP 暴露给上游 Agent 与 Next.js 前端。

### 知识库（KB）

在单个已部署域（`plugin_namespace`）**内部**由 `kb_name` 标识的知识库单元。每个 KB 拥有文档、向量、会话、任务及可选 per-KB 设置（如 `pdf_text_page_ratio`）。

**存储：** `knowledge_bases` 中按命名空间划分的行；向量在同一 Milvus Database 的基础集合（`eagle_text`、`eagle_visual`）及域专用集合上通过 `kb_name` 标量过滤。

### 多租户

Eagle-RAG 在**两个轴**上隔离数据 — 在 API 或 UI 文案中勿混淆：

| 轴 | 标识符 | 机制 |
| --- | --- | --- |
| **域** | `plugin_namespace` | 每域一个 Milvus **Database** + PostgreSQL 仓库过滤（部署时；`settings.plugins.default_namespace` 或 `EAGLE_RAG_PROFILE`） |
| **知识库** | `kb_name` | 该 Database **内部**的标量过滤（请求时） |

同一域 Database 内，多个 KB 共享基础集合并由 `kb_name` 分隔。跨域检索使用**多个实例**，而非 Core 在 Milvus Database 间扇出。

**传播：** `plugin_namespace` 来自实例配置；`kb_name` 贯穿 API、Celery kwargs、Milvus 标量过滤、PostgreSQL 仓库及去重键 `(sha256, kb_name, plugin_namespace)`。

**关键张力：** `plugin_namespace` 绑定与每条查询路径上 `kb_name` / `scope_filter` 下推的正确性 — 任一代码路径缺少过滤是**数据泄漏**，而非性能问题。

参见 [多租户](architecture/multi-tenancy.md) 与 [插件术语表](architecture/glossary-plugin.md)。

### `plugin_namespace`

部署时域绑定（= Milvus Database 名）。由 `settings.plugins.default_namespace` 或 `EAGLE_RAG_PROFILE` 固定；**非**运行时 UI 切换。请求上显式 `plugin_namespace` 与默认不一致时返回 **403**（除非 `plugins.allow_namespace_override`，仅测试用）。

### `kb_name`

知识库标识符，匹配 `^[a-z0-9_]+$`。默认：`default`（`KB_NAME` 环境变量）。创建后不可变。

**代码：** API 省略租户时回退 `get_settings().kb_name`；建议 Agent 每请求显式传 `kb_name`。

### 混合检索

向量 ANN 与元数据过滤和/或图扩展相结合。

| 层 | Eagle-RAG 混合机制 |
| --- | --- |
| 向量 + 标量 | Milvus `expr` 作用于 `kb_name`、`document_id`、`chunk_type`、`parent_section` |
| 图扩展 | Knowhere 文本节点上的 `metadata["connect_to"]` — `KnowhereGraphRetriever` |

参考：[Milvus 混合检索](https://milvus.io/docs/multi-vector-search.md)；[Gao RAG 综述](https://arxiv.org/abs/2312.10997)。

### 多模态

检索与生成同时使用**文本**与**图像**模态。文本块在 `eagle_text`（1536 维）；视觉瓦片在 `eagle_visual`（2048 维）。VLM（Qwen-VL-Max）在同一 prompt 中读取两者。

动机：[MuRAG，Chen 等，2022](https://arxiv.org/abs/2210.02928)。

### 父文档检索

长结构化文档的两阶段模式：

1. **阶段 1：** 从 `sections_to_text_nodes()` 召回 `type="section_summary"` 节点（id `sec_{sha1(document_id:path)[:16]}`）。
2. **阶段 2：** 按 `path` 前缀匹配下钻到细粒度块。

避免在章节摘要已足够时检索数百叶子块。

### ANN（近似最近邻）

高维次线性相似度搜索。Eagle-RAG 在 `eagle_visual` 上使用 Milvus **HNSW**（默认）或 **DiskANN**；文本集合经 LlamaIndex `MilvusVectorStore`。

| 索引 | 论文 | 适用场景 |
| --- | --- | --- |
| HNSW | [Malkov & Yashunin，2016](https://arxiv.org/abs/1603.09320) | 内存内、低延迟 |
| DiskANN | [Subramanya 等，2019](https://papers.nips.cc/paper/2019/hash/09853c7ff1cb93b59a86b8e886786b9b-Abstract.html) | 向量超出内存 |

---

## 流水线与解析器

### Knowhere

外部文档语义解析器（[Ontos-AI/knowhere](https://github.com/Ontos-AI/knowhere)），HTTP `:5005`。

**集成：** `knowhere-python-sdk` — `Knowhere(api_key, base_url).parse(file=...)` → 经 `/v1/jobs`（创建 → 上传 → 轮询 → 下载）得到内存中 `ParseResult`。

**代码：** `eagle_rag/ingest/knowhere_adapter.py` — `parse_with_knowhere_sdk()`、`knowhere_parse` Celery 任务。

**输出：** 类型化块（`text` / `image` / `table`）、`doc_nav.sections` 语义树、`connect_to` 图边。

### PixelRAG

视觉编码器 + 切片库（[StarTrail-org/PixelRAG](https://github.com/StarTrail-org/PixelRAG)）。

**Eagle-RAG 用法：** `pixelrag_render` 切页；`_Qwen3VLVisualEncoder` 嵌入瓦片。**无** `pixelrag-serve`、**无** FAISS — 向量写入 Milvus。

**代码：** `eagle_rag/ingest/pixelrag_adapter.py` — `pixelrag_build`、`knowhere_visual_chunks`。

### 语义树锚定融合

通过 `eagle_visual` 上四个锚定字段，将 PixelRAG 视觉瓦片链回 Knowhere 语义骨架。支持按章节范围的视觉搜索与 VLM 上下文，无需 SQL JOIN。

参见 [多模态融合](architecture/multimodal-fusion.md)。

### 路由矩阵

`eagle_rag/ingest/router.py` 中的四级**入库**决策链：

1. 文件名前缀（`knowhere:` / `pixelrag:`）
2. `settings.router.mode` 非 `auto` 时
3. PDF 形态探测（`probe_pdf_form`）
4. 扩展名 / content-type / 默认

**不同于** `route_query()` 中的查询时路由。

### Ingest（入库）

端到端：接受文档 → 去重 → 上传 MinIO → `ingest_router` → `route()` → 解析 → 嵌入 → Milvus upsert → 注册表 `ready`。

**入口：** `POST /ingest` → `eagle_rag/ingest/runner.py`。

### `source_type`

自由格式元数据标签（如 `policy` / `financial` / `other`，或部署专用标签）。由 `infer_source_type()` 推断：优先 `source_type_hint`，否则匹配 `settings.ingest.source_type.rules`（**Core 默认 `rules: []`** — 无金融/税务硬编码）。**不影响路由。**

**用途：** Milvus 标量过滤面；QA 范围 UI。

---

## 存储与向量

### Milvus

向量数据库（[milvus-io/milvus](https://github.com/milvus-io/milvus)），单集群。每个 **`plugin_namespace`** 映射一个 Milvus **Database**（`MilvusClientPool`，`db_name=` — 无每请求 DB 切换）。每个域 Database 有基础集合 `eagle_text`、`eagle_visual`；域插件可在同一 Database 增加专用集合（如 `eagle_text_biomed`）。**KB 隔离**是该 Database 内的 `kb_name` 标量过滤，而非每 KB 独立集合。`kb_name`、`document_id`、`parent_section` 等标量倒排索引支持单次查询中混合过滤 + ANN。

### `eagle_text`

**1536 维**文本向量（Qwen `text-embedding-v4`）的 Milvus 集合。由 `eagle_rag/index/milvus_text_store.py` 中 LlamaIndex `MilvusVectorStore` 管理。

**节点：** Knowhere 块 + `section_summary` 节点；元数据含 `path`、`connect_to`、`kb_name`、`document_id`。

### `eagle_visual`

**2048 维**视觉向量（Qwen3-VL-Embedding-2B）的 Milvus 集合。由 `eagle_rag/index/milvus_visual_store.py` 中 `pymilvus.MilvusClient` 管理。

**索引：** HNSW `M=16`，`efConstruction=256`，`metric_type=IP`（L2 归一化 → 余弦）。

### HNSW

分层可导航小世界图索引。`eagle_visual` 默认。查询时搜索参数 `ef=64`。

### DiskANN

磁盘驻留 Vamana 图。视觉实体数超过内存预算（`kb.visual_entity_limit`）时设置 `MILVUS_VISUAL_INDEX_TYPE=diskann`。

### 图扩展

对每个 ANN 召回的文本节点，`KnowhereGraphRetriever` 从 `metadata["connect_to"]` 拉取相关节点 — Knowhere 跨块知识图。

### 内积（IP）与余弦

对 L2 归一化向量 \(\|\mathbf{a}\| = \|\mathbf{b}\| = 1\)：\(\mathbf{a} \cdot \mathbf{b} = \cos\theta\)。Eagle-RAG 在 upsert 前归一化视觉嵌入；Milvus 使用 `metric_type=IP`。

---

## 融合锚定字段（`eagle_visual`）

| 字段 | 定义 | Milvus 过滤 |
| --- | --- | --- |
| **`chunk_type`** | `tile`（PixelRAG 页切片）/ `image`（Knowhere 图像块）/ `table`（Knowhere 表格块） | EQ |
| **`parent_section`** | 最近前序文本块的 `path` — 章节归属 | LIKE |
| **`content_summary`** | Knowhere 视觉摘要 — VLM prompt 文本上下文 | — |
| **`source_chunk_id`** | Knowhere `chunk_id` — 跨集合链到 `eagle_text` | EQ |

**写入方：** `extract_visual_chunks()` 或 `pixelrag_build` 之后的 `upsert_visual()` / `upsert_visual_batch()`。

### `section_summary`

来自 `sections_to_text_nodes()` 的章节摘要 `TextNode` 的 `type` 元数据。稳定 id：`sec_{sha1(document_id:path)[:16]}`。

---

## 查询与生成

### Router Engine（路由引擎）

`eagle_rag/router/router_engine.py` 中的 `EagleRouterQueryEngine`。按 `route_query()` 决策组合 `KnowhereGraphRetriever` 与 `PixelRAGVisualRetriever`。

### Scope filter（范围过滤）

`ScopeSelection{kb_names, document_ids, tags}` — 并集（OR）语义。由 `_resolve_scope_filter()` 解析；标签经 `resolve_tags_to_document_ids()` 转为文档 ID。持久化在 `sessions.scope_filter`。

### VLM（视觉语言模型）

Qwen-VL-Max（可通过 `vlm.model` 配置）。在 `EagleMultimodalQueryEngine` 上对文本块与图像瓦片生成答案。

### Rerank（重排）

经 DashScope `qwen3-rerank`（`qwen3-rerank` 系列）的检索后重排。在 VLM prompt 构建前应用。

---

## 运维与集成

### MCP（Model Context Protocol）

[Model Context Protocol](https://modelcontextprotocol.io/) — 在 `/mcp`（HTTP）或 stdio 向 Agent 暴露 **`core_ingest`**、**`core_query`**、**`core_retrieve_text`**、**`core_retrieve_visual`**。域插件注册 `{namespace}_{name}` 工具；每实例仅暴露 `core_*` 加 `default_namespace` 工具（G3）。工具**仅 RAG**（检索 / 组装上下文 — 无副作用命名）。

**代码：** `eagle_rag/api/mcp_server.py`、`eagle_rag/plugins/mcp_registry.py`、`TOOL_DEFINITIONS`。

### SSE（Server-Sent Events）

查询答案（`session` / `step` / `sources` / `token` / `done`）、任务进度与实时日志的流式传输。

### 任务状态机

`PENDING → RENDERING → EMBEDDING → INDEXING → SUCCESS`（及 `RETRYING` / `FAILED`）。由 `eagle_rag/tasks/state.py` 中 `ALLOWED_TRANSITIONS` 强制。

### 死信队列

Celery 队列 `dead_letter` 存放重试耗尽的消息。经 `drain_dead_letter()` 检查；经 `replay_dead_letter()` 重放。

**装饰器：** `ingest_router`、`knowhere_parse`、`pixelrag_build` 上的 `@with_retry`。

### Sidecar 缓存

`{storage_path}.parsed.json` 缓存附件解析结果。重复查询避免重解析。配置：`attachments.parse.cache_enabled`。

### 惰性初始化

导入时不连接任何服务。`get_settings()`、Milvus 客户端、`_Qwen3VLVisualEncoder` 在首次使用时构造 — `@lru_cache` 或模块级单例。

### 优雅降级

外部故障降级**功能**，而非进程。示例：检索器异常 → `[]`；标签解析失败 → 忽略标签；视觉分发失败 → 文本索引仍成功。

### `unknown` 与 `down`（健康）

`/health` 探测状态：`unknown` = 未配置 / 未探测；`down` = 已探测且失败。视觉 provider 非 `pixelrag` 时 PixelRAG 报告 `unknown`。

### 微内核插件 / `plugins.options`

进程内、仓库内插件（`settings.plugins.enabled`）。垂直旋钮在 `plugins.options.<namespace>`，经 `plugin_options()` 读取。参见 [插件术语表](architecture/glossary-plugin.md)、[ADR-008](architecture/adr/008-rag-only-plugin-platform.md)。

### Hot-path hooks（热路径钩子）

`PARSE` / `CHUNK` / `QUERY_ASSEMBLE` 必须在 ingest/query 热路径运行（`hotpath_hooks.py`）— 仅订阅不够。

### RAG-only MCP

MCP 工具仅检索并组装上下文。像 `execute_sql` 的副作用命名会被拒绝（`assert_rag_only_tool_name`）。Core 工具使用 `core_*` 前缀。

---

## Celery 队列

| 队列 | 并发 | 任务 |
| --- | --- | --- |
| `router_queue` | 4 | `ingest_router` |
| `knowhere_queue` | 8 | `knowhere_parse` |
| `pixelrag_queue` | 1 | `pixelrag_build`、`knowhere_visual_chunks` |

`pixelrag_queue` 并发**必须保持较低** — Chromium 渲染易 OOM。

---

## 参考文献

- [Lewis 等，2020](https://arxiv.org/abs/2005.11401)
- [Gao 等，2023](https://arxiv.org/abs/2312.10997)
- [MuRAG](https://arxiv.org/abs/2210.02928)
- [HNSW](https://arxiv.org/abs/1603.09320)
- [Milvus 文档](https://milvus.io/docs)
- [LlamaIndex 术语表](https://docs.llamaindex.ai/)
- [Knowhere](https://github.com/Ontos-AI/knowhere)
- [PixelRAG](https://github.com/StarTrail-org/PixelRAG)
- [MCP 规范](https://modelcontextprotocol.io/)
