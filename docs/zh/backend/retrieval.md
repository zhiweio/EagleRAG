# 检索

Eagle-RAG 检索在路由查询引擎后组合两个专用检索器：**KnowhereGraphRetriever** 用于结构化文本（1536 维，Milvus `eagle_text` + 图扩展），**PixelRAGVisualRetriever** 用于视觉瓦片（2048 维，Milvus `eagle_visual`）。域部署还会使用 **RetrieverOrchestrator**（`eagle_rag/plugins/retriever_orchestrator.py`）按计划在多个 collection 上查询，可选每计划 `RERANK` 钩子，以及 **RRF 合并**（`eagle_rag/router/rerank_fusion.py`）。Core 默认路由（G4）永不自动查询专用 collection。

**源模块：** `eagle_rag/retrievers/knowhere_graph_retriever.py`、`eagle_rag/retrievers/pixelrag_visual_retriever.py`、`eagle_rag/plugins/retriever_orchestrator.py`、`eagle_rag/router/rerank_fusion.py`

多编码器融合与 scope 感知 catalog 并集见[插件架构](../architecture/plugin-architecture.md)。

---

## 1. 理论背景

### 1.1 稠密段落检索（DPR）

**双编码器**检索将查询与文档独立编码到共享嵌入空间，再经近似最近邻（ANN）搜索取最近邻。这是现代开放域 QA 的基础（Karpukhin 等，arXiv:2004.04906）。

Eagle-RAG 文本检索使用 Qwen `text-embedding-v4`（1536 维，余弦相似度），**非对称编码**：文档用 `text_type=document`，查询用 `text_type=query` — 商业嵌入 API 中可提升检索质量的实践。

### 1.2 图增强检索

纯向量搜索可能漏掉结构相关分块（如与说明段落链接的表格）。Knowhere 分块携带 `connect_to` 边。ANN 召回后，检索器经 LlamaIndex docstore **沿边扩展** — 文档内部图增强，受 G-Retriever（He 等，arXiv:2402.07629）与 HippoRAG（Gutiérrez 等，arXiv:2405.14831）启发。

### 1.3 跨模态（文本到图像）检索

视觉检索将**文本查询**编码到与文档截图瓦片相同的 2048 维空间（Qwen3-VL-Embedding-2B）。可从自然语言问题检索相关页面区域 — 将 CLIP 范式（Radford 等，arXiv:2103.00020）应用于文档截图。

### 1.4 父文档检索

Knowhere 除细粒度分块外还索引 `type="section_summary"` 节点。两阶段策略：

1. 召回章节摘要（粗粒度、高信噪比）。
2. 经 `path` 前缀下钻子分块。

遵循父文档检索器模式（LlamaIndex `RecursiveRetriever`；Chen 等，arXiv:2310.09435 层级索引）。

### 1.6 倒数排名融合（RRF）

当多个 `CollectionQueryPlan` 活跃（域插件或 scope 感知 catalog 并集）时，`RetrieverOrchestrator` 每计划跑 ANN，可选每计划 `RERANK` 钩子，再用 RRF 合并 — 永不使用原始跨嵌入分数。按 `source_chunk_id`（若设置）或 `(document_id, path)` 去重。见 [ADR-004](../architecture/adr/004-multi-encoder-rrf-fusion.md)。

### 1.7 重排（下游）

检索返回 top-K 候选；**交叉编码器重排**在生成引擎中进行（`DashScopeRerank` / qwen3-rerank）。双编码器快但近似；交叉编码器联合编码 query+段落，在较小 K 上精度更高（Nogueira & Cho，arXiv:1901.04085；Reimers & Gurevych，arXiv:1908.10084）。

---

## 2. 架构

