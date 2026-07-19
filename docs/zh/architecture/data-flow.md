# 数据流

两条端到端流定义 Eagle-RAG：**摄入**（文档 → 向量）与**查询**（问题 → 带引用答案）。二者横跨 API、Celery、适配器、插件微内核、Milvus 与 PostgreSQL。本文追踪实际函数名与控制流。

完整微内核设计见 [插件架构](plugin-architecture.md)。

---

## 理论与基础

### 索引时 vs 查询时

[RAG 综述（Gao 等，2023）](https://arxiv.org/abs/2312.10997) 区分：

| 阶段 | 成本特征 | Eagle-RAG 特点 |
| --- | --- | --- |
| **索引** | 高延迟、批/异步 | Celery 三队列管线；每文档数分钟 |
| **查询** | 低延迟、交互 | 亚秒级 ANN + 流式 VLM 生成 |

[Lewis 等，2020](https://arxiv.org/abs/2005.11401) 在查询时检索 — 索引新鲜度取决于摄入是否成功完成。

### 双索引数据模型

每个领域 Milvus Database 始终包含两个**基础 collection**：

| Collection | 内容 | 嵌入 |
| --- | --- | --- |
| `eagle_text` | Knowhere 语义块 | Qwen `text-embedding-v4`（1536 维） |
| `eagle_visual` | PixelRAG 切片 / 图片 / 表格 | Qwen3-VL-Embedding-2B（2048 维） |

文本与视觉嵌入存于独立 collection，因为使用不同模型、维度与索引调优（HNSW 参数、规模化 DiskANN）。

**领域插件**可在**同一** Milvus Database 中新增专用 collection（如 `eagle_text_biomed`、`eagle_chemical`）。摄入记录文档使用了哪些 collection；查询可跨多个 collection 扇出检索。

**查询时融合**不再局限于文本 + 视觉双检索器。`RetrieverOrchestrator` 按 `CollectionQueryPlan` 执行 ANN、可选 per-plan `RERANK`，再用 RRF 合并（`eagle_rag/router/rerank_fusion.py`）— 绝不使用跨嵌入空间的原始分数。见 [ADR-004](adr/004-multi-encoder-rrf-fusion.md)。

`EagleRouterQueryEngine` 仍是 API 入口，检索委托给编排器，再进入 `EagleMultimodalQueryEngine` 生成。

---

## 摄入流

**目标：** 将上传文件或 URL 转为可搜索向量，并保留引用溯源。

```mermaid
sequenceDiagram
    autonumber
    participant Client
    participant API as FastAPI POST /ingest
    participant Runner as ingest.runner
    participant Dedup as storage.dedup
    participant MinIO
    participant PG as PostgreSQL
    participant Celery as router_queue
    participant IR as ingest_router
    participant Pipe as knowhere_parse / pixelrag_build
    participant HotPath as hotpath_hooks
    participant Bus as HookBus
    participant Orch as IngestOrchestrator
    participant Milvus

    Client->>API: multipart file + kb_name
    API->>Runner: ingest(...)
    Runner->>Runner: kb_exists_sync(kb_name)
    Runner->>Dedup: sha256 + check_duplicate
    alt duplicate (sha256, kb_name)
        Runner-->>API: dedup_hit 200
    else new document
        Runner->>MinIO: upload_bytes(object_key)
        Runner->>PG: register_document_sync
        Note over PG: plugin_namespace via repositories
        Runner->>Celery: send_task ingest_router
        Celery->>IR: ingest_router(job_id, ...)
        IR->>IR: route() + infer_source_type()
        IR->>Pipe: send_task per pipeline
        Pipe->>Pipe: Knowhere / PixelRAG parse
        Pipe->>HotPath: apply_parse_hook (PARSE)
        HotPath->>Bus: PARSE transform
        Pipe->>HotPath: apply_chunk_hook (CHUNK)
        HotPath->>Bus: CHUNK transform
        Pipe->>Bus: INGEST_VISUAL_EXTRACT
        loop each text/visual chunk
            Orch->>Bus: CLASSIFY_CHUNK / CLASSIFY_VISUAL
            Orch->>Bus: EMBED_TEXT / EMBED_VISUAL
            Orch->>Bus: UPSERT_VECTORS
            Bus->>Milvus: write collection
        end
        Pipe->>PG: update_status ready, chunk_count
        Pipe->>PG: collections_used catalog
        Pipe->>PG: task_audit SUCCESS
    end
```

### 逐步实现

| 步骤 | 函数 / 模块 | 说明 |
| --- | --- | --- |
| 1. API 接受 | `eagle_rag/api/ingest.py` | 校验 `kb_name`；返回 `job_id` |
| 2. Runner 编排 | `eagle_rag/ingest/runner.py` `ingest()` | SHA-256 哈希；去重门 |
| 3. 去重 | `eagle_rag/storage/dedup.py` | PK `(sha256, kb_name)`，作用域为 `plugin_namespace` |
| 4. 对象存储 | `eagle_rag/storage/minio_client.py` | `{document_id}/{filename}`；键含 namespace |
| 5. 注册表 | `register_document_sync()` | 状态 `pending` → `processing`；仓储注入 `plugin_namespace` |
| 6. 路由任务 | `eagle_rag/ingest/router.py` 中 `ingest_router` | `@with_retry`，`router_queue` |
| 7. 路由 | `route(filename, local_path, kb_name, ...)` | 返回 `["knowhere"]` 或 `["pixelrag"]` 或两者；插件可通过 `INGEST_ROUTE_SELECTORS` 扩展 |
| 8. 派发 | `app.send_task(knowhere_parse \| pixelrag_build)` | 按管线队列 |
| 9. 插件钩子 | `eagle_rag/plugins/hotpath_hooks.py` | `PARSE` → `CHUNK` → `INGEST_VISUAL_EXTRACT` |
| 10. 分类 + 索引 | `IngestOrchestrator` | 每块 `CLASSIFY_*` → `EMBED_*` → `UPSERT_VECTORS` |
| 11. Collection 目录 | `ingest_catalog.py` / `ingest_tracker.py` | 全部成功时：`documents.extra["collections_used"]` + `knowledge_bases.collections_used` |
| 12. 去重注册 | `dedup.register()` | **解析成功后** — 失败任务无去重行 |

固定钩子顺序（G26）：`PARSE` → `CHUNK` → `INGEST_VISUAL_EXTRACT` → `CLASSIFY_*` → `IngestOrchestrator`（`EMBED_*` → `UPSERT_VECTORS`）。失败或部分摄入不更新 collection 目录。见 [ADR-006](adr/006-ingest-query-routing-contract.md)。

### URL 来源

URL 摄入：客户端先调 `POST /ingest/validate/url`（可达性 + 按类型的 PDF 限制，见 `url_prefetch`），再 `POST /ingest` 仅做格式/SSRF 后入队。正文在管线任务内懒取；索引成功后应用去重。

### Knowhere 路径（`knowhere_parse`）

```mermaid
flowchart TD
    A[knowhere_parse] --> B[Resolve local file]
    B --> C[parse_with_knowhere_sdk]
    C --> HP1[apply_parse_hook PARSE]
    HP1 --> HP2[apply_chunk_hook CHUNK]
    HP2 --> D[chunks_to_text_nodes]
    HP2 --> E[sections_to_text_nodes]
    D --> IO[IngestOrchestrator]
    E --> IO
    IO --> F[CLASSIFY_* → EMBED_* → UPSERT_VECTORS]
    F --> G1[eagle_text]
    F --> G2[specialized collections]
    C --> G[extract_visual_chunks]
    G --> H[INGEST_VISUAL_EXTRACT]
    H --> I[dispatch_visual_chunks]
    I --> J[knowhere_visual_chunks on pixelrag_queue]
    J --> K[IngestOrchestrator → eagle_visual]
    C --> L[build_doc_nav_tree → documents.extra]
    F --> M[aggregate_keyword_counts → document_keywords]
    M --> N[update_status ready + collections_used]
```

**状态转移**（`eagle_rag/tasks/state.py`）：

`PENDING` → `RENDERING`（Knowhere 解析）→ `EMBEDDING` → `INDEXING` → `SUCCESS`

**非阻塞副作用**（失败记日志，主任务继续）：

- 标签目录写入（`upsert_document_keywords`）
- 视觉派发（`dispatch_visual_chunks`）
- `doc_nav` 持久化（`update_extra`）

### PixelRAG 路径（`pixelrag_build`）

扫描 PDF、图片、URL、HTML：

1. 渲染页为切片（`pixelrag_render`）— 设置：`tile_height`、`viewport_width`、`pdf_dpi`
2. `INGEST_VISUAL_EXTRACT` → `IngestOrchestrator` 分类并嵌入切片（`get_visual_encoder()`）— 2048 维，L2 归一化
3. `UPSERT_VECTORS` → `eagle_visual` — `chunk_type=tile`
4. `update_status(ready)`；`collections_used` 目录；成功时 `dedup.register()`

队列：`pixelrag_queue`，并发 **1**。

---

## 查询流

**目标：** 路由问题，跨一个或多个 collection 检索相关块，重排，生成有依据答案与来源。

```mermaid
sequenceDiagram
    autonumber
    participant Client
    participant API as POST /query
    participant Engine as EagleRouterQueryEngine
    participant HotPath as hotpath_hooks
    participant Bus as HookBus
    participant Class as CLASSIFY_QUERY
    participant Scope as scope_routing
    participant Orch as RetrieverOrchestrator
    participant RRF as merge_rrf
    participant Gen as EagleMultimodalQueryEngine
    participant Milvus
    participant VLM as Qwen-VL-Max

    Client->>API: query, mode, kb_name, scope_filter
    API->>Engine: query(...)
    Engine->>HotPath: apply_query_assemble
    HotPath->>Bus: QUERY_ASSEMBLE all
    Engine->>Class: route query
    Class->>Scope: union specialized collections from catalog
    Class-->>Engine: QueryRouteDecision plans
    Note over Class: Core 默认：仅 eagle_text + eagle_visual（G4）
    loop each CollectionQueryPlan
        Engine->>Orch: ANN per plan
        Orch->>Milvus: collection-specific search
        Orch->>Bus: RERANK first
    end
    Orch->>RRF: merge_rrf + dedupe
    RRF-->>Engine: NodeWithScore list
    Engine->>Gen: custom_query(nodes, route_info)
    Gen->>Gen: rerank (qwen3-rerank)
    Gen->>VLM: multimodal prompt
    VLM-->>Gen: answer tokens
    Gen-->>Client: answer + sources + route
```

### `EagleRouterQueryEngine` 控制流

```python
# eagle_rag/router/router_engine.py — 简化
def query(self, query, mode=None, kb_name=None, scope_filter=None, attachments=None):
    attach_nodes, image_docs, attach_step, has_doc = self._prepare_attachments(attachments)
    nodes, decision = self.retrieve(query, mode=mode, kb_name=kb_name,
                                    scope_filter=scope_filter, has_doc_attachments=has_doc)
    nodes = attach_nodes + nodes  # 附件前置
    return EagleMultimodalQueryEngine().custom_query(query, nodes=nodes, route_info=decision.to_dict(), ...)
```

**`retrieve()` 内部：**

1. `apply_query_assemble()` — `QUERY_ASSEMBLE` 钩子在 ANN 前扩展查询 / 实体提示（`plugins.query_assemble_enabled`）
2. `CLASSIFY_QUERY` → `QueryRouteDecision`，含一个或多个 `CollectionQueryPlan`
3. `_resolve_scope_filter(scope_filter)` → `(kb_names, document_ids, active)`；范围感知目录在 scoped 文档/KB/标签使用过专用 collection 时可**强制**加入（[ADR-006](adr/006-ingest-query-routing-contract.md)）
4. `RetrieverOrchestrator.retrieve()` — 按 plan ANN（尽力而为；失败 plan 跳过并审计）
5. 可选 per-plan `RERANK` 钩子，再 `merge_rrf()` — 按 `source_chunk_id` 或 `(document_id, path)` 去重

**Core 默认路由（G4）：** `CLASSIFY_QUERY` 仅规划 `eagle_text`（混合 / 图片时加 `eagle_visual`）。Core **从不**自动查询专用 collection；领域分类器或范围感知目录并集可添加。

### 遗留检索器细节（Core plan）

当 plan 指向基础 collection 时，行为与原始双索引路径一致：

**`eagle_text`（经 `KnowhereGraphRetriever` 或编排器 plan）：**

1. 经 Qwen `text-embedding-v4`（或 plan 指定领域编码器）嵌入查询
2. 在 `eagle_text` 上 Milvus ANN，带 `kb_name` / `document_id` 元数据过滤
3. 对每个命中扩展 `metadata["connect_to"]` — Knowhere 知识图
4. 可选父文档：提升 `type="section_summary"` 召回

**`eagle_visual`（经 `PixelRAGVisualRetriever` 或编排器 plan）：**

1. 经 `get_visual_encoder()` 嵌入查询（与切片同 provider/空间）
2. `milvus_visual_store.py` 中 `search_visual()` — IP 搜索，`ef=64`
3. 标量 expr：`kb_name`、`document_id`、可选 `chunk_type`、`parent_section`

### 生成（`EagleMultimodalQueryEngine`）

1. 拆分文本 `TextNode` 与视觉 `ImageNode`
2. 重排文本候选（`settings.rerank.text`）
3. 构造 VLM 提示：文本块 + `content_summary` + 图像路径
4. 流式或阻塞调用 `settings.vlm`（Qwen-VL-Max）
5. 经 `_text_source()` / `_image_source()` 映射来源 — 按 `router.source_content_max_chars` 截断

---

## 流式（`POST /query/stream`）

SSE 事件顺序：

```
session → step* → sources → token* → done
```

实现（`eagle_rag/api/query.py`）：

- 守护线程将同步 `engine.query_stream()` 生成器桥接到异步 SSE
- 事件：`session`、`step`（route、recall、attach_parse）、`sources`、`token`、`done`
- `done` 时将助手消息持久化到 `sessions` / `messages` 表

### 仅检索

`POST /search` 与 `/search/stream` 调用 `engine.search()` / `search_stream()` — **无 VLM**。返回 `sources{text, image}` + `route` + `steps`。

---

## 附件流

查询时附件（`POST /attachments`）：

```mermaid
flowchart LR
    UP[POST /attachments] --> STORE[local storage_path]
    Q[POST /query + attachment_ids] --> PARSE[parse_attachments]
    PARSE --> CACHE{.parsed.json?}
    CACHE -->|hit| NODES[TextNode list]
    CACHE -->|miss| ROUTE[route + parse]
    ROUTE --> NODES
    NODES --> PREPEND[prepend to retrieval]
    PREPEND --> GEN[generation]
```

- **不写 Milvus** — 仅临时上下文
- 旁路缓存：`attachments.parse.cache_enabled=true` 时 `{storage_path}.parsed.json`
- TTL：`attachments.ttl_hours`（默认 24）
- 文档附件设 `has_doc_attachments=True` → 路由偏向 `hybrid`

代码：`eagle_rag/attachments/parser.py`。

---

## MCP 数据流

单一 FastMCP 应用位于 `/mcp`（默认 HTTP）。工具命名 `{namespace}_{name}`。

| 工具 | 作用 |
| --- | --- |
| `core_ingest` | 摄入文件/URL 到 KB |
| `core_query` | 完整 RAG 查询（检索 + 生成） |
| `core_retrieve_text` | 仅文本检索 |
| `core_retrieve_visual` | 仅视觉检索 |

每个实例仅暴露 **`core_*`** 及绑定 `default_namespace` 插件的工具（G3）。Profile 下领域示例：`biomed_query_entities`、`lakehouse_bi_query_semantic_context`。所有工具接受 `kb_name`；`plugin_namespace` 为进程绑定，非运行时切换器。

插件前裸名（`ingest`、`query`）**不提供**别名。

---

## 租户：`plugin_namespace` + `kb_name`

两层模型 — 勿在 API 或 UI 文案中混用。见 [多租户](multi-tenancy.md)。

| 术语 | 层级 | 传播 |
| --- | --- | --- |
| `plugin_namespace` | 部署时领域（= Milvus Database） | 由 `settings.plugins.default_namespace` 固定；仓储注入所有 PG 读写；`MilvusClientPool` 构造时绑定 `db_name` |
| `kb_name` | Database 内 KB 标识（标量过滤） | 请求体 → runner → Celery kwargs → 向量元数据 → 查询 `MetadataFilters` |

| 阶段 | `kb_name` | `plugin_namespace` |
| --- | --- | --- |
| 摄入 API | 请求体 → runner → Celery kwargs | `register_document_sync` 经仓储 |
| 解析 | `chunks_to_text_nodes(..., kb_name=)` 元数据 | 领域 Milvus DB（向量无 per-vector namespace 标量） |
| Milvus | 每个向量的标量字段 | 按领域物理 DB 隔离 |
| 去重 | `(sha256, kb_name)` 复合 PK | 仓储过滤限定作用域 |
| 查询 | `MetadataFilters` / `_build_search_expr` | 实例绑定；请求不匹配 → 403（除非启用 override） |
| 会话 | `sessions.kb_name` 列 | `sessions.plugin_namespace` 经仓储 |
| MCP 工具 | 所有 `core_*` + 领域工具接受 `kb_name` | 实例 profile 决定暴露的 namespace |

高级：`scope_filter` 并集语义 — scoped KB / 文档 / 标签可通过摄入目录强制专用 collection plan。

---

## 设计张力与调参

| 张力 | 表现 | 缓解 |
| --- | --- | --- |
| 最终一致窗口 | API 在审计 `PENDING` 后返回；向量在 Celery 后出现 | 轮询 `/tasks/{job_id}`；`SUCCESS` 前勿查询 |
| 去重竞态 | `register` 完成前两次上传同 hash | 罕见；第二次应命中 `dedup_hit` — 监控重复审计 |
| 文本就绪先于视觉 | `knowhere_parse` 中切片索引前 `update_status(ready)` | 视觉队列追上前混合查询可能仅文本 |
| 附件 vs 索引 | 查询时前置 `parse_attachments`，不写 Milvus | 会话内证据；其他用户或 MCP `core_retrieve_*` 不可见 |
| 流式线程桥接 | `stream_custom_query` + 线程池内同步 VLM | 每 SSE 客户端一线程 — 小 API 上限制并发流 |
| 有注册表无向量 | Milvus 写入尽力而为记录错误但审计仍可能成功 | KB 重建 / 重摄入；对比 `documents.chunk_count` 与 Milvus 计数 |
| 多 collection 部分失败 | 某一 `CollectionQueryPlan` ANN 失败 | 编排器跳过该 plan 并审计，继续其余 plan |

---

## 配置

| 设置 | 影响流 |
| --- | --- |
| `ingest.routing` | 摄入管线选择 |
| `plugins.enabled` / `plugins.default_namespace` | 插件加载 + Milvus DB 绑定 |
| `plugins.query_assemble_enabled` | ANN 前 `QUERY_ASSEMBLE` |
| `router.mode` | 查询检索器选择（Core `CLASSIFY_QUERY`） |
| `router.max_scope_documents` | 标签 → document_id 解析上限 |
| `router.source_content_max_chars` | 查询响应中来源载荷大小 |
| `attachments.parse.*` | 附件懒解析限制 |
| `celery.queues` | 摄入吞吐 |
| `knowhere.poll_timeout` | Knowhere 解析最长等待 |

---

## 故障模式与运维

| 故障点 | 用户影响 | 代码行为 |
| --- | --- | --- |
| `ingest_router` 重试耗尽 | 任务 `FAILED`；死信 | `@with_retry` + `DeadLetterTask` |
| `knowhere_parse` SDK 错误 | 文档 `failed` | 不注册去重；不更新 `collections_used` |
| 插件钩子错误（PARSE/CHUNK/EMBED） | 文档 `failed` | 快速失败 → `HookInvocationError` |
| 视觉派发错误 | 文本搜索可用；无图 | `dispatch_visual_chunks` 中记录 |
| Milvus upsert 错误 | 部分索引 | 可能仍标 `SUCCESS`；目录反映实际写入 |
| 单 plan ANN 失败 | 召回降低 | 跳过 plan 并审计；其余 plan 继续 |
| VLM 超时 | 答案字段错误 | 进程不崩溃 |
| 无效 `scope_filter` 标签 | 忽略标签 | `_resolve_scope_filter` 警告 |

**重放：** 修复根因后 `POST /tasks/{job_id}/retry` 或 `replay_dead_letter()`。

---

## 参考文献

- [插件架构](plugin-architecture.md)
- [多租户](multi-tenancy.md)
- [ADR-004：多编码器 RRF 融合](adr/004-multi-encoder-rrf-fusion.md)
- [ADR-006：摄入 ↔ 查询路由契约](adr/006-ingest-query-routing-contract.md)
- [摄入管线](../backend/ingest-pipeline.md)
- [路由矩阵](routing-matrix.md)
- [检索](../backend/retrieval.md)
- [生成](../backend/generation.md)
- [API 查询](../api/query.md)
- [MCP 工具](../api/mcp-tools.md)
- [Lewis 等，2020](https://arxiv.org/abs/2005.11401)
- [Milvus 混合搜索](https://milvus.io/docs/multi-vector-search.md)