```mermaid
flowchart LR
    Q[Query string] --> RE[EagleRouterQueryEngine]
    RE --> QA[apply_query_assemble hooks]
    QA --> RD[QueryRouteClassifier / route_query]
    RD --> RO[RetrieverOrchestrator]
    RO --> TR[KnowhereGraphRetriever / per-plan ANN]
    RO --> VR[PixelRAGVisualRetriever / per-plan ANN]
    TR --> TI[VectorStoreIndex eagle_text]
    TI --> ANN1[HNSW ANN + scalar filter]
    ANN1 --> GE[connect_to graph expansion]
    VR --> EQ[embed_query 2048-d]
    EQ --> SV[search_visual eagle_visual]
    SV --> ANN2[HNSW ANN + scalar filter]
    GE --> RRF[merge_rrf]
    ANN2 --> RRF
    RRF --> NWS[NodeWithScore list]
    NWS --> GEN[EagleMultimodalQueryEngine]
```

---

## 3. RetrieverOrchestrator（多 collection）

**文件：** `eagle_rag/plugins/retriever_orchestrator.py`

当 `QueryRouteClassifier`（`CLASSIFY_QUERY` 钩子）返回多个 `CollectionQueryPlan` 时，编排器：

1. 每计划跑 ANN（尽力而为：失败计划跳过并审计）。
2. 可选应用每计划 `RERANK` 钩子。
3. 用 RRF 合并（`eagle_rag/router/rerank_fusion.py` 中的 `merge_rrf`）。
4. 返回去重后的 `NodeWithScore` 列表。

**Core 默认（G4）：** 仅 `eagle_text`（混合/图像时加 `eagle_visual`）。除非域分类器或 scope 感知 catalog 并集加入，否则不查专用 collection。

**Scope 感知并集：** 若 `scope_filter` 的 KB / 文档 / 标签 catalog 含专用 collection（`collections_used`），即使分类器弃权也强制这些计划。

---

## 4. 代码走读：KnowhereGraphRetriever

**文件：** `eagle_rag/retrievers/knowhere_graph_retriever.py`

### 4.1 构造参数

| 参数 | 用途 |
|-----------|---------|
| `top_k` / `similarity_top_k` | ANN 召回数（默认 5） |
| `kb_name` | 单 KB Milvus 过滤 |
| `kb_names` + `document_ids` | 高级 scope（OR 并集） |
| `source_type`, `year` | 分面过滤（AND） |
| `document_id` | 客户端后过滤 |

### 4.2 过滤器组装（`_build_filters`）

构建 LlamaIndex `MetadataFilters`：

```python
# 单租户
MetadataFilter(key="kb_name", value="finance", operator=FilterOperator.EQ)

# Scope 并集（OR）
MetadataFilters(
    filters=[
        MetadataFilter(key="kb_name", value=["finance", "pharma"], operator=FilterOperator.IN),
        MetadataFilter(key="document_id", value=["doc-a", "doc-b"], operator=FilterOperator.IN),
    ],
    condition=FilterCondition.OR,
)

# 与分面组合（AND）
MetadataFilters(filters=[scope_group, source_type_filter, year_filter], condition=FilterCondition.AND)
```

由 `MilvusVectorStore` 翻译为 Milvus 布尔表达式。

### 4.3 检索流程（`_retrieve`）

1. `get_text_index()` — 惰性 `VectorStoreIndex` 单例。
2. `text_index.as_retriever(similarity_top_k=K, filters=...)` → ANN 搜索。
3. 可选客户端 `document_id` 过滤。
4. **图扩展：** 对每个命中读 `metadata["connect_to"]`，从 docstore 取相关节点，按 `node_id` 去重，继承父分数。
5. 遥测：`ai_logger.info("retrieve", retriever="text", ...)`。

### 4.4 错误降级

任何 Milvus/嵌入异常 → 记录警告，返回 `[]`。路由引擎决定是否仅用视觉结果继续。

### 4.5 图扩展细节

`connect_to` 条目可为纯 chunk_id 字符串或字典 `{target, relation, ref, position}`。缺失 docstore 或目标不存在则静默跳过 — 扩展为尽力而为。

---

## 5. 代码走读：PixelRAGVisualRetriever

**文件：** `eagle_rag/retrievers/pixelrag_visual_retriever.py`

### 5.1 检索流程

```python
query_vector = embed_query(query_str)          # Qwen3-VL 文本编码，2048 维
results = search_visual(
    query_vector,
    top_k=self.top_k,
    kb_name=..., kb_names=..., document_ids=...,
    year=..., source_type=...,
    parent_section=..., chunk_type=...,
)
nodes = [self._to_node_with_score(r) for r in results]
```

### 5.2 ImageNode 构造

每个 Milvus 命中成为 `ImageNode`，元数据：

| 字段 | 来源 |
|-------|--------|
| `image_id`, `document_id`, `page`, `position` | Milvus 标量 |
| `kb_name`, `year`, `source_type` | Milvus 标量 |
| `chunk_type`, `parent_section`, `content_summary`, `source_chunk_id` | 融合锚点 |

Milvus 返回 None 时分数默认为 1.0。

### 5.3 跨模态编码

`embed_query()` 委托给 `get_visual_encoder().embed_text()` — 与摄取相同的工厂。保证查询与瓦片向量在同一归一化空间（同一 `embedding.visual.provider`；本地路径为末 token 池化 + L2）。

---

## 6. Milvus schema 与过滤表达式

### 6.1 文本 collection `eagle_text`

**向量：** 1536 维 FLOAT_VECTOR，COSINE 度量（经 LlamaIndex `MilvusVectorStore`）。

**过滤用标量/元数据字段：**

| 字段 | 示例 expr |
|-------|-------------|
| `kb_name` | `kb_name == "default"` |
| `document_id` | `document_id == "550e8400-..."` |
| `source_type` | `source_type == "financial"` |
| `year` | `year == 2025` |
| `type` | `type == "section_summary"` |
| `path` | `path like "report/Chapter 3%"` |

**组合示例：**

```
kb_name == "finance" and source_type == "policy"
```

```
(kb_name in ["finance", "pharma"] or document_id in ["doc-1", "doc-2"]) and year == 2025
```

索引参数（LlamaIndex Milvus 集成管理）：HNSW + COSINE；标量字段作为动态元数据索引。

### 6.2 视觉 collection `eagle_visual`

**向量：** 2048 维 FLOAT_VECTOR，**IP**（内积）度量。

**索引参数**（`milvus_visual_store.py`）：

| 索引类型 | 参数 |
|------------|--------|
| HNSW（默认） | `M=16`，`efConstruction=256`，搜索 `ef=64` |
| DiskANN | `metric_type=IP`，无额外搜索参数 |

**标量倒排索引：** `kb_name`、`document_id`、`source_type`、`year`、`chunk_type`、`parent_section`。

**过滤示例：**

```
kb_name == "pharma" and chunk_type == "tile"
```

```
document_id == "abc-123" and year in [2024, 2025]
```

```
(kb_name in ["finance"] or document_id in ["doc-x"]) and source_type == "financial" and parent_section like "%Balance Sheet%"
```

由 `search_visual()` 中 `_build_search_expr()` 构建。

---

## 7. LlamaIndex 集成

| 组件 | 角色 |
|-----------|------|
| `BaseRetriever` | 两检索器均子类化；实现 `_retrieve(QueryBundle)` |
| `TextNode` | Knowhere text/table/image/section_summary 分块 |
| `ImageNode` | 视觉命中（检索时创建，不在 docstore） |
| `NodeWithScore` | 带相似度分数的统一输出 |
| `VectorStoreIndex` | 经 `as_retriever()` 的文本 ANN |
| `MetadataFilters` | 声明式标量过滤 → Milvus expr |
| `QueryBundle` | 包装查询字符串供 `_retrieve` |

视觉检索**不**使用 `VectorStoreIndex` — 直接调用 `pymilvus.MilvusClient.search()`，因嵌入模型为自定义（Qwen3-VL 单例，非 LlamaIndex `BaseEmbedding`）。

**Docstore 图扩展：** `text_index.docstore.get_node(target_id)` 获取已在 Milvus/LlamaIndex 存储中索引的相关 `TextNode`。

---

## 8. Scope 过滤

两种 scope 机制并存：

### 8.1 遗留 `scope: list[str]`

文档 ID 列表；检索后客户端过滤（`_filter_by_scope`）。

### 8.2 高级 `scope_filter: ScopeSelection`

```json
{
  "kb_names": ["finance", "pharma"],
  "document_ids": ["doc-a"],
  "tags": ["增值税", "2025"]
}
```

- 标签经 `document_keywords` 表解析为文档 ID（`resolve_tags_to_document_ids`，namespace 范围）。
- 并集（OR）语义：`(kb_name IN ...) OR (document_id IN ...)` 下推到 Milvus。
- scope 匹配时从 `collections_used` catalog 并集专用 collection（[scope_routing](../architecture/plugin-architecture.md)）。
- 受 `router.max_scope_documents` 限制（默认 500）。

---

## 9. 设计张力与调优

| 张力 | 位置 | 效果 | 缓解 |
| --- | --- | --- | --- |
| **图扩展分数继承** | `knowhere_graph_retriever._retrieve`：扩展节点得父 `nws.score` | 链接表格/脚注排名与主命中一样高，即使与查询向量相似度低 | 扩展噪声大时降低 `top_k`；在分面中过滤 `type` |
| **扩展视野** | 仅初始 ANN 命中的 `connect_to`，一跳 | 多跳推理链不遍历 | 在解析时丰富 Knowhere `connect_to`，非检索器 |
| **Docstore 可用性** | `text_index.docstore` try/except → 跳过扩展 | 相同 ANN 结果是否带图取决于 docstore 同步 | 重索引后验证 docstore 与 Milvus 节点 ID 一致 |
| **Scope OR 基数** | `_build_filters`：`kb_names OR document_ids` AND 分面 | 大标签→文档并集接近 `max_scope_documents` 上限 — 尾部文档静默排除 | 收窄标签；在 `ai_logger` 路由事件中监控解析文档数 |
| **遗留 scope 后过滤** | `scope_filter` 未激活时 `_filter_by_scope` | Milvus 返回全局 top-K 再 Python 过滤 — 浪费 ANN 且扭曲分数 | 多文档 QA 优先 `scope_filter` 下推 |
| **视觉查询-图像鸿沟** | `embed_query` 文本在 2048 维截图空间 | 纯政策文本问题检索无关页面区域 | 路由 `visual` 路径；用 `chunk_type` / `parent_section` 过滤 |
| **空检索器降级** | except → `[]` | 混合查询静默变单路径 | 在 SSE 中检查 `recall` 步 `text_count`/`visual_count` |
| **RRF vs 原始分数** | 多计划 ANN 后 `merge_rrf` | 无法按分数排序混合 1536 维 / 域编码器命中 | 遥测用排名位置，非原始 Milvus 距离 |
| **G4 专用弃权** | Core `CLASSIFY_QUERY` | 除非分类器或 catalog 并集加入，域 collection 永不查询 | Core 预期行为；专用召回需启用域 profile |
| **章节摘要下钻** | 检索器中非自动父文档模式 | 须过滤 `type=="section_summary"` 或依赖提示中 path 重叠 | 客户端两阶段搜索或未来检索器模式 |

**ANN + 过滤交互：** 存在倒排索引时 Milvus 在 HNSW 搜索中应用标量谓词；否则过滤在 ANN 之后 — 相同 `expr`，不同延迟特征（见 [vector-stores](vector-stores.md) §8）。

---

## 10. 配置与调优

### 10.1 检索 top_k

查询时经 `QueryRequest.top_k` 设置（默认 5）。以 `similarity_top_k` / `top_k` 传给两检索器。

### 10.2 嵌入

```yaml
embedding:
  text:
    model: text-embedding-v4
    dim: 1536
  visual:
    provider: pixelrag
    model: Qwen/Qwen3-VL-Embedding-2B
    dim: 2048
```

### 10.3 Milvus 视觉索引

```yaml
milvus:
  visual_index_type: hnsw    # hnsw | diskann
  dim_text: 1536
  dim_visual: 2048
```

**调优指南：**

| 目标 | 调整 |
|------|-----------|
| 更高召回 | 提高 `top_k`（5 → 10） |
| 更快视觉搜索 | 较低 `ef` 的 HNSW（牺牲召回） |
| 大视觉语料 | 切换到 `diskann` |
| 更窄结果 | 添加 `source_type` / `year` 分面过滤 |
| 章节优先检索 | 过滤 `type == "section_summary"` 再按 path 下钻 |

### 10.4 重排（下游）

```yaml
rerank:
  text:
    model: qwen3-rerank
```

生成引擎 `top_n`（默认 3）控制重排后数量 — 见 [generation](generation.md)。

---

## 11. 测试

**主要：** `tests/test_retrievers.py`

| 测试领域 | 契约 |
|-----------|----------|
| 文本 ANN 召回 | Mock `get_text_index().as_retriever().retrieve()` |
| kb_name 过滤下推 | `MetadataFilter(key="kb_name", ...)` 传给检索器 |
| 图扩展 | 从 docstore 取 `connect_to` 目标并去重 |
| Scope 并集 | `kb_names` + `document_ids` OR 过滤器组装 |
| 视觉嵌入 + 搜索 | Mock `embed_query` + `search_visual` |
| ImageNode 元数据 | 融合锚点字段保留 |
| 错误降级 | 异常 → 空列表，不抛出 |
| 分面过滤 | `source_type`、`year`、`chunk_type`、`parent_section` |

**相关：**

- `tests/test_milvus_structure_fetch.py` — 从 Milvus 重建文档结构
- `tests/test_router_generation.py` — 端到端 route → retrieve → generate
- `tests/plugins/test_encoder_runtime.py` — 域编码器路由

---

## 12. MCP 暴露

MCP 工具直接调用检索器：

| 工具 | 检索器 |
|------|-----------|
| `core_retrieve_text` | `KnowhereGraphRetriever` / `RetrieverOrchestrator` |
| `core_retrieve_visual` | `PixelRAGVisualRetriever` |

均接受 `kb_name`、`top_k` 与分面过滤。

---

## 13. 性能特征

| 检索器 | 瓶颈 | 典型延迟驱动 |
|-----------|-----------|----------------------|
| 文本 | DashScope 嵌入 API + Milvus ANN | 到 DashScope 的网络 RTT |
| 视觉 | 本地 Qwen3-VL 编码（首次调用加载模型）+ Milvus ANN | GPU/CPU 推理 |
| 图扩展 | Docstore 查找 | 每命中的 `connect_to` 边数 |

两检索器发出 OpenTelemetry span（`retrieve.text`、`retrieve.visual`）与 AI 遥测 JSONL 事件。

---

## 14. 参考文献

- Karpukhin 等，*Dense Passage Retrieval*，[arXiv:2004.04906](https://arxiv.org/abs/2004.04906)
- Nogueira & Cho，*Passage Re-ranking with BERT*，[arXiv:1901.04085](https://arxiv.org/abs/1901.04085)
- Reimers & Gurevych，*Sentence-BERT*，[arXiv:1908.10084](https://arxiv.org/abs/1908.10084)
- Radford 等，*CLIP*，[arXiv:2103.00020](https://arxiv.org/abs/2103.00020)
- He 等，*G-Retriever*，[arXiv:2402.07629](https://arxiv.org/abs/2402.07629)
- Gutiérrez 等，*HippoRAG*，[arXiv:2405.14831](https://arxiv.org/abs/2405.14831)
- Chen 等，*Dense Hierarchical Retrieval*，[arXiv:2310.09435](https://arxiv.org/abs/2310.09435)
- Milvus HNSW 索引：[milvus.io/docs/index.md](https://milvus.io/docs/index.md)
- Milvus 布尔表达式：[milvus.io/docs/boolean.md](https://milvus.io/docs/boolean.md)
- LlamaIndex 检索器：[docs.llamaindex.ai/module_guides/querying/retriever](https://docs.llamaindex.ai/en/stable/module_guides/querying/retriever/)
- LlamaIndex 元数据过滤：[docs.llamaindex.ai/examples/vector_stores/MilvusIndexDemo](https://docs.llamaindex.ai/en/stable/examples/vector_stores/MilvusIndexDemo/)
