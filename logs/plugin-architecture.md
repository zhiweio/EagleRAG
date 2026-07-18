# EagleRAG 微内核 + 插件 + MCP 生态架构升级方案

> **设计账本（非规范文档）** — 实现状态以官方文档为准：
> [`docs/en/architecture/plugin-architecture.md`](../docs/en/architecture/plugin-architecture.md) ·
> [`docs/en/architecture/adr/007-plugin-implementation-status.md`](../docs/en/architecture/adr/007-plugin-implementation-status.md) ·
> ADR-008（纯 RAG / 前端=Core only）。
>
> 状态：**已实现（Implemented）** — M1–M8 已落地；下文保留设计推演，烤问清单中已闭合项标为 ✅。
> 日期：2026-07-14（2026-07-18 同步：视觉 `get_visual_encoder`、PluginAudit、BiomedCLIP/`open_clip`）
> 适用分支：`feature/multi-industry`
>
> **运行时命名提示**：放射编码器 label 仍为 `medimageinsight`，默认 checkpoint 为 **BiomedCLIP via `open_clip`**（非独立 MedImageInsight 产品权重）。Core 视觉经 `eagle_rag/ingest/visual_encoder.py` 的 `get_visual_encoder()`（`pixelrag` | `dashscope`）。

---

## 〇、产品红线（最高约束）

EagleRAG **完完全全是 RAG 系统**，不是业务 Agent 应用平台。

| 做（本系统职责） | 不做（下游 Agent / 客户应用职责） |
| --- | --- |
| 文档/资产 ingest、分块、多编码器向量化、多 collection 检索、RRF、溯源 | 业务工作流编排、多步 Agent 规划/反思循环 |
| REST / SSE / MCP 暴露 **检索与入库** 能力 | Text-to-SQL 执行、取数、改库、发邮件、下单等副作用 |
| 行业插件提升 **召回质量 / 精度 / 资产结构化** | 行业 Agent UI、对话策略、审批、可视化仪表盘 |
| 返回结构化上下文包 + sources（给 Agent 用） | 替 Agent「做决策」或「完成业务闭环」 |

### 前端 vs 后端范围

| 表面 | 范围 | 要求 |
| --- | --- | --- |
| **内置前端** | **仅 Core** | 展示 knowhere（语义结构化文本）+ pixelrag（视觉）混合检索 |
| **垂类扩展**（biomed、lakehouse-bi、…） | **仅后端 MCP** | 实现 + 测试 + MCP 契约；**不**规划垂类前端 |
| **下游消费** | Agent / 客户自建 UI | 通过 MCP/API 集成 |

二开指南：[`docs/zh/guides/authoring-industry-plugin.md`](../guides/authoring-industry-plugin.md)；模板：`plugins/_template/`。

### Hook 热路径矩阵（须真实接线）

| Hook | 模式 | 热路径插入点 | RAG 语义 |
| --- | --- | --- | --- |
| `PARSE` | transform | Knowhere parse 后 | 解析 enrich |
| `CHUNK` | transform | nodes → IngestOrchestrator 前 | 领域 metadata enrich（保留 Knowhere 骨架） |
| `QUERY_ASSEMBLE` | all（可降级） | Router ANN 前 | query 扩写 / 上下文 hint |
| `CLASSIFY_*` / `EMBED_*` / … | first / transform | orchestrator | 分类与编码 |

实现：`eagle_rag/plugins/hotpath_hooks.py`。配置：`plugins.options.<ns>`（勿再往 Core 加行业 typed settings）；`source_type.rules` Core 默认为空。

---

## 一、目标与约束

将 EagleRAG 从"单一多模态 RAG 系统"重构为 **微内核（Core）+ 领域插件（Plugin）+ 统一 MCP** 架构。

**用户确认的关键决策：**

- **插件运行模式**：进程内加载，共享模型单例（PubMedBERT / Qwen3-VL 等在 Core 进程内常驻），热路径（embed/retrieve）零 RPC 序列化开销。
- **MCP 暴露**：单一聚合 `/mcp`；工具名 **`{namespace}_{name}`**（下划线分隔，对齐 FastMCP 惯例），如 `core_ingest`、`biomed_query_entities`、`lakehouse_bi_query_semantic_context`。单域实例**仅注册** `core_*` + `default_namespace` 对应插件工具（见 §拍板 G3）。
- **数据隔离（Milvus Database = 领域命名空间，底座恒在 + 专用增量）**：底层统一 Milvus 实例，**每个 `plugin_namespace` 对应一个独立的 Milvus Database**（物理隔离），该 Database 内**至少**有一对基础 Collection（`eagle_text` + `eagle_visual`）共置所有 KB（`kb_name` 标量过滤）；插件可按需**新增**领域专用 Collection（如 `eagle_text_biomed`/`eagle_chemical`）承载特殊数据，基础底座恒在、专用增量按需。不新增 `plugin_namespace` 标量字段、不做二维标量过滤。**不引入** Spark / dbt 运行时 / Trino 等重型组件。
- **模型策略**：Core 仅保留基于 DeepSeek/Qwen 的全局路由调度与生成编排；领域插件**允许**内部集成领域专用模型（如 biomed 插件的 PubMedBERT 负责向量化与重排）。
- **模态与融合的边界**：PixelRAG 视觉模态（render + Qwen3-VL 编码 + `eagle_visual` + `PixelRAGVisualRetriever`）是 Core 的**一等公民**，不可裁剪--EagleRAG 的存在理由就是解决"纯文本 RAG 对图/表/版式失明"。可插拔的只是"四锚点桥接逻辑"（`extract_visual_chunks` 的锚点赋值、检索侧 `parent_section`/`source_chunk_id` 过滤），作为 Core 默认行为，**不**做成可禁用的独立插件。领域插件（biomed/lakehouse）可裁剪，视觉模态不可裁剪。
- **首个业务插件**：`plugins/biomed/`（同仓生物医药插件，允许 PubMedBERT/BioBERT）；第二个 `plugins/lakehouse-bi/` 作为湖仓语义层 RAG 检索插件。
- **产品语义（租户模型）**：**单域部署**（G1）——每个实例绑定单一 `plugin_namespace`（= Milvus Database）；用户在该实例内 **选 KB（`kb_name`）** 即可，**不做**运行时领域切换。`plugin_namespace` 由部署配置固定，API 未传时回落 `settings.plugins.default_namespace`；前端/API 不得将 `kb_name` 与 `plugin_namespace` 混称为 "namespace"。
- **部署与检索边界**：**单服务实例绑定单一 Milvus Database**（由 `settings.plugins.default_namespace` 固定）。**永不做单次 query 跨 DB**；单次 query **可以**在同一 DB 内跨多个 collection（如 biomed 的 `eagle_text` + `eagle_text_biomed` + `eagle_visual`）。跨领域检索由**多实例部署**承担，Core 不内置 fan-out。
- **MCP 兼容**：接受 **breaking change**——Core 工具统一加 `core_` 前缀（`ingest` → `core_ingest` 等），**不提供**旧名 alias。
- **默认查询路由（G4）**：Core 默认 `QueryRouteClassifier` **永不**自动查专用 collection（仅 `eagle_text` + 可选 `eagle_visual`）；专用 collection 仅由领域插件分类器显式加入 `plans`。
- **父文档检索（G5）**：`settings.router.parent_doc_retrieval` **默认 `true`**（召回质量优先；可关）。
- **多路合并（G8）**：多 collection 分路 RERANK 后统一用 **RRF** 合并，禁止跨 embedding 空间 raw score 排序。
- **PG 隔离（G9/G10）**：所有 PG 读写经 repository 层**强制**注入 `plugin_namespace`；`document_keywords` / tag 解析 / `scope_filter` 均带 namespace 维度，同名 KB 跨 namespace 不串。
- **插件信任**：**仅加载同仓** `plugins/*` 模块（`settings.plugins.enabled` 显式列表）。**不启用** Python `entry_points` 外部 pip 包加载。
- **医学影像编码器（M6）**：通用放射影像（CT/MRI/超声）首选 **MedImageInsight**；病理切片（HE 染色）首选 **UNI 2**。不回落 Qwen3-VL 作为医学影像最终编码器。
- **医学影像 collection（已拍板）**：拆为 **`eagle_medical_radiology`**（MedImageInsight）与 **`eagle_medical_pathology`**（UNI 2）两个专用 collection，各自独立维度，不做统一 projection。
- **对象存储隔离（G12）**：`images` 表 + MinIO object key（含 **原始文档** 与 tile）+ MCP cache key **均贯穿 `plugin_namespace`**，与 Milvus DB 对齐（见 §1.8）。
- **PG 运维表隔离（G11）**：`task_audit` / `notifications` / `mcp_call_log` 同步加 `plugin_namespace`（多实例共用 PG 时防串线；见 §1.4）。
- **Hook 异常策略（G13）**：ingest/query 热路径 **fail-fast**；仅 `QUERY_ASSEMBLE` 允许 per-plugin try/except 降级（见 §0.1）。
- **Orchestrator 分路失败（G14）**：多 collection ANN **best-effort 合并** + `PluginAudit` 记失败路（见 §2.5）。
- **Biomed 查询路由 v1（G15）**：**规则 + UMLS 实体触发**，abstain → G4 默认；**不用 LLM 做查询分类**（见 §5.0）。
- **Knowhere 职责边界（G16）**：Eagle **不调用** Knowhere `RetrievalAgent` / `WorkflowOrchestrator`；父文档检索仅在 Milvus `eagle_text` 两阶段（见 §4.0）。
- **PyMilvus 连接语义（G17）**：同 URI 的 `MilvusClient` **共享底层连接**（`alias` 不等于独立连接）；构造时绑定 `db_name=`、**禁止** per-request `using_database` 切换与 `close()`；M2 阻塞 spike 验证 FastAPI + Celery 无竞态（见 §1.2）。
- **PG 子表硬隔离（G18）**：`documents` 保留 `document_id` 全局唯一 PK；子表（`images`/`document_keywords`/`task_audit` 等）FK **必须**带 `plugin_namespace` 维度（复合 FK 或等价约束），禁止仅按 `document_id` JOIN（见 §1.4）。
- **API namespace 信任边界（G19）**：生产环境 repository **只信任** `settings.plugins.default_namespace`，**忽略**请求体 `plugin_namespace`；显式传入且与实例不一致 → **403**（非 warn）；测试环境可用 `settings.plugins.allow_namespace_override` 放开（见 §1.7）。
- **Biomed 默认双路 ANN（G20）**：biomed 实例纯文本 query **默认仅** `eagle_text`；**仅当** UMLS/规则命中生物医学实体时加 `eagle_text_biomed`；`settings.plugins.options.biomed.default_dual_text_search` 默认 `false`（见 §5.0）。
- **Ingest–Query 路由契约（G21）**：入库 per-chunk 分类与查询 `QueryRouteClassifier` 必须闭合——scope 含专用 collection 入库文档/KB 时，查询侧 **scope-aware** 强制加入对应 collection plans（见 §2.5.2.2、§5.0）。
- **入库编码编排（G22）**：新增 **`IngestOrchestrator`**（与 `RetrieverOrchestrator` 对称）+ `EMBED_TEXT`/`EMBED_VISUAL`/`UPSERT_VECTORS` hook；`ClassificationDecision.target_encoder` 由编排器经 `EncoderRegistry` 编码落库（见 §2.6）。
- **KB 级 scope catalog（G23）**：`scope_filter.kb_names` 非空时，按 KB 级 `collections_used` 聚合做 scope-aware 并集（与 document 级对称）；见 §1.9、§2.5.2.2。
- **Milvus 客户端池化（G24）**：统一 `MilvusClientPool`；**禁止** health/stats/lifecycle 等路径 `MilvusClient.close()`（现网 `kb/stats.py`/`api/health.py` 等须迁移）；见 §1.2。
- **KB 可观测性（G25）**：`kb/stats` / `GET /knowledge-bases/*/collections` 扇出 `PluginManager.provides_specialized_collections`，绑定 `plugin_namespace` + `db_name`；见 §1.9。
- **Ingest hook 顺序（G26）**：固定 `PARSE → CHUNK → INGEST_VISUAL_EXTRACT → CLASSIFY_* → IngestOrchestrator`；见 §0.1、§2.6。
- **全库探索性检索边界（G27）**：无 scope 且无 UMLS 时 biomed 仅查 `eagle_text`——产品须明示；UI 空 scope 提示或 `biomed.exploratory_search_collections` 配置放宽；见 §1.7、§5.0。
- **Collection catalog 存储（G28）**：v1 用 `documents.extra["collections_used"]` + `knowledge_bases.collections_used`（JSON 数组）；不新建表；见 §1.9。
- **Tags scope catalog（G29）**：`scope_filter.tags` 经 `resolve_tags_to_document_ids(namespace)` 解析为 `document_ids` 后，走与 document scope 相同的 catalog 并集路径；见 §1.9、§2.5.2.2。
- **Catalog 提交时机（G30）**：`collections_used` **仅在 ingest 终态成功**（`documents.status=success`、全 chunk 写入 Milvus 后）更新；失败/部分成功不污染 KB catalog；见 §1.9、§2.6。
- **KB rebuild 与 catalog（G31）**：`rebuild_kb` 启动时清空 `knowledge_bases.collections_used`，逐文档成功后重算并集；单文档删除后 KB 并集重算（或 rebuild 时惰性重算）；见 §1.4、§1.9。
- **RRF 跨 collection 去重（G32）**：双写（P1-9）导致同一逻辑块出现在多 collection 时，RRF 后按 `source_chunk_id`（非空）或 `(document_id, path)` **dedupe**，保留较高 rank；见 §2.5。
- **Session 列表 namespace 过滤（G33）**：`sessions`/`messages` repository 的 `list_sessions`/`get_session` **强制** `plugin_namespace = default_namespace`；写入时自动注入；见 §1.4。

> 注：本次为重大架构升级。`AGENTS.md` 中关于"仅限特定模型"与"领域禁用硬编码"的旧约束，在本架构演进的相应阶段同步更新；Core 仍保持 DeepSeek/Qwen 调度与生成编排。

### 拍板决策（Grilling 结论，2026-07-10）

| ID | 问题 | 决策 |
| --- | --- | --- |
| G1 | 前端单域还是多域网关？ | **单域部署**：实例固定 `default_namespace`；UI **无**领域切换器 |
| G2 | MCP 工具名分隔符？ | **`{namespace}_{name}`**（下划线），如 `biomed_query_entities` |
| G3 | 非 `default_namespace` 的 MCP 工具是否注册？ | **否**。实例只暴露 `core_*` + `default_namespace` 插件工具；`enabled` 与 `default_namespace` 启动时联动校验（fail-fast） |
| G4 | 默认 QueryRouteClassifier 是否自动查专用 collection？ | **永不**；仅 `eagle_text`（+ hybrid 时 `eagle_visual`） |
| G5 | `parent_doc_retrieval` 默认开还是关？ | **默认开** |
| G6 | LlamaIndex 不支持 `db_name` 时是否重写 text store？ | **接受** Phase 1 用原生 `MilvusClient(uri, db_name=)` 薄封装（与 visual store 对齐） |
| G7 | biomed 独立 pipeline 还是 knowhere + hooks？ | **knowhere + hooks**（不新增 `biomed` pipeline 名） |
| G8 | 多路 RERANK 合并算法？ | **RRF** |
| G9 | PG 是否强制 repository 注入 `plugin_namespace`？ | **强制** |
| G10 | 同名 KB 跨 namespace 的 tag/scope？ | **加 `plugin_namespace` 区分** |
| G11 | `task_audit` / `notifications` / `mcp_call_log` 是否加 `plugin_namespace`？ | **加**（部署契约：多实例可共用 PG；repository 强制注入） |
| G12 | MinIO **原始文档** object key 是否加 namespace 前缀？ | **是**：`{plugin_namespace}/{source_type}/{document_id}/{name}`（与 tile 路径对称） |
| G13 | Hook 订阅者抛异常时？ | **ingest/query fail-fast**；仅 `QUERY_ASSEMBLE` per-plugin 降级（其余插件仍合并） |
| G14 | Orchestrator 单路 ANN 失败？ | **best-effort**：成功路继续，失败路记 `PluginAudit` + warn 日志，不整 query 失败 |
| G15 | Biomed 查询路由 v1 实现？ | **规则 + UMLS 实体触发**；abstain → G4；**不用 LLM** 做 collection 分类（零额外延迟） |
| G16 | Knowhere Agentic 与 Eagle 检索边界？ | Eagle **不调用** Knowhere `RetrievalAgent`/`WorkflowOrchestrator`；parse/doc_nav 归 Knowhere；query 热路径归 Eagle Milvus 多 collection + RRF |
| G17 | PyMilvus 同 URI 是否真隔离连接？ | **否**：同 URI 共享连接；`db_name=` 构造绑定 DB 上下文；**禁止** `close()` / per-request `using_database`；M2 spike 验证无竞态 |
| G18 | `documents.document_id` 全局 PK，子表 JOIN 会否串线？ | `document_id` 保持全局唯一；子表 FK **带 `plugin_namespace`**（复合 FK 或 `(document_id, plugin_namespace)` 唯一约束 + repository 强制） |
| G19 | API 可选 `plugin_namespace` 不一致时？ | 生产：**忽略**请求参数，仅用 `default_namespace`；显式传入不一致 → **403**；测试用 `allow_namespace_override` |
| G20 | Biomed 实例默认是否双路 text ANN？ | **否**：默认仅 `eagle_text`；UMLS/规则命中才加 `eagle_text_biomed`；`biomed.default_dual_text_search=false` |
| G21 | 入库分类与查询路由不一致（chunk 仅在专用库）？ | **scope-aware plans**：scope 内文档 catalog 含专用 collection 时，查询强制加入对应 plans；ADR-006 |
| G22 | 专用 encoder 入库谁调用？ | **`IngestOrchestrator`** + `EMBED_*`/`UPSERT_VECTORS` hooks；分类后 encode → upsert，对称 RetrieverOrchestrator |
| G23 | scope 仅 `kb_names` 时 G21 是否失效？ | **KB 级 `collections_used` 聚合**；`scope_kb_names` 非空时按 KB catalog 做 scope-aware 并集 |
| G24 | 现网大量 `MilvusClient.close()` 与 G17 冲突？ | **`MilvusClientPool` 池化**；禁止对外 `close()`；M2 grep 清零临时 client（health/stats/lifecycle） |
| G25 | KB stats/API 只认 2 个 collection？ | `get_kb_stats` / `get_collections` 扇出 `PluginManager` 专用 collection + `db_name` |
| G26 | `INGEST_VISUAL_EXTRACT` 与 `CLASSIFY_VISUAL` 顺序？ | **`PARSE→CHUNK→INGEST_VISUAL_EXTRACT→CLASSIFY_*→IngestOrchestrator`** |
| G27 | 全库无 scope 探索性 query 漏专用库？ | **产品显式接受**；M2.5 UI 提示；可选 `biomed.exploratory_search_collections` |
| G28 | catalog 存 `documents.extra` 还是新表？ | **v1**：`documents.extra["collections_used"]` + `knowledge_bases.collections_used`；热点后再拆表 |
| G29 | scope 仅 `tags` 时 G21 catalog 路径？ | **tags → document_ids(namespace) → documents.extra.collections_used 并集**；与 document scope 对称 |
| G30 | 失败/部分 ingest 是否更新 catalog？ | **否**；仅 `documents.status=success` 且全 chunk upsert 后更新 document/KB catalog |
| G31 | KB rebuild/delete 后 `collections_used` 陈旧？ | **rebuild 清空 KB 并集**、逐文档成功重算；delete KB 删行；单文档删后 KB 并集重算 |
| G32 | RRF 后同一 chunk 双 collection 重复？ | RRF 后按 `source_chunk_id` 或 `(document_id, path)` dedupe，保留较高 rank |
| G33 | `list_sessions` 无 namespace 过滤泄漏元数据？ | repository **强制** `plugin_namespace`；`get`/`list`/`create` 自动注入实例 namespace |

**G3 说明**：单域部署下，biomed 实例的 `/mcp` 只应有 `core_*` + `biomed_*`；若 `enabled` 含 `plugins.lakehouse_bi` 但 `default_namespace: biomed`，**启动失败**（避免 Agent 发现可调但无数据的工具）。跨领域由**多实例**各自暴露本域 MCP。

完整审查项见 **§六、Grilling 审查清单（P0 / P1 / P2）**。

## 二、现状关键发现（决定重构策略）

已通过代码探明，以下事实直接决定重构手法：

1. 已有两个干净的 **Protocol + FallbackChain** 缝隙：`IngestRouteSelector`（`eagle_rag/ingest/selectors.py:63`）与 `RouteSelector`（`eagle_rag/router/selectors.py:40`）--直接作为 HookBus 的雏形。
2. **无统一 `IngestPipeline` 协议**：`knowhere_adapter` 与 `pixelrag_adapter` 是 ad-hoc 模块函数 + Celery task，返回类型不统一（`TextNode` vs tile dict）。这是重构的主缝隙。
3. MCP 是 `@mcp.tool()` 装饰器 + **手工同步的 `TOOL_DEFINITIONS` 列表**（`eagle_rag/api/mcp_server.py:83-232` 与 `:240-790` 手动对齐）--无注册表，是插件工具化的最清晰切入点。
4. `kb_name` 已完整贯穿 API -> stores -> Milvus 标量过滤--此成熟模型保留不变；`plugin_namespace` 改用 Milvus Database 物理隔离（不再克隆标量过滤）。
5. 四个锚点字段（`chunk_type`/`parent_section`/`content_summary`/`source_chunk_id`）仅在 `knowhere_visual_chunks`（`eagle_rag/ingest/pixelrag_adapter.py:683-696`）写入--但需区分两个性质不同的关注点：① PixelRAG 视觉模态（render + Qwen3-VL + `eagle_visual` + `PixelRAGVisualRetriever`）是 Core 一等公民，不可裁剪；② 四锚点桥接逻辑（文本骨架↔视觉向量的链接赋值与检索过滤）是可重构的"融合"关注点，但仍属 Core 默认行为，不做成可禁用插件。
6. Celery `include=` 是静态 4 模块列表（`eagle_rag/tasks/celery_app.py:28-33`）；`ingest_router` 用硬编码 `_KNOWHERE_TASK`/`_PIXELRAG_TASK` 派发（`eagle_rag/ingest/router.py:314-319`）--需改为 pipeline 注册表派发。

---

## 三、架构总览

```
                         External Agents / LLMs
                                  │  one endpoint
                                  ▼
┌─────────────────────────────────────────────────────────┐
│ Core (微内核)                                            │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ PluginManager│─>│  HookBus     │  │ FastMCP /mcp  │  │
│  │ (load pkgs)  │  │ (in-process) │  │ (aggregate ALL│  │
│  └──────┬───────┘  └──────┬───────┘  │  plugin tools)│  │
│         │ discover         │ hooks    └───────┬───────┘  │
│  ┌──────▼──────────────────▼──────────────────▼───────┐  │
│  │ Core services: IngestPipeline registry, Retriever  │  │
│  │ registry, MCP tool registry, Celery task registry, │  │
│  │ global routing (DeepSeek) + generation (Qwen-VL)   │  │
│  ┌────────────────────▼────────────────────────────────┐  │
│  │ Milvus instance                                     │  │
│  │   DB "default"(core)   DB "biomed"   DB "lakehouse_bi"│  │
│  │   ├─ eagle_text (1536d) ├─ eagle_text  ├─ eagle_text│  │
│  │   ├─ eagle_visual      ├─ eagle_visual ├─ eagle_vis │  │
│  │   └─ (base, always)    ├─ eagle_text_  ├─ (base)    │  │
│  │                        │  biomed(768d) │            │  │
│  │                        ├─ eagle_chem   │            │  │
│  │                        ├─ eagle_med_   │            │  │
│  │                        │  radiology    │            │  │
│  │                        └─ eagle_med_   │            │  │
│  │                           pathology    │            │  │
│  │   (plugin_namespace=DB; kb_name=scalar filter)      │  │
│  │ PostgreSQL (documents + dedup + KB + sessions)      │  │
│  └─────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
        ▲ in-process hooks         ▲ in-process hooks
┌───────┴──────────┐  ┌────────────┴──────────┐  ┌──────────────┐
│ Core: PixelRAG    │  │ biomed plugin          │  │ lakehouse-bi │
│ visual modality   │  │ PubMedBERT embed/rerank│  │ 语义层 RAG    │
│ (render+Qwen3-VL  │  │ IMRaD section tagger,  │  │ (只读检索)    │
│  + eagle_visual,  │  │ SMILES (复用 Core 视觉) │  │              │
│  一等公民不可裁剪) │  │                        │  │              │
└───────────────────┘  └────────────────────────┘  └──────────────┘
```

**核心设计原则：**

- Core 与插件走同一套扩展机制：Core 自身也注册为 namespace=`"core"` 的"内置插件"，无特权代码路径。
- 进程内 Hook 总线：热路径（parse/chunk/embed/retrieve/rerank）零序列化开销，模型单例共享。
- **模态不可裁剪，领域可裁剪**：PixelRAG 视觉模态是 Core 一等公民（EagleRAG 的存在理由是解决纯文本 RAG 对图/表/版式失明）；可启停的是领域插件（biomed/lakehouse），不是模态。
- **两层隔离**：Milvus **Database** = `plugin_namespace`（物理隔离，跨命名空间零泄漏）；Database 内**至少**一对基础 Collection（text+visual）共置所有 KB，`kb_name` 作标量过滤，插件可按需新增专用 collection。向后兼容（默认 Database = `"default"`，等价于现 `core` 命名空间）。含连字符的 namespace（如 `lakehouse-bi`）映射为 Milvus 合法 DB 名（`lakehouse_bi`）。
- **单实例单 DB**：部署层固定实例所属 `plugin_namespace`；查询在同一 DB 内可跨 collection，不可跨 DB。
- 单一聚合 MCP：本实例 `/mcp` 暴露 `core_*` + `default_namespace` 插件工具（工具名 `{namespace}_{name}`，见拍板 G2/G3）。

---

## 四、阶段分解

### Phase 0 - 插件微内核地基（无行为变更，全量走 core 默认）

#### 0.1 新增 `eagle_rag/plugins/` 包

**`eagle_rag/plugins/contract.py`** - 插件契约（dataclass + Protocol）：

```python
@dataclass(frozen=True)
class PluginManifest:
    namespace: str            # "core" | "biomed" | "lakehouse-bi" (API/MCP 展示名)
    milvus_db_name: str | None = None  # Milvus DB 名；None 时由 Core 映射（core->"default", lakehouse-bi->"lakehouse_bi"）
    version: str
    depends_on: tuple[str, ...] = ()
    provides_pipelines: tuple[str, ...] = ()      # ingest pipeline names
    provides_retrievers: tuple[str, ...] = ()     # plugin-owned retrievers for specialized collections (e.g. ChemicalRetriever for eagle_chemical); Core's text+visual retrievers are always present
    provides_mcp_tools: tuple[str, ...] = ()
    provides_specialized_collections: tuple[str, ...] = ()  # e.g. ("eagle_text_biomed","eagle_chemical","eagle_medical_radiology","eagle_medical_pathology")
    resource_hints: dict[str, Any] = field(default_factory=dict)  # P1-6: e.g. {"gpu_mb": 8192, "load_order": 10}


class Plugin(Protocol):
    manifest: PluginManifest
    def register_hooks(self, bus: "HookBus") -> None: ...
    def on_load(self, ctx: "PluginContext") -> None: ...   # init model singletons + ensure_collections
    def on_unload(self) -> None: ...
    def ensure_collections(self, ctx: "PluginContext") -> None: ...  # create specialized Milvus collections on first load
```

**`eagle_rag/plugins/classifier.py`** - 内容分类器一等接口（Core 一等扩展点）：

> 前置分类器是垂类 RAG 开发的通用刚需--要把 chunk/图像路由到不同 index/编码器/模型，前置分类是必经之路。Core 提供默认分类器（基于扩展名/启发式/规则的现有实现），插件可注册更精准的分类器，**不注册则 fallback 默认**。分两个粒度：文档级（复用现有 `IngestRouteSelector`）+ chunk/asset 级（新增）。

```python
@dataclass(frozen=True)
class ClassificationDecision:
    """Standard output of every content classifier (doc-level + chunk/asset-level).

    A classifier either returns a decision (decided) or None (abstain, defer
    to the next classifier in the chain, ultimately the default classifier).
    """
    category: str                  # e.g. "chemical"/"protein"/"medical_image"/"general_text"/"ddl"
    target_collection: str         # which Milvus collection to write/query, e.g. "eagle_chemical"
    target_encoder: str            # which encoder to use, e.g. "molformer"/"qwen3-vl"/"text-embedding-v4"
    chunk_type: str                # anchor field value, e.g. "chemical"/"medical_image"/"text"
    confidence: float = 1.0        # 0.0-1.0; low confidence can trigger fallback
    fallback_used: bool = False    # True when this decision came from the default classifier
    exclusive_group: str | None = None  # P1-9: same group → at most one primary collection per chunk
    metadata: dict = field(default_factory=dict)  # e.g. {"quality": "unverified"} for medical images


class ContentClassifier(Protocol):
    """Chunk/asset-level content classifier protocol.

    Returns a ClassificationDecision when decided, None to abstain (defer to
    the next classifier in the chain). The chain's terminal fallback is the
    Core default classifier, so a plugin that does not register a classifier
    always gets sensible default routing.
    """

    def classify(self, ctx: "ClassificationContext") -> ClassificationDecision | None: ...


@dataclass(frozen=True)
class ClassificationContext:
    """Input to a classifier: the chunk/asset + surrounding context."""
    content: str | bytes           # text chunk or image bytes
    modality: str                  # "text" | "image" | "table"
    document_id: str
    kb_name: str
    plugin_namespace: str
    parent_section: str = ""       # nearest preceding text chunk path (anchor)
    source_chunk_id: str = ""      # corresponding text chunk_id (anchor)
    file_ext: str = ""             # source file extension, for doc-level hints
    extra: dict = field(default_factory=dict)
```

- **文档级分类器**：复用现有 `IngestRouteSelector`（`ingest/selectors.py:63`）+ `FallbackChain`，决定整个文件走哪个 ingest pipeline。插件通过 hook `INGEST_ROUTE_SELECTORS` 注册新 selector。
- **chunk/asset 级分类器（入库侧）**：新增 `ContentClassifier` Protocol + `ClassificationDecision`，决定单个 chunk/图像走哪个 collection/编码器。插件通过 hook `CLASSIFY_CHUNK` / `CLASSIFY_VISUAL` 注册。
- **查询侧检索路由分类器（检索侧）**：入库侧分流到多个 collection 后，查询时一段文本 query 无法在所有 collection 做 ANN（如 `text-embedding-v4` 1536d 的 query 无法在化学 embedder 空间检索）。新增 `QueryRouteClassifier` Protocol，根据 query 意图决定**查哪些 collection**：

```python
@dataclass(frozen=True)
class CollectionQueryPlan:
    collection: str
    encoder: str       # "text-embedding-v4" | "pubmedbert" | "qwen3-vl" | ...
    top_k: int = 5

@dataclass(frozen=True)
class QueryRouteDecision:
    """Which collections to query, each with its own encoder (multi-encoder plan)."""
    plans: tuple[CollectionQueryPlan, ...]
    # e.g. (CollectionQueryPlan("eagle_text","text-embedding-v4"),
    #       CollectionQueryPlan("eagle_text_biomed","pubmedbert"))


class QueryRouteClassifier(Protocol):
    """Decide which collections a query should hit.

    Returns a QueryRouteDecision when decided, None to abstain (defer to the
    next classifier). Consumed by RetrieverOrchestrator (§2.5).
    """
    def route(self, query: str, plugin_namespace: str, *, has_image: bool = False) -> QueryRouteDecision | None: ...
```

  - 插件通过 hook `CLASSIFY_QUERY` 注册。Core 默认分类器（G4）：纯文本 query → **仅** `eagle_text`（`text-embedding-v4`）；hybrid/带图 query → 加 `eagle_visual`（`qwen3-vl`）。**永不**自动查专用 collection（`eagle_text_biomed`/`eagle_chemical`/`eagle_medical_*` 等），除非领域插件 `QueryRouteClassifier` 显式加入 `plans`。
- **默认分类器**（Core 提供，作为链终端 fallback）：
  - 文档级：现有 `FallbackChain`（Prefix/ForcedMode/HttpUri/PdfForm/Extension/ContentType selectors），`default_pipeline="knowhere"`。
  - chunk/asset 级文本：默认所有文本 chunk -> `eagle_text` + `text-embedding-v4` + `chunk_type=text`（即"通用走底座"）。
  - chunk/asset 级视觉：默认所有图像 -> `eagle_visual` + `qwen3-vl` + `chunk_type=image`。
  - 查询路由（G4）：纯文本 → **仅** `eagle_text`（`text-embedding-v4`）；hybrid → 加 `eagle_visual`（`qwen3-vl`）。专用 collection **不**进入默认 plans。
- **链式组合**：复用 `FallbackChain` 语义--分类器按 priority 排序，首个非 None 决策生效；全部 abstain 则用默认分类器。支持多插件各注册自己的分类器，互不干扰。

**`eagle_rag/plugins/hookbus.py`** - 进程内 Hook 总线：

Hook 点定义在 `eagle_rag/plugins/hooks.py`（常量枚举），每个 hook 标注 **invocation mode**（见下表）。

| 方法 | 语义 | 用于 |
| --- | --- | --- |
| `invoke_first(hook, ctx)` | 按 priority 排序，**首个非 None 生效**（等同 `FallbackChain`） | `CLASSIFY_*`、`INGEST_ROUTE_SELECTORS`、`EMBED_*`（编码器选择）、`RERANK` |
| `invoke_all(hook, ctx)` | 调用全部订阅者，**合并所有非 None 结果** | `QUERY_ASSEMBLE`（多插件共同扩充 query） |
| `invoke_transform(hook, ctx)` | 链式传递：每个订阅者接收上一者输出 | `CHUNK`、`PARSE`、`UPSERT_VECTORS`（顺序改写） |

**入库全链路 hook（G26，`eagle_rag/plugins/hooks.py`）**——固定顺序，不可乱序：

| Hook | 模式 | 阶段职责 |
| --- | --- | --- |
| `PARSE` | `invoke_transform` | 解析产物改写（lakehouse DDL/YAML 等） |
| `CHUNK` | `invoke_transform` | Knowhere 节点 enrich（biomed IMRaD 段位标注等；禁止从零重切） |
| `INGEST_VISUAL_EXTRACT` | `invoke_first` | Knowhere 视觉块提取 + **四锚点默认赋值**（§4.3）；在分类前 |
| `CLASSIFY_CHUNK` / `CLASSIFY_VISUAL` | `invoke_first` | 决定 `target_collection` / `target_encoder` |
| `EMBED_TEXT` / `EMBED_VISUAL` | `invoke_first` | 编码（见下表） |
| `UPSERT_VECTORS` | `invoke_transform` | 写入 Milvus；四锚点强制保留 |

**编码 hook（G22）**：

| Hook | 模式 | 职责 |
| --- | --- | --- |
| `EMBED_TEXT` | `invoke_first` | 按 `ClassificationDecision.target_encoder` 对文本 chunk 编码；默认 Core `text-embedding-v4` |
| `EMBED_VISUAL` | `invoke_first` | 对图像/tile 按 `target_encoder` 编码；默认 Qwen3-VL；医学影像走插件 encoder |
| `UPSERT_VECTORS` | `invoke_transform` | 编码结果写入目标 collection；插件可 augment 行 metadata（四锚点强制保留） |

分类（`CLASSIFY_*`）与编码（`EMBED_*`）分离：`BiomedImageClassifier` 只产出 `ClassificationDecision`，**`IngestOrchestrator`**（§2.6）负责调用 `EncoderRegistry` + `UPSERT_VECTORS`。

- `subscribe(hook_name, fn, *, priority=0, namespace: str | None = None)` 注册回调。`namespace` 非空时 HookBus **仅**在 `ctx.plugin_namespace == namespace` 时调用该订阅者；`namespace=None` 表示全局（Core 默认 hook）。
- **禁止**用单一 `invoke()` 混用上述三种语义（原稿矛盾点已修正）。
- **异常传播（G13）**：

| Hook / 路径 | 订阅者异常 | 行为 |
| --- | --- | --- |
| `invoke_first` / `invoke_transform`（ingest、query、分类、RERANK 等） | 未捕获 | **fail-fast**：中止当前 ingest/query，向上抛结构化错误（含 `hook`/`namespace`/`plugin`） |
| `invoke_all`（`QUERY_ASSEMBLE`） | 单订阅者失败 | **per-plugin 降级**：该插件跳过，其余订阅者结果仍合并；失败记入 `PluginAudit` |
| `on_load` / `register_hooks` | 任意 | **fail-fast**：插件加载失败，进程启动失败 |

进程内插件无沙箱（§七 #15）；G13 保证单插件 bug 在 ingest/query 主路径上可快速暴露，同时 `QUERY_ASSEMBLE` 不因单插件扩写失败拖垮整次生成。

**`eagle_rag/plugins/context.py`** - `PluginContext` 契约（M1）：

```python
@dataclass(frozen=True)
class PluginContext:
    """Runtime context passed to plugin on_load / ensure_collections."""
    plugin_namespace: str          # this plugin's manifest.namespace
    default_namespace: str         # settings.plugins.default_namespace (instance-bound)
    settings: Settings
    bus: HookBus
    encoder_registry: EncoderRegistry
    collection_registry: CollectionStoreRegistry
    audit: PluginAudit             # log_decision(category, target_collection, confidence, ...)
```

- `PluginAudit.log_decision(...)` 记录分类/路由决策 telemetry（风险 #17）。
- Repository 访问**不**经 `PluginContext` 直读 PG——统一走 `eagle_rag/db/repositories/*`，由 repository 强制 `plugin_namespace`（G9）。

#### 0.1.1 HookBus 语义说明（FAQ）

**Q：分类器链（`invoke_first`）是什么？**

入库/查询时可能有多个分类器（Core 默认 + biomed 插件）。它们按 priority 排队，**谁先给出明确决策谁赢**；其余 abstain（返回 `None`）则继续下一个；全部 abstain 则走 Core 默认分类器。  
类比：医院分诊台--专科护士先看，拿不准交给全科默认流程。

**Q：`QUERY_ASSEMBLE`（`invoke_all`）是什么？**

查询**召回之后、送 LLM 生成之前**，允许**多个插件同时往 query 上下文里加料**，Core **全部采纳、合并**。  
例：biomed 插件把 `"HER2"` 扩成 `"ERBB2/HER-2/CD340"`；lakehouse 插件加业务口径片段--两者可同时生效，不是"谁先说算谁"。  
类比：做菜前多个师傅分别备料，主厨把所有料一起下锅；不是分诊台抢一个结果。

**`eagle_rag/plugins/manager.py`** - `PluginManager`：

- 加载来源（**仅同仓**）：`settings.plugins.enabled` 显式 Python 模块路径列表（如 `eagle_rag.plugins.core_defaults`、`plugins.biomed`）。**不**扫描 `entry_points`，不加载外部 pip 包。
- **启动校验（G3）**：除 `core_defaults` 外，每个 enabled 插件的 `manifest.namespace` **必须**等于 `settings.plugins.default_namespace`；否则 fail-fast。
- 生命周期：`discover() -> validate_namespace() -> resolve_deps() -> on_load() -> register_hooks() -> register_mcp_tools() -> register_celery_tasks()`。
- 全局单例 `get_plugin_manager()`（lru_cache），供 API/Celery/MCP 层调用。API 进程与 Celery worker **必须**共用同一 `enabled` 列表（部署契约）。
- **`GET /health/plugins`（M1）**：返回已加载 manifest 列表、`default_namespace`、MCP 工具名、Celery 模块；供部署探针与 worker 一致性检查。

**`eagle_rag/plugins/core_defaults.py`** - Core 自身作为一个 namespace=`"core"` 的"内置插件"，把现有 knowhere 文本流水线 + PixelRAG 视觉模态 + 四锚点桥接默认实现注册为默认 hooks。这样 Core 与插件走同一套扩展机制，无特权代码路径。

#### 0.2 配置扩展 `eagle_rag/config.py` + `settings.yaml`

新增 `PluginSettings`：

```python
class PluginSettings(BaseModel):
    enabled: list[str] = ["eagle_rag.plugins.core_defaults"]
    default_namespace: str = "core"   # 本实例绑定的 Milvus DB / 插件上下文
    allow_namespace_override: bool = False  # G19：测试环境 True；生产 False
```

`plugins.options.biomed`（`default_namespace=biomed` 时生效，G20/G27；经 `plugin_options("biomed")` 读取，**非** Core typed `BiomedPluginSettings`）：

```yaml
plugins:
  options:
    biomed:
      default_dual_text_search: false  # True = 每 query 默认 eagle_text + eagle_text_biomed
      exploratory_search_collections: []  # G27：无 scope 时额外查的专用库；默认空
      encoder_mode: auto
```

`Settings.plugins: PluginSettings`。`default_namespace` 即**部署时固定的领域**；未传 `plugin_namespace` 的 API 请求均回落到此值。

部署示例（biomed 专用实例）：

```yaml
plugins:
  enabled:
    - eagle_rag.plugins.core_defaults
    - plugins.biomed
  default_namespace: biomed
```

同仓插件路径：`plugins/biomed/__init__.py` 导出 `Plugin` 实现；**不**使用 `pyproject.toml` `entry_points`。

#### 0.3 验收

- `get_plugin_manager()` 启动时加载 core_defaults，无任何行为变化（现有 4 个 MCP 工具、3 个 Celery task、2 个 retriever 全部经 hooks 注册，但实际实现仍是原模块）。
- `PluginContext` + `HookBus.subscribe(..., namespace=)` + **G13 异常语义** + `GET /health/plugins` 就位。
- `ContentClassifier` + `QueryRouteClassifier` 接口 + Core 默认分类器就位（G4）：不注册插件分类器时，查询仅 `eagle_text`（+ hybrid 时 `eagle_visual`），行为与重构前一致。
- **`EMBED_TEXT` / `EMBED_VISUAL` / `UPSERT_VECTORS` / `INGEST_VISUAL_EXTRACT` hook 常量**就位（G22/G26 接口；M3 实现 IngestOrchestrator）。
- `ruff check` / `mypy` / 现有测试全绿。

---

### Phase 1 - Milvus Database 级领域隔离

> **隔离策略变更**：不再新增 `plugin_namespace` 标量字段、不做二维标量过滤。改为 **Milvus Database = `plugin_namespace`** 的物理隔离；每个 Database 内**至少**有一对基础 Collection（`eagle_text` + `eagle_visual`）共置所有 KB（`kb_name` 标量过滤），插件可按需**新增**领域专用 Collection（如 `eagle_text_biomed`/`eagle_chemical`）承载特殊数据。基础底座恒在，专用增量按需。
> 向后兼容：默认 Database 名 = `"default"`（等价 `core` 命名空间，即 Milvus 原生默认 DB）。

#### 1.1 隔离模型对比

| 维度 | 旧方案（已废弃） | 新方案（本设计） |
| --- | --- | --- |
| `plugin_namespace` 隔离方式 | Milvus 标量字段 + 检索时 `AND plugin_namespace==X` | **Milvus Database**（物理隔离） |
| KB 隔离方式 | 标量 `kb_name` 过滤 | 标量 `kb_name` 过滤（不变） |
| Collection 数量 | 全局 2 个（text+visual），所有 namespace 共置 | **每个 Database 内至少 2 个基础**（`eagle_text`+`eagle_visual`，所有 KB 共置）+ **0~N 个领域专用**（由插件按需新增，如 `eagle_text_biomed`/`eagle_chemical`） |
| 跨 namespace 泄漏风险 | 标量过滤 bug 可能泄漏 | 物理隔离，零泄漏 |
| 索引/HNSW 规模 | 全局混合，单索引膨胀 | 按 namespace 分库，索引独立可控 |
| 删除/备份粒度 | 按 namespace 删需标量 delete | `DROP DATABASE` 级别，干净利落 |

**为何 Database 级优于标量级**：
- 物理隔离杜绝跨命名空间数据泄漏（即使检索 filter 构造有 bug 也不会跨库命中）。
- 每个 namespace 独立 HNSW 索引，规模可控、召回质量更高、build/load 更快。
- 插件整库 drop/backup/迁移一条命令完成（`drop_database` / 快照整个 DB）。
- **基础底座恒在 + 领域专用增量**：每个 DB 内 `eagle_text`(1536d) + `eagle_visual`(2048d) 是恒在的基础底座，承载该领域所有通用文本与通用图像；插件只**新增**专用 collection（如 `eagle_text_biomed`(768d PubMedBERT)、`eagle_chemical`），由插件在 chunk 级分流决定哪块进专用库，**不替换**基础底座的维度与编码器。不同 namespace 的基础底座维度一致（1536d/2048d），专用 collection 各自不同。
- `kb_name` 标量过滤模型零改动，复用现成熟链路。

#### 1.2 Milvus 配置与客户端改造

> **G6 拍板**：`llama-index-vector-stores-milvus` **不保证**透传 `db_name`。Phase 1 **阻塞 spike** 验证；若不支持，**接受重写 text store**——与 visual store 一致，用原生 `MilvusClient(uri, db_name=...)` 薄封装 + 自建 ANN/upsert，**不**依赖 `MilvusVectorStore` 的 DB 上下文。

`MilvusSettings`（`eagle_rag/config.py:74`）新增 `db_name`：

```python
class MilvusSettings(BaseModel):
    host: str
    port: int
    db_name: str = "default"          # NEW: default Milvus database
    text_collection: str              # "eagle_text" (same name in every DB)
    visual_collection: str            # "eagle_visual" (same name in every DB)
    dim_text: int
    dim_visual: int
    visual_index_type: str
    auto_create_db: bool = True       # NEW: create DB on first use if missing
```

- `settings.yaml`：`milvus.db_name: ${MILVUS_DB_NAME:-default}`。
- Collection **名在所有 Database 中保持一致**（都叫 `eagle_text` / `eagle_visual`），隔离靠 Database 名而非 Collection 名。

**客户端绑定 Database**：

`index/milvus_visual_store.py` - `get_visual_client`（`:77`）改为按当前 namespace 解析 DB 并创建/选择：

```python
def _milvus_db_name(plugin_namespace: str | None) -> str:
    """Map plugin_namespace to a Milvus database name.

    'core' / None -> 'default' (Milvus native default DB, backward compatible).
    Other namespaces -> manifest.milvus_db_name or sanitized name
    (e.g. 'lakehouse-bi' -> 'lakehouse_bi'; Milvus 资源名仅允许字母/数字/下划线).
    """
    ns = plugin_namespace or "core"
    if ns == "core":
        return "default"
    # hyphenated API namespaces map to underscore DB names
    return ns.replace("-", "_")


```python
def ensure_database(db_name: str) -> None:
    """Ensure Milvus database exists (auto_create_db). Binding via MilvusClientPool only."""
    if db_name != "default" and get_settings().milvus.auto_create_db:
        admin = get_milvus_pool().admin_client()  # default DB, construction-time only
        existing = {d.name for d in admin.list_databases()}
        if db_name not in existing:
            admin.create_database(db_name)
```

- `ensure_collection`、`get_visual_client` 接收 `plugin_namespace`，解析为 `db_name`，经 **`MilvusClientPool.get(db_name)`** 取客户端（G17/G24）。每 `db_name` 进程单例：`MilvusClient(uri, db_name=..., alias=f"eagle-{db_name}")`；**禁止** `close()` / per-request `using_database()`。

**G17/G24 PyMilvus 连接与池化（M2 阻塞 spike）**：

- PyMilvus 官方行为：同 URI 的多个 `MilvusClient` **共享底层连接**；`close()` 一个会影响同 URI 全部客户端；`db_name=` 设定**客户端级 DB 上下文**；`alias` **不等于**独立 TCP 连接。
- **现网冲突（须迁移）**：`kb/stats._milvus_collections_for_kb`、`index/milvus_text_store._get_text_milvus_client`、`api/health.py`、`kb/health.py` 等路径 **临时 `MilvusClient` + `finally: close()`**——与 G17 直接冲突，M2 须清零。
- **`MilvusClientPool`（G24）**：`eagle_rag/index/milvus_pool.py`——`get(db_name) -> MilvusClient` 进程缓存；**无公开 `close()`**；health/stats/count 等管理操作一律走池。
- **强制约束**：lint/CI 禁止新增裸 `MilvusClient(`（store 与 health 除外池入口）；禁止 per-request `using_database()`。
- **M2 spike 验收**：FastAPI + Celery 并发读写不同 `db_name`；**health 探针与 query 热路径同进程压测**无串库、无 `close` 副作用。

`index/milvus_text_store.py` - text store 改造（G6）：

```python
def get_text_vector_store(plugin_namespace: str | None = None) -> TextVectorStore:
    """Return a (cached) text store bound to the plugin_namespace's DB.

  Prefer MilvusClient(uri, db_name=...) wrapper (same pattern as visual store).
  Fall back to MilvusVectorStore only if spike confirms db_name support.
    """
    db_name = _milvus_db_name(plugin_namespace)
    ...
```

- 文本 index（`get_text_index`）、retriever 构造时传入 `plugin_namespace` + `collection_name`（见下）。

**`get_text_index` 去全局单例（P0）**：

现状 `get_text_index()` 是**无参全局单例**，绑定单一 Qwen 1536d embed model，无法服务 biomed 的 `eagle_text_biomed`(768d PubMedBERT)。

```python
# 改为按 (db_name, collection_name) 缓存
def get_text_index(
    plugin_namespace: str | None = None,
    collection: str | None = None,  # default: settings.milvus.text_collection
) -> VectorStoreIndex:
    """Return index bound to namespace DB + collection + matching encoder."""
    ...
```

- 基础底座 `eagle_text` → Qwen `text-embedding-v4`（1536d）
- 专用 collection → 由 `EncoderRegistry` 解析（插件 `on_load` 注册 `pubmedbert` 等）
- `KnowhereGraphRetriever` **不再**内部调用无参 `get_text_index()`；由 **RetrieverOrchestrator**（§2.5）按 `QueryRouteDecision` 构造对应 index/retriever

#### 1.3 入库/检索全链路贯穿 `plugin_namespace`

- **入库**：`upsert_visual(...)` / `upsert_text_nodes(...)` 增加 `plugin_namespace` 参数（默认 `"core"`），内部解析 DB 并 `using_database` 后写入。`ingest_router` / `knowhere_parse` / `pixelrag_build` task kwargs 增加 `plugin_namespace`（默认 `"core"`），向下传给 store。**`ingest/runner.py` 派发 router task** 与 **`task_state.create_audit`** 同步传入 `plugin_namespace`（G11）。MinIO 原始文档上传 key 加 namespace 前缀（G12，见 §1.8）。`dedup.check_duplicate` / `dedup.register` 增加 `plugin_namespace`（默认 `"core"`），与 `kb_name` 一起作为去重三元组。
- **检索**：`KnowhereGraphRetriever.__init__` / `PixelRAGVisualRetriever.__init__` 增加 `plugin_namespace`（默认 `"core"`），取对应 DB 的 vector store / client。`_build_filters`（`knowhere_graph_retriever.py:104`）与 `_build_search_expr`（`milvus_visual_store.py:336`）**不**新增 `plugin_namespace` 过滤条件（DB 已隔离）。
- **API**：`QueryRequest`/`SearchRequest`/`ingest` API 增加可选 `plugin_namespace`（默认 `settings.plugins.default_namespace`）。**单实例模型**：运行时通常不传，由部署配置固定 DB；显式传参仅用于测试或多租户网关场景。`scope_filter` **不**扩展 `plugin_namespaces`（一次查询只查当前实例的单一 DB；**永不做跨 DB fan-out**；同一 DB 内可跨 collection）。**Session 创建时持久化 `plugin_namespace`** 到 `sessions` 表，恢复时读取并下推到检索。
- **所有 `kb_name or settings.kb_name` 回退点旁**，对称加 `plugin_namespace or settings.plugins.default_namespace`（含 `dedup._resolve_kb`、`registry._resolve_kb`、`milvus_visual_store._build_row` 等）。

#### 1.4 PostgreSQL（仅元数据，不改隔离模型）

> **G9/G10 拍板**：新增 `eagle_rag/db/repositories/` 层；**所有** PG 查询/写入经 repository，**强制**传入 `plugin_namespace`（默认 `settings.plugins.default_namespace`）。禁止 handler/store 直写裸 SQL 且漏 namespace。

- `documents` 表加 `plugin_namespace: str = Field(default="core")` + 索引（用于元数据查询/列表过滤，如 `/documents?plugin_namespace=biomed`）。`document_id` **保持全局唯一 PK**（UUID 生成，不改为复合 PK）。ingest **终态成功**时写入 **`extra["collections_used"]`**（G28/G30）。PG 不做 Milvus 级物理隔离，但须 **DB 层硬约束防串线（G18）**：
  - 子表 `images`、`document_keywords` 等：FK 升级为 `(document_id, plugin_namespace) → documents(document_id, plugin_namespace)`，或保留 `document_id` FK 且子表 **UNIQUE(document_id, plugin_namespace)** + repository 强制双边 namespace 条件。
  - **禁止**仅 `WHERE document_id = %s` 跨 namespace JOIN；Alembic 迁移须含 FK/约束。
- `document_keywords` 同步加 `plugin_namespace` 字段 + 复合索引 `(plugin_namespace, kb_name, keyword)`。
- **`resolve_tags_to_document_ids`**（`index/tag_catalog.py`）签名扩展 `plugin_namespace: str`，WHERE 子句 **必须**含 `plugin_namespace = %s`（G10：同名 KB 不串 tag）。
- **`scope_filter` 标签解析**（`router_engine._resolve_scope_filter`）：调用 tag 解析时传入 session/API 的 `plugin_namespace`。
- **`document_dedup` 表主键扩展**：现 PK 为 `(sha256, kb_name)`（`db/models/dedup.py:22-23`），改为 `(sha256, kb_name, plugin_namespace)`。`check_duplicate`（`storage/dedup.py:82`）/`register`（`:92`，`ON CONFLICT`）签名加 `plugin_namespace`。**否则同一文件（同 sha256）先 ingest 到 core 的 `default` KB，再 ingest 到 biomed 的 `default` KB 时，dedup 误命中、biomed 侧被跳过**--两个 namespace 物理隔离了 Milvus，但 dedup 表是全局共享 PG 表，必须加 namespace 维度。
- **`knowledge_bases` 表主键扩展**：现 PK 为 `kb_name`（单一主键，`db/models/knowledge_bases.py:19`），改为 `(kb_name, plugin_namespace)`。新增 **`collections_used: list[str]`**（JSONB，默认 `[]`，G28/G23）。`kb_exists_sync`（`kb/registry.py:209`）查询加 `plugin_namespace` 条件。**否则 `kb_name="default"` 在 core 和 biomed 两个 namespace 无法各自存在**--KB 注册在 namespace 层就泄漏。
- **`sessions` 表加 `plugin_namespace`**：`sessions` 表已有 `kb_name` 列（`db/models/sessions.py`），加 `plugin_namespace: str = Field(default="core")`。session 创建时持久化 `plugin_namespace`，恢复时读取--**否则 biomed namespace 创建的 session 恢复时 namespace 丢失，查询落到默认 core**。`messages` 表同理加 `plugin_namespace`。
- **运维/审计表（G11）**——多实例共用同一 PostgreSQL 时，以下表**必须**加 `plugin_namespace` 并经 repository 强制过滤：
  - **`task_audit`**：`create_audit` / `list_audits` / `get_audit` 签名扩展；`list_audits` 默认按实例 `default_namespace` 过滤。
  - **`notifications`**：`create_notification_sync` / `list_notifications` 加 `plugin_namespace`（与 `kb_name` 并列）。
  - **`mcp_call_log`**：写入与 `list_recent_mcp_calls` 查询带 `plugin_namespace`（从实例 `default_namespace` 或 MCP 请求上下文注入）。
- Alembic 迁移回填历史行 `plugin_namespace='core'`（含 `documents`/`document_keywords`/`document_dedup`/`knowledge_bases`/`sessions`/`messages`/`images`/`task_audit`/`notifications`/`mcp_call_log`）。
- KB 生命周期（`kb/lifecycle.py` 的级联删除/rebuild）按 `(plugin_namespace, kb_name)` 二元组定位，删 Milvus 时调 `delete(predicate=kb_name)` 而非 drop DB（DB 内多 KB 共置，不能整库 drop）。**级联删除须扇出 namespace 内全部 collection**（基础底座 + `PluginManager` 提供的 `provides_specialized_collections`）（P1-16）。
- **`sessions` / `messages` repository（G33）**：除表列 `plugin_namespace` 外，`sessions/store.py` 的 `create_session` / `get_session` / `list_sessions` / `set_session_scope_filter` **经 repository 强制**注入与过滤 `plugin_namespace`（默认 `settings.plugins.default_namespace`）。**禁止** `list_sessions` 仅按 `kb_name` 过滤而漏 namespace——多实例共用 PG 时会列出他域 session 元数据。

#### 1.5 数据迁移（现有 `default` DB）

- 现有 `eagle_text`/`eagle_visual` 已在 Milvus `default` DB，等价于 `plugin_namespace="core"`。**无需迁移向量数据**。
- 仅需：① PG 加列回填 `plugin_namespace='core'`；② 代码默认 namespace=`"core"` -> DB=`"default"`，行为零变化。
- 后续新 namespace（biomed/lakehouse-bi）首次入库时 `auto_create_db` 自动建库（`lakehouse-bi` → Milvus DB `lakehouse_bi`）。

#### 1.6 验收

- 不传 `plugin_namespace` 时：DB=`"default"`，行为与现在完全一致（现有测试全绿）。
- 传 `plugin_namespace="biomed"` 时：写入落到 Milvus `biomed` DB 的基础底座 `eagle_text`/`eagle_visual` + 专用 collection（如 `eagle_text_biomed`）；core 的 `default` DB 检索**物理上无法命中** biomed 数据（零泄漏）。
- 同一文件（同 sha256）分别 ingest 到 core 和 biomed 的同名 KB，**dedup 不误命中**（PK 含 `plugin_namespace`）。
- 同名 `kb_name` 在 core 和 biomed 两个 namespace 各自注册成功（`knowledge_bases` PK 含 `plugin_namespace`）。
- biomed namespace 创建的 session 恢复后，`plugin_namespace` 正确读取，查询落到 `biomed` DB。
- 同一 DB 内多个 `kb_name` 仍按标量过滤隔离。
- KB 级联删除按 `(plugin_namespace, kb_name)` 精确删除，不影响同 DB 其他 KB。
- `auto_create_db=True` 时新 namespace 首次写入自动建库成功。
- **images/MinIO（tile + 原始文档）/cache** 按 `plugin_namespace` 隔离（§1.8，G12）。
- **`task_audit` / `notifications` / `mcp_call_log`** 按 `plugin_namespace` 隔离（§1.4，G11）。
- **G18**：子表 FK 带 `plugin_namespace`；跨 namespace 按 `document_id` 单独 JOIN 失败（约束或测试覆盖）。
- **G19**：生产配置下传入错误 `plugin_namespace` 返回 403；repository 不读请求 namespace。
- **G25/G28/G30**：ingest 成功后 `documents.extra["collections_used"]` 与 `knowledge_bases.collections_used` 正确更新；失败 ingest 不污染 catalog。
- **G29**：scope 仅 tags 时 scope-aware 并集正确。
- **G31**：rebuild 后 KB `collections_used` 与 Milvus 一致。
- **G33**：`list_sessions` 不返回他域 session；`create_session` 自动写入 `plugin_namespace`。

#### 1.7 产品语义：单域部署 + KB 选择（API + Frontend）

> **G1 拍板**：**单域部署**——`plugin_namespace` 由实例部署固定，用户只选 KB。**G19**：生产环境 repository **只信任** `settings.plugins.default_namespace`，**忽略**请求体中的 `plugin_namespace`；若客户端显式传入且与 `default_namespace` 不一致 → **HTTP 403**（非 warn）。测试/集成环境可设 `settings.plugins.allow_namespace_override: true` 允许覆盖。

**交互模型**：

```
1. 领域（plugin_namespace）= 部署固定，UI 只读展示（如 AppBar 标签 "Biomed"）
        ↓
2. KB 选择（该领域 DB 内的 kb_name 列表）
   default | finance | pubmed-2025 | ...
        ↓
3. 查询 / 入库 / Session 均携带 (plugin_namespace, kb_name)
   — plugin_namespace 通常由后端默认注入，前端不必切换
```

**API 变更要点**：

| 端点 | 变更 |
| --- | --- |
| `GET/POST /knowledge-bases` | 默认 `plugin_namespace=settings.plugins.default_namespace`；列表/创建按 `(plugin_namespace, kb_name)` |
| `POST /ingest` / MCP `core_ingest` | `kb_name` 必填或默认；`plugin_namespace` 生产忽略（G19），测试可 override |
| `POST /query` / `/search` | Session 恢复 `plugin_namespace`；`scope_filter.kb_names` 仅在同 DB 内 OR；错误 namespace → 403 |
| `GET /documents` | 默认带 `plugin_namespace` 过滤 + 可选 `kb_name` |

**Frontend 变更要点**（M2.5，**在 G1 单域模型拍板后**实施）：

- **不实现**领域切换器；AppBar **只读展示**当前部署领域（i18n：`domain` = `plugin_namespace` 展示名）。
- 现有 KB 模块文案 "namespace" 改为 "knowledge base"。
- QA `scopeStore`：`kb_names` 在当前实例领域内有效；**无**跨领域切换清空逻辑。
- `TargetKBSelector` / `CreateKBDrawer`：创建 KB 时绑定实例 `default_namespace`（由后端默认，前端可不传）。
- **G27 全库探索性检索提示**（biomed 实例）：QA 页 scope 为空时，展示只读说明——「默认检索通用文本库；生物医学专用库需 query 含实体、或限定文档/KB scope」。文案走 i18n（`qa.scope.exploratoryHint`）。可选后端配置 `settings.plugins.options.biomed.exploratory_search_collections: list[str]`（默认 `[]`）允许高级部署放宽无 scope 时的 collection 扇出。

**验收**：

- biomed 实例 UI 仅展示 biomed 领域下的 KB；**无**领域切换入口。
- Session 恢复后 `plugin_namespace` + `kb_name` 均正确，查询落到预期 DB。

#### 1.8 对象存储隔离：images + MinIO + cache（P0，G12 已拍板）

Milvus DB 隔离后，若 images/MinIO 仍全局共享，会出现：**向量在 biomed DB、tile 文件却在 core 路径**，或 `image_id` / 原始文档跨 namespace 碰撞。

**PostgreSQL `images` 表**：

- 新增 `plugin_namespace: str = Field(default="core")` + 索引。
- 查询/列表默认带 `plugin_namespace` 过滤（与 `kb_name` 并列）。

**MinIO object key**——**tile 与原始文档均加 namespace 前缀（G12）**：

```python
db_ns = plugin_namespace or settings.plugins.default_namespace

# Tile（images/store.py store_tile）
# 旧: {document_id}/{image_id}.png
# 新: {plugin_namespace}/{document_id}/{image_id}.png
tile_key = f"{db_ns}/{document_id}/{image_id}.png"

# 原始文档（ingest/runner.py 上传 MinIO）
# 旧: {source_type}/{document_id}/{name}
# 新: {plugin_namespace}/{source_type}/{document_id}/{name}
source_key = f"{db_ns}/{source_type}/{document_id}/{name}"
```

- `store_tile(...)` / `get_image_bytes` / `list_images_by_document` 全链路增加 `plugin_namespace` 参数。
- **`ingest/runner.py`**：`upload_file` / `upload_bytes` 的 `object_key` 构造改为 `source_key` 格式；`send_task_with_trace` kwargs 向下传递 `plugin_namespace`。
- Celery ingest task kwargs 向下传递（与 Milvus 写入对称）。

**MCP cache**（`mcp_cache.cache_key`）：

- `cache_key(...)` 增加 `plugin_namespace` 维度，避免 core/biomed 实例共用 Redis 时误命中。

**Attachments 懒解析缓存（P1-12）**：

- `attachments/parser.py` 解析缓存 key 增加 `plugin_namespace`（与 MCP cache、MinIO 对称）。
- `query` / `search` 的 `image_base64` 路径在 cache lookup 时带实例 `default_namespace`。

**验收（并入 §1.6）**：

- 同 `document_id` + 同 `image_id` 在 core 与 biomed 各 ingest 一次，MinIO tile key 不碰撞，PG `images` 行按 `plugin_namespace` 独立。
- 同 `document_id` 在 core 与 biomed 各 ingest 同名文件，**原始文档 MinIO key 不覆盖**（G12）。
- MCP `retrieve_visual` cache 在切换 `plugin_namespace` 后不返回他域结果。

#### 1.9 Collection catalog 与 KB 可观测性（G23/G25/G28/G29/G30/G31）

**G28 catalog 存储（v1，不新建表）**：

- **文档级**：`documents.extra["collections_used"]: list[str]`——ingest **终态成功**（G30）后合并更新，如 `["eagle_text","eagle_text_biomed"]`。
- **KB 级（G23）**：`knowledge_bases.collections_used: list[str]`（JSON/JSONB 列）——该 KB 下**所有成功文档** `collections_used` 的**并集**；每次文档 ingest 成功时 `UPDATE ... SET collections_used = collections_used | :new`（集合并集）。
- 文档数 >1 万且 catalog 查询成为热点时，再拆 `document_collection_index` 表（P2 迭代）；v1 不引入。

**G30 catalog 提交时机**：

- **仅在 ingest 终态成功**更新 catalog：`documents.status=success` 且 `IngestOrchestrator` 对该文档**全部 chunk** 完成 upsert 后，原子更新 `documents.extra["collections_used"]` 与 `knowledge_bases.collections_used`。
- **不在** per-chunk 热路径更新 KB 级并集；**不在** Celery 中间态（`pending`/`processing`）或失败终态写入 catalog。
- 与 `dedup.register` 同级回调（router 链全绿后）；部分成功（如 text 成功、visual 失败）**不**写入专用 collection 到 catalog。

**G31 KB 生命周期与 catalog 维护**：

- **`delete_kb`**：删除 `knowledge_bases` 行（`collections_used` 随行删除）；Milvus 扇出删除（P1-16）。
- **`start_rebuild` / 全量 re-ingest**：**清空** `knowledge_bases.collections_used = []`；每文档 ingest 成功后按 G30 重算并集。
- **单文档删除**（若支持）：从 KB 并集 **重算**（`SELECT` 剩余文档 `extra.collections_used` 并集）或 defer 到下次 rebuild（v1 推荐重算，避免 G23 陈旧）。

**G23 scope-aware 数据源**：

| scope 维度 | catalog 查询 |
| --- | --- |
| `scope_filter.document_ids` | 各 `documents.extra["collections_used"]` 并集 |
| `scope_filter.kb_names` | 各 `knowledge_bases.collections_used` 并集（**G23 关键**：UI 常只选 KB） |
| `scope_filter.tags` | **G29**：`resolve_tags_to_document_ids(plugin_namespace, tags)` → `document_ids` → 各行 `extra["collections_used"]` 并集（与 document scope 同路径） |
| 无 scope | 不查 catalog；走 G20/G15 规则路由 |

**G25 KB stats / API 改造**（`kb/stats.py`、`api/knowledge_bases.py`）：

- `_milvus_collections_for_kb` / `get_collections`：扇出 **基础底座** + `PluginManager.get_specialized_collections(plugin_namespace)`；经 `MilvusClientPool.get(db_name)` 按 `kb_name` 标量 `query` 各 collection 行数（**禁止**临时 client + `close()`）。
- `GET /knowledge-bases` / `GET /knowledge-bases/{kb}` 默认 `plugin_namespace=settings.plugins.default_namespace`（G19）；`collections` 字段含专用库名与计数。
- `stats.get_kb_stats` 的 `graph_nodes` / `visual_slices` 按 namespace 内全 collection 聚合（不只 `eagle_text`/`eagle_visual`）。

**验收（并入 §1.6）**：

- biomed KB ingest 含 `eagle_text_biomed` chunk 后，`knowledge_bases.collections_used` 含 `eagle_text_biomed`；`GET .../collections` 可见。
- scope 仅 `kb_names` 时，G21 scope-aware 能强制加入专用 collection plans。
- scope 仅 `tags` 时（G29），tag 解析到的文档 catalog 能触发专用库 plans。
- ingest 失败文档**不**更新 KB `collections_used`；rebuild 后 catalog 与 Milvus 一致（G31）。

---

### Phase 2 - `IngestPipeline` 协议 + 注册表化派发

#### 2.1 新增 `IngestPipeline` Protocol（`eagle_rag/plugins/pipeline.py`）

```python
class IngestPipeline(Protocol):
    name: str                                   # "knowhere" | "pixelrag" | ...
    def parse(self, ctx: ParseContext) -> ParseResult: ...
    def to_nodes(self, parse_result, ctx) -> list[TextNode]: ...
    def celery_task_name(self) -> str: ...
    def queue(self) -> str: ...
```

统一返回类型为 `ParseResult`（dataclass，兼容现 Knowhere `ParseResult` 鸭子类型 + PixelRAG tile 列表）。

#### 2.2 重构现有两个 adapter 为 pipeline 实现

- `ingest/knowhere_adapter.py`：抽 `KnowherePipeline` 类（`name="knowhere"`），`parse`/`to_nodes` 包装现有 `parse_with_knowhere_sdk`/`chunks_to_text_nodes`/`sections_to_text_nodes`。Celery task `knowhere_parse` 保留但内部委托给 pipeline。
- `ingest/pixelrag_adapter.py`：抽 `PixelragPipeline`（`name="pixelrag"`），`parse` 返回 tile 描述，`to_nodes` 产出 visual 记录。
- 两者通过 `core_defaults` 插件注册到 `PluginManager.pipeline_registry`。

#### 2.3 路由派发改为注册表查询

- `ingest/router.py`：`_KNOWHERE_TASK`/`_PIXELRAG_TASK` 硬编码常量（`:314-319`）替换为 `manager.get_pipeline(name).celery_task_name()`。`ingest_router` task 的 `app.send_task`（`:409-423`）改为遍历 `route()` 返回的 pipeline 名列表查注册表派发。
- `FallbackChain` 仍是路由决策核心；`route()` 返回的 pipeline 名现在可由插件注入新 selector 扩展（如 biomed 的 `BiomedFormatSelector` 仍路由到 **`knowhere`** pipeline，领域逻辑走 `PARSE`/`CHUNK` hooks，见 G7）。

#### 2.4 Celery task 注册动态化

- `tasks/celery_app.py`：`include=` 静态列表（`:28-33`）改为 `manager.collect_celery_modules()` 动态生成；插件通过 hook `CELERY_TASKS` 暴露其 task 模块路径。
- `celery_app.autodiscover_tasks()`（`:81` no-op）实现为遍历插件 task 模块。

#### 2.5 验收

- 现有 knowhere/pixelrag 流水线行为不变（端到端 ingest 一篇 PDF）。
- 新增单测：注册一个 stub pipeline，`route()` 能返回其名，`ingest_router` 能派发到其 task。

---

### Phase 2.6 - IngestOrchestrator（多 encoder 入库接线，M3，G22）

> **对称 RetrieverOrchestrator（§2.5）**：检索侧已有「分类决策 → 多路 ANN」；入库侧缺「`ClassificationDecision` → 多 encoder 编码 → 多 collection upsert」。现状 adapter 内硬编码 Qwen embed，无法承载 biomed 医学影像 / PubMedBERT 等专用 encoder。

#### 2.6.1 组件设计

**`eagle_rag/plugins/ingest_orchestrator.py`**：

```python
class IngestOrchestrator:
    def embed_and_upsert(
        self,
        chunk: TextNode | VisualChunk,
        decision: ClassificationDecision,
        *,
        plugin_namespace: str,
        kb_name: str,
        document_id: str,
    ) -> str:
        """CLASSIFY → EMBED_* hook → EncoderRegistry → UPSERT_VECTORS → node_id."""
```

- 流程（**G26 固定顺序**）：`PARSE` → `CHUNK` → `INGEST_VISUAL_EXTRACT` → `CLASSIFY_CHUNK` / `CLASSIFY_VISUAL`（`invoke_first`）→ `IngestOrchestrator.embed_and_upsert` → `EMBED_TEXT` / `EMBED_VISUAL` → `UPSERT_VECTORS` → 目标 collection。
- ingest **终态成功**时更新 **G28/G30 catalog**：`documents.status=success` 且全 chunk upsert 后，合并 `documents.extra["collections_used"]` 并 `knowledge_bases.collections_used` 并集（与 `dedup.register` 同级，**不在** per-chunk 或失败态更新）。
- 启动校验：`encoder.dim == collection.dim`（与 P0-7 共用 `EncoderRegistry`）。
- 四锚点（`parent_section`/`source_chunk_id`/`chunk_type`/`content_summary`）在 `UPSERT_VECTORS` 链中**强制保留**，插件 augment 不得剥离。
- `knowhere_parse` / `knowhere_visual_chunks` / `pixelrag_build` 在 chunk 产出后委托 `IngestOrchestrator`，替换 adapter 内直接 `upsert_text_nodes` / `upsert_visual` 硬编码路径。

#### 2.6.2 验收

- core 实例：无插件分类器时，行为与现 ingest 一致（全进 `eagle_text` / `eagle_visual` + Qwen encoder）。
- stub 插件注册第二 encoder + collection，`IngestOrchestrator` 能按 `ClassificationDecision` 写入正确库。
- `EMBED_VISUAL` hook 可被 biomed 插件 override（MedImageInsight / UNI 2），默认仍走 Core Qwen3-VL。

---

### Phase 2.5 - RetrieverOrchestrator（多 collection 检索接线，M3.5）

> **这是什么？** 一句话：**把 `QueryRouteClassifier` 的"查哪些库"决策，真正接到 Milvus 查询代码上**。  
> 现状 `EagleRouterQueryEngine._fetch_nodes` 写死只调 `KnowhereGraphRetriever` + `PixelRAGVisualRetriever` 两个 retriever，各查 `eagle_text` / `eagle_visual`。biomed 加了 `eagle_text_biomed`、`eagle_chemical` 等专用 collection 后，**没有组件负责"按决策去查这些库"**——这就是要补的线。

#### 2.5.1 问题用例子说明

用户问："HER2 信号通路机制"（biomed 实例）

1. `BiomedQueryRouteClassifier` 决策（**G15/G20**：`HER2` UMLS 命中）→ 查 `eagle_text`（Qwen 1536d）**和** `eagle_text_biomed`（PubMedBERT 768d）；若无 UMLS 且无 scope catalog，则**仅** `eagle_text`
2. **RetrieverOrchestrator** 执行：
   - 用 `text-embedding-v4` 编码 query → ANN 查 `eagle_text` → top_k₁
   - 用 `pubmedbert` 编码 query → ANN 查 `eagle_text_biomed` → top_k₂
   - （若有视觉路由）查 `eagle_visual` / `eagle_chemical` / `eagle_medical_*` …
3. 分路结果各路经 `RERANK` hook 重排后，由 **`RerankFusion` 以 RRF 合并**（G8；**禁止**把 1536d cosine 与 768d cosine 直接比大小）
4. 合并后的 `NodeWithScore` 列表交给 `EagleMultimodalQueryEngine` 生成

没有 RetrieverOrchestrator，步骤 2 不存在——分类器决策是空文。

#### 2.5.2 组件设计

**`eagle_rag/plugins/retriever_orchestrator.py`**：

```python
@dataclass(frozen=True)
class CollectionQueryPlan:
    collection: str
    encoder: str          # "text-embedding-v4" | "pubmedbert" | "qwen3-vl" | ...
    top_k: int

@dataclass(frozen=True)
class QueryRouteDecision:
    plans: tuple[CollectionQueryPlan, ...]  # 取代单一 query_encoder 字段


class RetrieverOrchestrator:
  def retrieve(
      self,
      query: str,
      *,
      plugin_namespace: str,
      route_decision: QueryRouteDecision,
      kb_name: str | None,
      scope_filter: dict | None,
      query_image_bytes: bytes | None = None,
  ) -> list[NodeWithScore]:
      """For each plan: encode query -> ANN on collection -> merge via RERANK hook."""
```

- `EncoderRegistry`（插件 `on_load` 注册 encoder 名 → 实例）：`pubmedbert`、`medimageinsight`、`uni2` 等。启动时校验 **encoder.dim == collection.dim**（P0-7）。
- `CollectionStoreRegistry`：`(db_name, collection)` → vector store / retriever（复用 §1.2 客户端池）。
- **分路失败策略（G14）**：对每个 `CollectionQueryPlan` 独立 try/except；单路 ANN/编码失败时**跳过该路**、记 `PluginAudit.log_decision(..., error=...)` + warn 日志，**不**因一路失败中止整次 query。成功路继续进入分路 RERANK → RRF。若**全部** plan 失败，返回空列表（与现 `_fetch_nodes` per-retriever 降级风格一致）。
- **RRF 规格（G8 细化）**：`RerankFusion.merge_rrf(plans_results, *, k=60)`——`k` 默认 60（`settings.router.rrf_k` 可配）；各路 `top_k` 可不等，按各路内 rank 参与 RRF；**0 命中路不参与**融合（不产生虚假 rank）。分路 RERANK：`RERANK` hook 按 `collection` 分流调用（Orchestrator 传入 `collection` 上下文），各路 rerank 后再 RRF。
- **RRF 后去重（G32）**：`RerankFusion.dedupe_cross_collection(nodes)`——双写（P1-9）或边界抖动导致同一逻辑块出现在多 collection 时，按 **`source_chunk_id`（非空优先）** 或 **`(document_id, path)`** 折叠为一条，保留 RRF 排名更高者；记入 `PluginAudit`（`reason="rrf_dedupe"`）供监控双写率。
- `EagleRouterQueryEngine._fetch_nodes` **委托**给 `RetrieverOrchestrator.retrieve`；Core 默认 `QueryRouteDecision` 等价于现行为（只查 `eagle_text` + 可选 `eagle_visual`）。

#### 2.5.2.1 查询流水线（M3.5 ADR，拍板）

`RouteSelector`（模态：text/visual/hybrid）与 `QueryRouteClassifier`（collection plans）**分层**执行：

```
User Query
    │
    ▼
RouteSelector (现有 router/selectors.py FallbackChain)
    │  → RouteDecision.mode ∈ {text, visual, hybrid}
    ▼
QueryRouteClassifier (CLASSIFY_QUERY, invoke_first)
    │  → QueryRouteDecision.plans（受 mode 约束：
    │     mode=text  → 仅文本 plans；mode=visual → 仅视觉 plans）
    ▼
Scope-aware 并集（G21/G23）— 在 plans 确定后合并 catalog
    ▼
RetrieverOrchestrator.retrieve (multi-ANN per plan)
    ▼
RERANK hook (per-plan reranker)
    ▼
RerankFusion.merge_rrf (G8)
    ▼
RerankFusion.dedupe_cross_collection (G32)
    ▼
QUERY_ASSEMBLE (invoke_all)
    ▼
EagleMultimodalQueryEngine.generate
```

- `RouteContext` / `QueryRouteClassifier.route()` 增加 `route_mode: str` 入参（来自 `RouteDecision.mode`）。
- Core 默认 classifier（G4）在 `route_mode=text` 时 plans 仅含 `eagle_text`；`hybrid` 时加 `eagle_visual`。
- **SSE `step` 事件（M3.5）**：`POST /query/stream` 与 `POST /search/stream` 的 `route` step payload 增加 **`collection_plans`**（`QueryRouteDecision.plans` 序列化：collection、encoder、top_k）与 **`scope_aware_union`** 标记，便于前端/Agent 调试多 collection 路由；`recall` step 可含各路命中数（不含 token 流变更）。

#### 2.5.2.2 Scope-aware 查询路由（G21 + G23 + G28）

入库 per-chunk 分类（`CLASSIFY_CHUNK`）与查询 `QueryRouteClassifier` 是**双轨**决策。若 chunk 仅写入 `eagle_text_biomed` 而 query 侧 abstain 回落 G4，将**永远查不到**专用库向量。

**闭合契约**：

1. **Catalog 存储（G28/G30）**：`documents.extra["collections_used"]` + `knowledge_bases.collections_used`（§1.9）；**仅 ingest 终态成功**后由 `IngestOrchestrator` 路径更新。
2. **`QueryRouteClassifier.route()`** 接收 `scope_document_ids` / `scope_kb_names` / **`scope_tags`**；插件 classifier 决策后，Core 路由层执行 **scope-aware 并集**：
   - **document scope**：并集各 `documents.extra["collections_used"]` → 强制加入对应 `plans`。
   - **KB scope（G23）**：并集各 `knowledge_bases.collections_used`（`WHERE plugin_namespace AND kb_name IN ...`）→ 强制加入对应 `plans`。**UI 常只选 KB，此路径为默认闭合方式。**
   - **tags scope（G29）**：`resolve_tags_to_document_ids(plugin_namespace, tags)` → `document_ids` → 并集各文档 `extra["collections_used"]` → 强制加入对应 `plans`（与 document scope **同逻辑**，经 tag 间接解析）。
   - 例：scope `kb_names=["pubmed-2025"]` 且该 KB `collections_used` 含 `eagle_text_biomed` → 强制加 `eagle_text_biomed`（即使 query 无 UMLS）。
3. **无 scope 全库 query（G20/G27）**：仅 UMLS/规则命中才加专用库；**不**读 KB catalog 全扇出（性能约束）。产品须明示（§1.7 G27）；可选 `biomed.exploratory_search_collections` 放宽。
4. 决策记入 `PluginAudit.log_decision(..., reason="scope_aware_union"|"kb_catalog_union")`。

ADR-006 固化 ingest–query 契约（见 Phase 7）。

#### 2.5.3 与 HookBus 的分工

| 阶段 | 组件 | Hook |
| --- | --- | --- |
| 决定查哪些 collection | `QueryRouteClassifier` | `CLASSIFY_QUERY`（`invoke_first`） |
| 执行多路 ANN | `RetrieverOrchestrator` | 无（Core 编排） |
| 分路重排 + 合并 | `RerankFusion` | `RERANK`（`invoke_first`，按 collection 分流）→ **RRF 合并**（G8）→ **跨 collection dedupe**（G32） |
| 扩充 query 上下文 | 插件 | `QUERY_ASSEMBLE`（`invoke_all`） |

#### 2.5.4 验收

- core 实例：不传插件分类器时，Orchestrator 行为与现 `KnowhereGraphRetriever`+`PixelRAGVisualRetriever` 一致。
- stub 插件注册第二 text collection + encoder，Orchestrator 能按 `QueryRouteDecision.plans` 双路 ANN、分路 RERANK、**RRF 合并**。
- **G14**：stub 一路 ANN 抛错时，另一路仍返回结果；`PluginAudit` 含失败路记录。
- biomed 集成测试（M6）依赖本 Phase 就位。
- **G23/G29**：scope 仅 `kb_names` 或仅 `tags` 时，catalog 触发专用库 plans。
- **G32**：stub 双写场景下 RRF 后节点数 dedupe，上下文无重复 `source_chunk_id`。

---

### Phase 3 - MCP 工具注册表（消除手工同步）

#### 3.1 新增 `eagle_rag/plugins/mcp_registry.py`

```python
def _mcp_tool_name(namespace: str, name: str) -> str:
    """G2: underscore separator; hyphenated namespaces → underscore (lakehouse-bi → lakehouse_bi)."""
    ns = namespace.replace("-", "_")
    return f"{ns}_{name}"

def register_mcp_tool(*, namespace: str, name: str, description: str,
                      parameters: dict, required: list[str]):
    tool_name = _mcp_tool_name(namespace, name)
    def decorator(fn):
        mcp.tool(name=tool_name, description=description)(fn)
        TOOL_DEFINITIONS.append({
            "name": tool_name,
            "description": description,
            "parameters": parameters, "required": required,
        })
        return fn
    return decorator
```

- `core_defaults` 插件用此装饰器重写现有 4 个工具（`core_ingest`/`core_query`/`core_retrieve_text`/`core_retrieve_visual`），`mcp_server.py:83-232` 的手工 `TOOL_DEFINITIONS` 删除，改为 `from eagle_rag.plugins.mcp_registry import TOOL_DEFINITIONS`。
- 工具内部实现不变（仍 `resilient_call` + `with_metrics` + 懒导入）。
- **应用启动顺序（FastMCP）**：`PluginManager.load_all()` → `register_mcp_tools()` → `register_core_hooks()` **完成后**再挂载/启动 FastMCP（`mcp.run()` / ASGI lifespan）。工具须在 server 启动前注册，否则 `/mcp` 不可见插件工具。
- **Breaking change（已拍板）**：旧工具名（`ingest`/`query`/…）**不保留** alias；外部 Agent 迁移到 `core_*` 前缀（G2）。Phase 7 更新 MCP 集成文档与 changelog。

#### 3.2 插件工具注册（G3）

- `PluginManager.register_mcp_tools()` **仅**为 `core_defaults` + `manifest.namespace == default_namespace` 的插件注册工具。
- `enabled` 与 `default_namespace` 启动联动校验（§0.1）；配置错误 fail-fast。
- `/mcp/tools` REST 路由自动反映**本实例**已注册工具。

#### 3.3 验收

- `/mcp/tools` 返回 Core 工具集，名称为 `core_ingest`/`core_query`/`core_retrieve_text`/`core_retrieve_visual`（**breaking change**，无旧名）。
- 单测：`default_namespace=biomed` 时仅 `core_*` + `biomed_*` 可见；`enabled` 含异 namespace 插件时启动失败。

---

### Phase 4 - 视觉模态归 Core，四锚点桥接重构为可替换默认行为

> **修正**：原方案把 PixelRAG 视觉模态与四锚点桥接混为一个可禁用的 `fusion` 插件，犯了两个错：① 把模态（render+Qwen3-VL+`eagle_visual`+`PixelRAGVisualRetriever`）当"融合"，命名与语义错位；② 把"禁用视觉=纯文本 RAG"当验收卖点，等于把 EagleRAG 退回成它要取代的东西。
> **本 Phase 重切边界**：PixelRAG 视觉模态归 Core 一等公民，不可裁剪；仅"四锚点桥接逻辑"重构为可替换的 Core 默认行为（非独立可禁用插件）。

#### 4.0 Knowhere 与 Eagle 职责边界（G16，已拍板）

Knowhere 自带 Agentic RAG（`WorkflowOrchestrator`、`RetrievalAgent`、3-channel BM25 + RRF、`doc_nav` 树导航）。Eagle **不重复实现** Knowhere 侧 agentic 编排。

| 层 | 职责 | Eagle 是否调用 |
| --- | --- | --- |
| **Knowhere** | 文档 parse、`doc_nav.sections` 骨架、`ChunkPayload` 产出、（可选）Knowhere 自有 Agentic 检索服务 | **仅 parse**（`knowhere.mode` api/parser）；**不**在 query 热路径调 `RetrievalAgent` / `WorkflowOrchestrator` |
| **Eagle Core** | Milvus 多 collection 写入/检索、多 encoder、四锚点桥接、`RetrieverOrchestrator` + RRF、MCP/API | query/search 热路径 |
| **Eagle 父文档检索（G5）** | Milvus `eagle_text` 两阶段（`section_summary` → `path` 前缀下钻） | 复用 PG `doc_nav` 骨架，**非** Knowhere Navigation BFS |
| **Eagle `reconstruct_document`** | 按 `document_id` ID 直查扇出各 collection，挂回语义树 | 只读 PG `documents.extra` + Milvus 标量过滤 |

**禁止**：在 Eagle `EagleRouterQueryEngine` / `RetrieverOrchestrator` 内嵌 Knowhere `navigate_step` / DAG planner。若未来需要 Knowhere Agentic，应作为**独立服务**由上游 Agent 编排，而非 Eagle 插件内耦合。

#### 4.1 关注点切分

需区分三件性质不同的事：

| 关注点 | 性质 | 归属 | 可否裁剪 |
| --- | --- | --- | --- |
| PixelRAG 视觉模态（render->Qwen3-VL 2048d->`eagle_visual`->`PixelRAGVisualRetriever`） | **模态本身**--Knowhere 只产文本，图/表只能靠它理解 | **Core 一等公民** | ❌ 不可裁剪 |
| 四锚点桥接（`extract_visual_chunks` 锚点赋值 + 检索侧 `parent_section`/`source_chunk_id` 过滤） | 文本骨架↔视觉向量的**链接逻辑** | Core 默认行为，可被领域插件 override | ⚠️ 可替换不可移除 |
| `knowhere_visual_chunks` 派发任务 | 调度编排 | Core（pixelrag_queue） | ✅ 可重构 |

按 `multimodal-fusion.md` 第 199-224 行，`extract_visual_chunks` 是 **Knowhere 侧**把 image/table chunk 连同 `parent_section`（最近前序文本块 path）提取--这是文本骨架的延伸。PixelRAG 只负责渲染切片与 Qwen3-VL 编码（`multimodal-fusion.md` 第 243-262 行）。两者本就分属不同关注点，不应搅在一起。

#### 4.2 视觉模态归 Core

- Core 视觉编码经 `get_visual_encoder()`（`eagle_rag/ingest/visual_encoder.py`：`pixelrag` 本地 HF / `dashscope` 百炼）；`pixelrag_adapter` 仅负责 render + 调用工厂。**不**迁移到任何独立插件。
- `PixelRAGVisualRetriever`（`retrievers/pixelrag_visual_retriever.py`）保留为 Core 默认 retriever；**M3.5 后** `EagleRouterQueryEngine._fetch_nodes` 委托 `RetrieverOrchestrator`（§2.5），按 `QueryRouteDecision` 多 collection 检索，默认决策等价于现 hybrid 双检索器。
- `knowhere_visual_chunks` task（`pixelrag_adapter.py:594`）保留在 Core，仍走 `pixelrag_queue`（concurrency 1）。
- `pixelrag_build` 全视觉流水线（扫描 PDF/图像/URL/HTML）保留为 Core pipeline。

#### 4.3 四锚点桥接重构为可 override 的 Core 默认行为

- `extract_visual_chunks` + `dispatch_visual_chunks`（现 `knowhere_adapter.py:531,581`）保留为 Core 默认实现，产出带四锚点的 visual chunk 描述。
- 通过 HookBus 暴露 `INGEST_VISUAL_EXTRACT` 与 `RETRIEVE_VISUAL_FILTER` 两个 hook 点，允许领域插件**替换**锚点赋值逻辑（例如 biomed 插件为专用编码器产物补充锚点，见 Phase 5），但**不允许**移除锚点写入。
- **不**新增 namespace=`"fusion"` 的独立插件。原方案的 `plugins/fusion/` 目录取消。

#### 4.4 Core 瘦身的正确边界

Core 瘦身限于：剥离**领域**逻辑（finance 硬编码等），**不**剥离模态。`core_defaults` 提供：knowhere 文本流水线 + PixelRAG 视觉模态 + 四锚点桥接默认实现 + core MCP 工具 + 全局路由/生成编排。

#### 4.5 验收

- 重构后端到端多模态 ingest+query 行为与重构前一致（四锚点字段正确写入/读取，hybrid 双检索器正常工作）。
- **删除**"禁用 fusion->纯文本 RAG"这一验收项--视觉模态不可禁用。
- 领域插件（如 biomed）启停**不**影响 Core 视觉模态：卸载 biomed 后，Core 仍可对任意 PDF 做图/表视觉检索。
- 单测：hook `INGEST_VISUAL_EXTRACT` 可被领域插件 override，但默认实现始终产出四锚点。
- **父文档检索验证**：`parent_doc_retrieval=true` 时，`KnowhereGraphRetriever` Stage 1 召回 `type=section_summary` 节点，Stage 2 按 `path` 前缀下钻细粒度 chunk；`parent_doc_retrieval=false` 时退化为单阶段检索，行为与重构前一致。
- **跨 collection 文档重组验证**：`GET /documents/{id}/structure` 扇出 namespace 内所有 collection 捞碎片，按四锚点挂回 `doc_nav` 语义树返回完整结构。

#### 4.6 跨 collection 文档重组（多模型/多 collection 对文档结构透明）

> 用户关切：无论多少模型和 collection，检索时能否按 Knowhere 语义树把正片文档捞出还原？答案：**设计意图上能**，锚点+语义树+document_id 三者独立于嵌入维度与 collection 数量；但需明确重建路径、跨维度下钻约束，并标注现有未实现的 gap。

**三件独立于向量空间的锚定机制**（多模型多 collection 设计成立的基础）：

| 机制 | 存储位置 | 作用 |
| --- | --- | --- |
| 语义树骨架（`doc_nav.sections`，带 `path` 层级） | PostgreSQL `documents.extra` | 重建的"目录"，不在 Milvus |
| `document_id` 标量字段 | 每个 collection 都有 | 按文档捞出该文档全部碎片 |
| 四锚点（`parent_section`/`source_chunk_id`/`chunk_type`/`content_summary`） | 每个 collection 的标量字段 | 把散落碎片按 `path` 前缀和 `source_chunk_id` 挂回语义树节点 |

三者均独立于嵌入维度与 collection 数量--这是"无论多少模型/collection 都能还原正片文档"的理论基础。

**整文档重建操作（`reconstruct_document`，Core 新增）**：

```
1. 从 PG documents.extra 取 doc_nav 语义树（骨架）
2. 扇出查询：遍历当前 namespace 的所有 collection（基础底座 + 插件 provides_specialized_collections），
   按 document_id 标量过滤捞出各自碎片
   - eagle_text:        fetch_text_nodes_by_document_id(document_id)
   - eagle_visual:      fetch_visual_by_document(document_id)
   - eagle_text_biomed: fetch by document_id（插件 collection，同构查询）
   - eagle_chemical:           fetch by document_id
   - eagle_medical_radiology:  fetch by document_id
   - eagle_medical_pathology:  fetch by document_id
3. 合并所有碎片，按四锚点挂回语义树对应节点：
   - chunk.parent_section（path）匹配 doc_nav section 的 path 前缀 -> 挂到对应章节
   - chunk.source_chunk_id 关联到 eagle_text/eagle_text_biomed 的对应文本 chunk（跨 collection 下钻）
   - chunk.chunk_type 标注碎片类型（text/biomed_text/image/chemical/protein/medical_image/table）
4. 返回完整文档结构（树 + 各节点挂载的碎片）
```

- **`GET /documents/{id}/structure` 端点改造**：现有实现（`api/documents.py:79`）只查 `eagle_text` 的 section_summary。改为调 `reconstruct_document`，扇出到 namespace 内所有 collection，返回含跨 collection 碎片的完整结构。
- **`reconstruct_document` 由 Core 提供**，插件通过 `provides_specialized_collections` 声明的 collection 自动纳入扇出范围（Core 从 PluginManager 获取 namespace 内所有 collection 清单）。插件无需自实现重建逻辑。
- **性能（M5 最低实现）**：collection 清单启动时缓存；`reconstruct_document` **并行** `asyncio.gather` / 线程池扇出各 collection fetch；大文档 structure 端点可选分页（`?section_path=` 子树）；后续可加 PG `document_chunk_index` 倒排表。

**跨维度 `source_chunk_id` 下钻约束**：

跨 collection 下钻（如 `eagle_medical_pathology` 的病理命中 -> `source_chunk_id` 指向 `eagle_text_biomed` 的文本 chunk）**只能走 ID 直查**（`fetch_text_nodes_by_document_id` 已支持按 node_id 过滤），**不能**跨维度向量检索--1536d 的 query 向量无法在 768d collection 里做 ANN。方案需在 `ClassificationDecision`/检索组装层明确：跨 collection 的锚点重联是 ID 直查，不是向量检索。

**父文档检索热路径实现（解决现有 gap）**：

`sections_to_text_nodes` 的 docstring 声称"recall section_summary -> drill down by path prefix"，但实际 `KnowhereGraphRetriever._build_filters`（`knowhere_graph_retriever.py:104`）只下推 `kb_name`/`document_id`/`source_type`/`year`，**不**按 `type=section_summary` 召回、**不**做 path 前缀下钻。path 前缀匹配仅用于 structure 重建（`fetch_text_nodes_by_document_id` 的 `path like "{prefix}%"`），不在检索热路径。这在**现有单 collection** 就未落地。本方案在 Phase 4 补齐，而非留作 gap。

**实现：`KnowhereGraphRetriever` 增加两阶段父文档检索模式**

`_build_filters`（`knowhere_graph_retriever.py:104`）改造--新增 `type` 与 `path_prefix` 过滤维度：

```python
def _build_filters(self, *, type_filter: str | None = None,
                   path_prefix: str | None = None) -> MetadataFilters | None:
    filter_list: list[MetadataFilter | MetadataFilters] = []
    # ... existing kb_name / kb_names / document_ids / source_type / year logic ...
    if type_filter is not None:
        filter_list.append(
            MetadataFilter(key="type", value=type_filter, operator=FilterOperator.EQ)
        )
    if path_prefix is not None:
        filter_list.append(
            MetadataFilter(key="path", value=path_prefix,
                           operator=FilterOperator.TEXT_MATCH)  # prefix via Milvus LIKE
        )
    ...
```

`_retrieve`（`knowhere_graph_retriever.py:144`）改造--新增可选两阶段模式，由 `parent_doc_retrieval: bool` 开关控制（默认开，配置 `settings.router.parent_doc_retrieval`）：

```
Stage 1 - section_summary 召回（粗）:
  filters = _build_filters(type_filter="section_summary")
  retriever = text_index.as_retriever(similarity_top_k=section_top_k, filters=filters)
  section_nodes = retriever.retrieve(query)          # 召回章节摘要节点
  # section_top_k 默认 = similarity_top_k（如 5），召回少量章节

Stage 2 - path 前缀下钻（细）:
  drill_nodes = []
  for sec in section_nodes:
      sec_path = sec.node.metadata["path"]            # e.g. "doc/3 Model Architecture"
      drill_filters = _build_filters(path_prefix=sec_path)
      drill_retriever = text_index.as_retriever(
          similarity_top_k=drill_top_k, filters=drill_filters)
      drill_nodes.extend(drill_retriever.retrieve(query))   # 该章节下细粒度 chunk
  # drill_top_k 默认 = similarity_top_k，每章节下钻若干细块

  # 合并 + 去重（按 node_id）+ graph expansion（connect_to，现有逻辑保留）
  merged = dedupe(section_nodes + drill_nodes)
  expanded = graph_expand(merged)                      # 现有 connect_to 扩展不变
```

- **向后兼容**：`parent_doc_retrieval=False` 时退化为现有单阶段检索（`_build_filters` 不加 `type`/`path_prefix`），行为不变。
- **`path` 前缀过滤（P0-13，✅）**：Stage 2 经 LlamaIndex `FilterOperator.TEXT_MATCH` 做 `path` 前缀过滤（非字面 SQL `LIKE`）。
- **为什么不强制**：两阶段多一轮 ANN（每章节一次下钻），长文档或大 scope 下延迟增加。配置开关让用户按场景取舍；默认开（召回质量优先），可关（延迟优先）。
- **多 collection 适配（P1）**：父文档两阶段检索**默认仅在主文本底座 `eagle_text`** 执行（`parent_doc_retrieval` 不扇出到全部专用 collection，避免 biomed 5 库 × 2 阶段 ANN 延迟爆炸）。`eagle_text_biomed` 专用召回走单阶段；配置 `router.parent_doc_retrieval_collections` 可显式扩展。
- **配置项**（`settings.yaml` `router` 段）：
  ```yaml
  router:
    parent_doc_retrieval: true      # enable two-stage parent-doc retrieval
    section_top_k: 5               # stage-1 section_summary recall count
    drill_top_k: 5                 # stage-2 fine-grained chunk count per section
    rrf_k: 60                      # G8: RRF fusion constant (RerankFusion.merge_rrf)
  ```

**与 `reconstruct_document` 的关系**：两者独立。`reconstruct_document` 按 `document_id` **全量**捞出（ID 直查，非向量检索），用于 `/documents/{id}/structure` 整文档展示；父文档检索是**查询热路径**的两阶段向量召回优化，用于 `/query`/`/search` 的检索质量提升。互不依赖，可各自交付。

---

### Phase 5 - `plugins/biomed` 生物医药插件（首个业务示范）

> **同仓插件**（`plugins/biomed/`，经 `settings.plugins.enabled` 加载）。允许内部集成 PubMedBERT/BioBERT 及医学影像专用编码器。

#### 5.0 查询路由实现策略（G15 + G20 + G21，已拍板）

`BiomedQueryRouteClassifier` **v1 不用 LLM** 做 collection 分类（零额外 query 延迟、可确定性测试）。实现为 **规则 + UMLS 实体触发**，并与 **scope-aware 并集（G21）** 闭合 ingest 双轨：

| 触发条件 | 加入的 plan |
| --- | --- |
| 默认（biomed 实例、纯文本 query、**无 scope 专用库文档**） | **仅** `eagle_text`（G20：`default_dual_text_search=false`） |
| UMLS/本地本体命中 ≥1 生物医学实体（基因、药物、疾病、通路） | `eagle_text` + `eagle_text_biomed` |
| scope **KB** `collections_used` 含专用库（**G23**） | **强制**加对应 collection plans（即使 query 无实体） |
| scope **文档** catalog 含 `eagle_text_biomed`（**G21**） | **强制**加 `eagle_text_biomed` |
| 无 UMLS 命中 + 规则判定「通用非生物」query（如纯商业/行政措辞） | 仅 `eagle_text` |
| SMILES/InChI 子串或化学结构关键词 | 加 `eagle_chemical` |
| scope catalog 含 `eagle_chemical`（G21） | 强制加 `eagle_chemical` |
| 放射影像关键词（CT/MRI/超声/病灶描述）或 query 带 DICOM 附件 | 加 `eagle_medical_radiology` |
| 病理/HE/组织学关键词 | 加 `eagle_medical_pathology` |
| 规则无法判定 | 返回 `None`（**abstain**）→ Core 默认 G4（仍执行 G21 scope 并集） |

- 规则表放 `plugins/biomed/routing_rules.yaml`（可热更新）；UMLS 子集与 `QUERY_ASSEMBLE` 实体扩展共用索引。
- **配置**：`settings.plugins.options.biomed.default_dual_text_search: false`（G20）；`exploratory_search_collections: []`（G27）。
- **G27 产品语义**：无 scope 且无 UMLS 时，**不保证**命中仅存在于专用 collection 的 chunk——须在 UI 明示（§1.7）。
- **预留**：`CLASSIFY_QUERY` 链允许后续插件注册 LLM 分类器（高 priority），但 v1 不默认启用。
- 所有决策经 `PluginAudit.log_decision` 记录触发规则/实体 ID / scope 并集原因。

#### 5.1 插件能力（全部通过 hook 注入）

> **底座恒在 + 专用增量**（本节核心心智模型）：biomed DB 内 `eagle_text`(1536d, `text-embedding-v4`) 与 `eagle_visual`(2048d, Qwen3-VL) 是**恒在的基础底座**，承载该领域所有通用文本（论文引言/背景/讨论、FDA 通用条款、专利背景）与通用图像（实验记录截图、文档版式图）。插件只**新增**专用 collection 承载特殊数据，**不替换**基础底座的维度与编码器。分流粒度是 **per-chunk**，不是 namespace 级整库替换。

- **`manifest`**：`namespace="biomed"`，`milvus_db_name="biomed"`，`provides_pipelines=()`（**G7：不新增 pipeline**，复用 Core `knowhere`/`pixelrag`），`provides_specialized_collections=("eagle_text_biomed","eagle_chemical","eagle_medical_radiology","eagle_medical_pathology")`，`provides_mcp_tools=("query_entities","retrieve_compounds")`。
  - **注意**：`embedder_override` 字段取消。原设计的 namespace 级整库替换与"通用走底座"冲突，改为 per-chunk 分流（见下）。
- **on_load**：懒加载 PubMedBERT、MolFormer；**MedImageInsight**（放射）、**UNI 2**（病理）；`ensure_collections` 创建专用 collection（各自 `dim` 由 encoder 决定）。
- **BiomedFormatSelector**（订阅 `INGEST_ROUTE_SELECTORS`，`namespace="biomed"`）：`.pdb`/`.sdf`/`.mol`/医学 PDF 等仍路由到 **`knowhere`** pipeline（G7）；领域解析走下方 `PARSE`/`CHUNK` hooks，**不**派发独立 `biomed` Celery task。
- **BiomedSectionTagger**（订阅 `CHUNK` hook，`namespace="biomed"`；模块 `plugins/biomed/chunker.py`）：
  - **Knowhere-first enrich**：不重切文本、不重建目录树；在 Knowhere `path` / typed chunks 上标注 `biomed_section`（IMRaD / claims 别名）与 `biomed_doc_type`。
  - 真要改切分/层级边界 → 上推 Knowhere parse，禁止 Eagle 从零 chunker。
  - **"图像+图注+表格+脚注打包为同一逻辑分组"**--明确：这是**逻辑分组 + 四锚点链接**，**不是**单向量嵌入。PubMedBERT 只能嵌入文本，无法嵌入图像；物理上，图注/脚注（文本）经 **`IngestOrchestrator`** + `EMBED_TEXT` 进文本 collection，图像/表格经 `EMBED_VISUAL` 进目标视觉 collection（G22）。分组关系靠四锚点（`parent_section`=最近前序文本块 path、`source_chunk_id`=对应文本 chunk_id）在检索时重联，**复用 EagleRAG 既有的双向量空间+锚点设计**（`multimodal-fusion.md` 第 266-282 行），而非把图文塞进一个向量。
  - 专利 claim：仅从 Knowhere `path`/弱文本回退标注 `claims`，不重建权利要求树。
- **BiomedTextClassifier**（订阅 `CLASSIFY_CHUNK` hook，`namespace="biomed"`）--**取代原 `embedder_override` 的关键设计**，per-chunk 分流而非 namespace 级整库替换：
  - 输入 `ClassificationContext`（text chunk + IMRaD 段位 + 实体密度等），输出标准 `ClassificationDecision`：
    - 通用文本（论文引言/背景/讨论、FDA 通用条款、专利背景）-> `ClassificationDecision(category="general_text", target_collection="eagle_text", target_encoder="text-embedding-v4", chunk_type="text")` -> 写入**基础底座** `biomed.eagle_text`(1536d)。
    - 术语密集特殊文本（方法学描述、生化反应描述、实体/通路段落）-> `ClassificationDecision(category="biomed_term", target_collection="eagle_text_biomed", target_encoder="pubmedbert", chunk_type="biomed_text")` -> 写入**专用** `biomed.eagle_text_biomed`(768d)。
    - 无法判断 -> 返回 `None`（abstain），fallback 到 Core 默认文本分类器（所有文本 -> `eagle_text` + `text-embedding-v4`）。
  - 两条支路都填充四锚点（`parent_section`/`source_chunk_id`/`chunk_type`），检索时各 collection 分路召回后**经 RERANK hook + RRF 合并**（G8；禁止跨 embedding 空间直接比 raw score）。
  - **防双写（P1-9）**：`ClassificationDecision` 可选 `exclusive_group: str`；同一 chunk 在同一 `exclusive_group` 内只写入一个 primary collection；边界抖动由 `audit.log_decision` 监控。
  - **为什么不整库换 PubMedBERT**：PubMedBERT 在生物医学术语/实体上强，但是 768d encoder，对长段落通用语义检索未必胜过 1536d `text-embedding-v4`；把"药物商业化背景"这类通用文本也用 PubMedBERT 嵌，是用偏科模型干通用模型的活。per-chunk 分流让两种模型各司其职。
- **BiomedImageClassifier**（订阅 `CLASSIFY_VISUAL` hook，`namespace="biomed"`）--**将原 ad-hoc"轻量分类器"升格为注册到 Core 接口的标准分类器**：
  - 输入 `ClassificationContext`（image bytes + parent_section + source_chunk_id），输出标准 `ClassificationDecision`，按图像性质分四档：

    | 图像类型 | `ClassificationDecision` 输出 | 编码方式 | 落库 |
    | --- | --- | --- | --- |
    | 化学分子图 | `category="chemical", target_collection="eagle_chemical", target_encoder="molformer", chunk_type="chemical"` | 化学结构识别器 -> SMILES -> MolFormer | `biomed.eagle_chemical`（专用） |
    | 蛋白结构图 | `category="protein", target_collection="eagle_chemical", target_encoder="pdb_fingerprint", chunk_type="protein"` | PDB 拓扑 -> 结构指纹 | `biomed.eagle_chemical`（专用） |
    | 文档版式图（Western Blot/凝胶图/实验记录截图/表格） | `category="document_visual", target_collection="eagle_visual", target_encoder="qwen3-vl", chunk_type="image"` | Core Qwen3-VL-Embedding-2B 2048d | `biomed.eagle_visual`（基础底座） |
    | **放射影像（CT/MRI/超声）** | `category="radiology_image", target_collection="eagle_medical_radiology", target_encoder="medimageinsight", chunk_type="medical_image"` | **MedImageInsight** | `biomed.eagle_medical_radiology` |
    | **病理切片（HE 染色）** | `category="pathology_slide", target_collection="eagle_medical_pathology", target_encoder="uni2", chunk_type="medical_image"` | **UNI 2** | `biomed.eagle_medical_pathology` |
    | 无法判断 | 返回 `None`（abstain） | fallback Core 默认视觉分类器 -> `eagle_visual` + Qwen3-VL | `biomed.eagle_visual`（基础底座） |

  - **医学影像不回落 Qwen3-VL 作为最终解**：Qwen3-VL-Embedding-2B 的训练/评测基准（MMEB-v2/MMTEB，视觉文档检索用 JinaVDR/ViDoRe v3）全是文档/截图/图表，**无医学影像分布**（context7 `/qwenlm/qwen3-vl-embedding` 官方资料）。医学影像的语义在像素级纹理（病灶形态、组织结构），非版式；用文档版式编码器会产生语义错误的召回。
  - **垂类医学影像（M6 已拍板，拆 collection）**：
    - **放射**（CT/MRI/超声）→ `eagle_medical_radiology` + MedImageInsight（各自原生维度，collection 创建时 `dim=` 与模型对齐）。
    - **病理**（HE 染色）→ `eagle_medical_pathology` + UNI 2（独立 collection，**不与放射共用向量空间**）。
    - 两路编码器在 `on_load` 注册到 `EncoderRegistry`；**禁止**医学影像写入 `eagle_visual` 或经 Qwen3-VL 编码。
  - **关键约束：所有分类决策产物必须保留四锚点**。`ClassificationContext` 携带 `parent_section`/`source_chunk_id`，无论 `ClassificationDecision` 指向哪个 collection/编码器，写入时**强制**透传这两个锚点 + `chunk_type`。专用编码器**override 的是向量生成方式（由 `target_encoder` 决定），不是链接关系**。
  - 分类器 abstain（返回 None）时 fallback 到 Core 默认视觉分类器（所有图像 -> `eagle_visual` + Qwen3-VL），**不得**静默丢弃。
- **PubMedBERT/biomed reranker override**（订阅 `RERANK` hook，仅对 `eagle_text_biomed` 召回的节点生效；基础底座 `eagle_text` 召回的节点仍走 Core `qwen3-rerank`）。
- **BiomedQueryRouteClassifier**（订阅 `CLASSIFY_QUERY` hook，`namespace="biomed"`）--**查询侧检索路由**（实现见 **§5.0 G15**）：规则 + UMLS 触发决定 `plans`；abstain → Core 默认路由（G4：仅 `eagle_text` + 可选 `eagle_visual`）。
- **实体扩展**（订阅 `QUERY_ASSEMBLE` hook）：基于本地 UMLS 子集本体，"HER2" -> "ERBB2/HER-2/CD340"+相关通路，注入检索 query。

#### 5.2 MCP 工具

- `biomed_query_entities(entity)`：返回实体别名、通路、关联药物/突变。
- `biomed_retrieve_compounds(smiles_or_name)`：化学结构相似/子结构检索。
- 通过 Phase 3 的 `register_mcp_tool` 注册；**仅**在 `default_namespace=biomed` 实例暴露（G3）。

#### 5.3 数据隔离与多嵌入空间检索组装

**数据隔离（底座 + 专用增量）**：
- 所有 biomed 写入落到独立 `biomed` Milvus Database；core 检索在 `default` DB，**物理隔离零泄漏**。
- **基础底座恒在**：`biomed.eagle_text`(1536d, `text-embedding-v4`) + `biomed.eagle_visual`(2048d, Qwen3-VL)，与 core 同维度，承载通用文本与通用图像。
- **领域专用增量**（按需）：`eagle_text_biomed`(768d)、`eagle_chemical`、`eagle_medical_radiology`(MedImageInsight)、`eagle_medical_pathology`(UNI 2)。
- **单实例单 DB**：biomed 部署实例只查 `biomed` DB；**永不做跨 DB 检索**。与 core 的协作由**多实例部署**或调用方多次请求承担。

**多嵌入空间共存的检索组装**（biomed DB 内多 collection；由 **RetrieverOrchestrator** §2.5 执行）：
- biomed hybrid 检索：`BiomedQueryRouteClassifier` 产出 `QueryRouteDecision.plans` → **G21 scope 并集** → Orchestrator 多路 ANN → 分路 RERANK → **RRF 合并**（G8）。
- **BiomedQueryRouteClassifier** 示例决策（G20/G21）：
  - UMLS 命中 / scope 含 biomed 专用文档 → `plans=(("eagle_text","text-embedding-v4"), ("eagle_text_biomed","pubmedbert"))`
  - 纯通用问题、无 scope 专用库 → 仅 `("eagle_text","text-embedding-v4")`
  - 含化学结构 / scope 含 chemical → 加 `("eagle_chemical","molformer")`
  - 放射影像 query / 带 CT 描述 → 加 `("eagle_medical_radiology","medimageinsight")`
  - 病理/HE 描述 → 加 `("eagle_medical_pathology","uni2")`
  - abstain → Core 默认路由 + G21 scope 并集
- **文本侧**：分路 ANN 后 **RERANK hook 合并**（`eagle_text`→`qwen3-rerank`；`eagle_text_biomed`→PubMedBERT reranker）。
- **视觉侧**：版式图 → `eagle_visual`(qwen3-vl)；化学 → `eagle_chemical`；放射 → `eagle_medical_radiology`；病理 → `eagle_medical_pathology`。**禁止 raw cosine 跨空间排序**。
- **四锚点重联是跨空间拼合的依据**：所有 collection 的命中都携带 `source_chunk_id`/`parent_section`/`chunk_type`，通过 `source_chunk_id` **ID 直查**下钻到 `eagle_text`/`eagle_text_biomed` 对应文本块（跨维度不可向量检索，见 Phase 4.6 约束），通过 `parent_section` 做章节范围限定，与 `multimodal-fusion.md` 第 277-282 行设计一致。专用编码器 override 的是向量生成，**不**破坏锚点链接。
- 生成阶段（`EagleMultimodalQueryEngine`）：文本命中的 `content_summary` + 视觉命中的图像路径 + 锚点关联文本，一并送 Qwen-VL-Max 生成，流程不变。
- **整文档重建**：biomed 多 collection（`eagle_text`/`eagle_text_biomed`/`eagle_visual`/`eagle_chemical`/`eagle_medical_radiology`/`eagle_medical_pathology`）经 `reconstruct_document` 扇出重组。

#### 5.4 验收

- 100 篇 PubMed/FDA 文献端到端：Knowhere `doc_nav`/path 保留、IMRaD 段位标注正确、四锚点保留、PubMedBERT 向量入库、实体扩展生效、引用可溯源到段落/图号。
- **医学影像**：放射 → `eagle_medical_radiology` + MedImageInsight；病理 HE → `eagle_medical_pathology` + UNI 2；**无** Qwen3-VL 冒充医学向量。
- **入库分类器验证**：`BiomedTextClassifier`/`BiomedImageClassifier` 输出标准 `ClassificationDecision`；abstain fallback；telemetry 记录 `category`/`target_collection`/`confidence`。
- **查询路由 + Orchestrator 验证**：`BiomedQueryRouteClassifier`（G15/G20/G21）产出 multi-encoder `plans`；scope 内专用库文档强制并集；`RetrieverOrchestrator` 双路 ANN + 分路 RERANK + **RRF 合并**；单路失败 best-effort（G14）。
- **入库编排验证（G22）**：`IngestOrchestrator` 将 PubMedBERT / MedImageInsight / UNI 2 向量写入对应 collection；四锚点保留。
- **跨 collection 文档重组验证**：`GET /documents/{id}/structure` 扇出含 `eagle_medical_radiology`/`eagle_medical_pathology`；跨维度 `source_chunk_id` ID 直查成功。
- 禁用 biomed 插件时 Core 视觉模态完全不受影响（Core 仍可对任意 PDF 做图/表视觉检索），且 Core 默认分类器接管所有 chunk/图像路由。

---

### Phase 6 - `plugins/lakehouse-bi` 湖仓语义层 RAG 检索插件

> **同仓插件**（`plugins/lakehouse-bi/`）。**定位修正**：本插件是**纯粹的湖仓语义层 RAG 检索服务**，为第三方独立的 Agentic BI 服务提供业务语义上下文。
> **不做** SQL 执行、不做 Text-to-SQL 生成、**不内置任何湖仓 connector**。EagleRAG 全程不直连湖仓。

#### 6.1 核心定位与边界

**EagleRAG 在 Agentic BI 中的角色** = **Agent-Ready 语义层检索底座**。第三方 Agentic BI 服务（自带取数/执行/可视化能力）通过 MCP 或 REST 向 EagleRAG 请求"语义上下文"，EagleRAG 只负责把散落的元数据与业务知识检索出来、组装成结构化上下文包返回。

| 职责 | 归属 | 说明 |
| --- | --- | --- |
| 湖仓元数据拉取（DDL/db/schema/table/column/views） | **用户二开 connector** | EagleRAG 不内置任何湖仓 connector |
| 湖仓无关数据资产 YAML（指标/业务规则/join/fewshot/context） | **用户编写 + EagleRAG 解析入库** | 行业标准 YAML schema（见 6.3） |
| 非结构化业务知识文档入库 | **EagleRAG Core（knowhere pipeline）** | 复用现有文本流水线 |
| 语义上下文混合召回与组装 | **本插件** | 核心能力 |
| SQL 生成 / SQL 执行 / 取数 / 可视化 | **第三方 Agentic BI 服务** | EagleRAG 不参与 |

**支持的湖仓**：Databricks / Snowflake / Apache Doris / StarRocks / 以及任何能导出元数据的湖仓--因为 EagleRAG 不连湖仓，"支持某湖仓"等同于"用户为该湖仓实现了 connector 把元数据导出成 EagleRAG 可摄入的格式"。

#### 6.2 用户二开 connector 契约

EagleRAG 定义 **`LakehouseMetadataConnector` 抽象基类**（位于 **`eagle_rag/plugins/contracts/lakehouse.py`**，Core 轻量契约，与 lakehouse 检索插件解耦）：

```python
class LakehouseMetadataConnector(ABC):
    """User-implemented connector: pulls metadata FROM a lakehouse,
    EagleRAG never connects to the lakehouse directly."""

    @abstractmethod
    def extract_ddl(self) -> Iterator[str]:
        """Yield raw DDL statements (CREATE TABLE/VIEW/...)."""

    @abstractmethod
    def extract_schema(self) -> list[TableDescriptor]:
        """Return table/column/view descriptors (db/schema/table/columns/types/comments)."""

    @abstractmethod
    def extract_views(self) -> list[ViewDescriptor]:
        """Return view definitions (name, sql, dependencies)."""

    # Optional: lineage, partitions, stats - override if available.
```

- 用户在二开时实现自己的 connector（Databricks/Snowflake/Doris/StarRocks 各自一个），调用湖仓的 information_schema / `SHOW CREATE TABLE` / REST API 拉取元数据。
- Connector 产出物喂给 EagleRAG 标准 `/ingest` 接口（指定 `plugin_namespace="lakehouse-bi"`）。
- EagleRAG 不 import 任何湖仓 SDK；connector 是用户的代码，不在 EagleRAG 进程内运行时依赖（仅入库时调用一次导出）。

> 这里的 connector 是"一次性元数据导出器"，不是常驻连接池。导出的元数据以文件（DDL `.sql` / schema `.json` / 资产 `.yaml`）形式提交给 EagleRAG ingest。

#### 6.3 湖仓无关数据资产 YAML schema（行业标准，dbt Semantic Layer 兼容）

资产 YAML 与湖仓无关，描述指标口径、业务规则、join 规则、fewshot、business context。**采用 dbt Semantic Layer 兼容格式**（业界事实标准，便于与 dbt/metric 生态互操作）。

**语义模型（semantic_models）** - 描述表/实体的度量与维度：

```yaml
semantic_models:
  - name: orders
    description: |
      Order fact table. Grain: one row per order.
    model: ref('fct_orders')      # logical ref, resolved by user's connector at BI side
    defaults:
      agg_time_dimension: order_date
    entities:                      # join keys
      - name: order_id
        type: primary
      - name: customer
        expr: customer_id
        type: foreign
    dimensions:                    # categorical / time
      - name: order_date
        type: time
        type_params:
          time_granularity: day
      - name: region
        type: categorical
    measures:                      # aggregable columns
      - name: order_total
        description: Total amount per order incl. tax.
        agg: sum
        expr: amount
      - name: order_count
        expr: 1
        agg: sum
```

**指标定义（metrics）** - 四种类型，覆盖绝大多数 BI 口径：

```yaml
metrics:
  # Simple - direct measure aggregation
  - name: order_total
    description: Sum of orders value
    type: simple
    label: Order Total
    type_params:
      measure:
        name: order_total

  # Ratio - numerator / denominator
  - name: avg_order_value
    description: Average value of each order
    type: ratio
    type_params:
      numerator:
        name: order_total
      denominator:
        name: order_count

  # Cumulative - windowed aggregation (MTD/QTD/YTD)
  - name: cumulative_order_amount_mtd
    description: Month-to-date value of all orders
    type: cumulative
    type_params:
      measure:
        name: order_total
      cumulative_type_params:
        grain_to_date: month

  # Derived - arithmetic over other metrics
  - name: pct_large_orders
    description: Percent of orders over 20
    type: derived
    type_params:
      expr: large_orders / order_count
      metrics:
        - name: large_orders
        - name: order_count
```

**EagleRAG 扩展资产**（dbt 之外、湖仓无关的业务知识，EagleRAG 自定义 key）：

```yaml
# EagleRAG-specific asset kinds (lakehouse-agnostic)
business_rules:
  - name: active_user_definition
    description: |
      "活跃用户"口径：近 30 天内登录 ≥3 次且产生 ≥1 笔有效订单。
      退货订单不计入有效订单。
    applies_to: metric:active_users
    owner: growth-team

join_rules:
  - name: orders_to_customers
    description: How orders join to customers
    from: orders
    to: customers
    on: orders.customer_id = customers.customer_id
    type: many_to_one

fewshots:
  - question: 华东区 Q3 退货率趋势
    intent: metric_trend_by_dimension
    resolved_metric: return_rate
    dimensions: [region, quarter]
    filters: { region: "华东", quarter: "Q3" }
    notes: |
      退货率 = 退货订单数 / 总订单数。注意 2025-Q2 起退货口径变更，
      历史对比需用 return_orders_v2 表。

business_context:
  - name: status_code_map
    description: 订单状态枚举映射
    mapping:
      "1": 待支付
      "2": 已支付
      "3": 已发货
      "Y": 标记有效
  - name: fiscal_calendar
    description: 财年与自然年差异说明
    content: 本公司财年 4 月起算，Q1=4-6 月...
```

> 所有 YAML 资产 + DDL + schema 描述 + 非结构化业务文档，统一经 `/ingest`（`plugin_namespace="lakehouse-bi"`）入库，由 knowhere 文本流水线解析分块，存入独立 Milvus Database **`lakehouse_bi`** 的**基础底座** `eagle_text`/`eagle_visual` collection（`kb_name` 标量过滤隔离多 KB）。lakehouse-bi **不新增专用 collection**--所有资产类型（DDL/metric/rule/fewshot/context）都进基础底座 `eagle_text`，靠 `type` 标量字段（`table_schema`/`metric`/`business_rule`/`join_rule`/`fewshot`/`business_context`）区分，检索时按 `type` 过滤。这与 biomed 的"专用 collection"模式不同：biomed 因嵌入维度不同（768d vs 1536d）必须分 collection；lakehouse-bi 全用 core 默认 `text-embedding-v4`，维度一致，无需分库。

#### 6.4 插件能力（全部通过 hook 注入）

- **`manifest`**：`namespace="lakehouse-bi"`，`milvus_db_name="lakehouse_bi"`，`provides_pipelines=()`（复用 core knowhere 文本流水线，不自带 pipeline），`provides_specialized_collections=()`（全进基础底座，靠 `type` 标量字段区分资产类型，见上），`provides_mcp_tools=("query_semantic_context","retrieve_historical_analysis")`。
- **on_load**：无模型单例（纯检索，不 override embedder/reranker，用 core 默认 Qwen text-embedding-v4）。
- **资产解析增强**（订阅 `PARSE`/`CHUNK` hook，仅对 `plugin_namespace=="lakehouse-bi"` 生效）：
  - DDL `.sql` -> 提取表名/字段/注释/外键，生成 `Table_Schema_Chunk`（type=`table_schema`）。
  - 资产 `.yaml` -> 按 top-level key 分块：semantic_models -> `Semantic_Model_Chunk`；metrics -> `Metric_Definition_Chunk`（type=`metric`）；business_rules/join_rules/fewshots/business_context -> 对应 typed chunk。
  - 数据字典 PDF/Excel -> 复用 knowhere 表格解析，枚举值映射精准入库。
- **查询上下文组装**（订阅 `QUERY_ASSEMBLE` hook，仅 lakehouse-bi namespace）：意图路由识别为"数据查询"类，混合召回 `Table_Schema` + `Metric_Definition` + `Business_Logic` + 历史相似分析报告（均通过 `eagle_text` 的 `type` 标量过滤），组装成结构化上下文包。

#### 6.5 MCP 工具（只读检索，无执行）

> **删除 `execute_sql` 与 `reflect_on_error`**--SQL 执行与纠错归第三方 Agentic BI 服务，EagleRAG 不参与。

- **`lakehouse_bi_query_semantic_context(question: str, kb_name: str | None = None) -> dict`**
  混合召回当前问题相关的表结构、指标口径、业务规则、join 规则、fewshot、枚举映射，返回结构化语义上下文包：
  ```json
  {
    "tables": [{"name":"...","schema":"...","columns":[...],"ddl":"..."}],
    "metrics": [{"name":"...","type":"...","formula":"...","description":"..."}],
    "business_rules": [...],
    "join_rules": [...],
    "fewshots": [...],
    "enums": [...],
    "sources": [{"document_id":"...","chunk_id":"...","path":"..."}]
  }
  ```
  第三方 Agent 据此生成 SQL、自行执行、自行纠错--EagleRAG 不在闭环内。

- **`lakehouse_bi_retrieve_historical_analysis(topic: str, kb_name: str | None = None) -> list[dict]`**
  检索历史分析报告与归因结论（非结构化业务文档入库的部分），避免 Agent 从零开始。

#### 6.6 典型 Agentic BI 协作工作流

```
┌──────────────────────┐         MCP /mcp          ┌─────────────────────┐
│ Third-party Agentic  │ ─── lakehouse_bi_query_semantic_context ─>│ EagleRAG lakehouse  │
│ BI service           │ <── semantic context pack ─│ -bi plugin (RAG)    │
│ (generates & runs    │                            │  (检索 only)        │
│  SQL, visualizes,    │ ─── lakehouse_bi_retrieve_historical_analysis ─>│                     │
│  reflects on errors) │ <── historical analyses ───│                     │
└──────────────────────┘                            └─────────────────────┘
         │                                                      │
         │ user's connector (二开) pulls metadata               │ ingest via /ingest
         ▼                                                      ▼
┌──────────────────────┐                            ┌─────────────────────┐
│ Lakehouse            │                            │ Milvus DB           │
│ (Databricks/Snowflake│                            │  "lakehouse_bi"     │
│  /Doris/StarRocks)   │                            │  ├─ eagle_text      │
└──────────────────────┘                            │  └─ eagle_visual    │
                                                    │  (kb_name filter)   │
                                                    └─────────────────────┘
```

1. 用户二开 connector 从湖仓拉取 DDL/schema/views + 编写资产 YAML + 业务文档 -> 经 `/ingest` 入库。
2. 第三方 Agentic BI 收到用户自然语言问题。
3. BI Agent 通过 MCP 调 `lakehouse_bi_query_semantic_context`，获得标准化指标公式、相关表、业务注释、枚举映射、join 规则、fewshot。
4. BI Agent 自行生成 SQL、在自己侧执行、出错自行反思纠错（EagleRAG 不参与执行/纠错）。
5. BI Agent 可选调 `lakehouse_bi_retrieve_historical_analysis` 获取历史归因逻辑辅助结论。
6. BI Agent 返回带溯源的结论给用户。

**整个过程 EagleRAG 只做检索，不执行任何 SQL、不连任何湖仓。**

#### 6.7 验收

- 一份 DDL + 一份指标定义 YAML + 一份业务规则 YAML 经 `/ingest`（`plugin_namespace="lakehouse-bi"`）入库。
- MCP `lakehouse_bi_query_semantic_context` 能召回相关表结构/指标口径/业务规则/fewshot/枚举。
- `lakehouse_bi_retrieve_historical_analysis` 能召回历史分析报告 chunk。
- 确认插件**不**包含任何 SQL 执行代码、**不** import 任何湖仓 SDK。
- 确认 `LakehouseMetadataConnector` ABC 可被用户继承并产出合规元数据。

---

### Phase 7 - 文档与约束同步

- 更新 `AGENTS.md`：新增"插件架构"章节（PluginManager/HookBus/契约/`plugin_namespace` 隔离/MCP 聚合/**`ContentClassifier` 分类器接口**）；调整模型策略表述为"Core 仅 DeepSeek/Qwen 调度与生成；领域插件可自带领域模型"；新增插件开发指南要点（含"如何注册自定义分类器 + fallback 默认"）。
- 更新 `README.md`：微内核 + 插件定位、双示范、MCP 单端点。
- 更新 `eagle_rag/settings.yaml`：`plugins` 段示例（`enabled` 同仓模块列表、`default_namespace` 部署固定领域）+ 注释；可选 `profiles:` 块（P2-4）。
- 同步 `docs/en/architecture/` 与 `docs/zh/architecture/`（新增 `plugin-architecture.md`，更新 `multimodal-fusion.md` 说明视觉模态归 Core、四锚点桥接可被领域插件 override）。
- **ADR（P1-13）**，落 `docs/en/architecture/adr/` + `docs/zh/architecture/adr/`：
  - `001-milvus-database-isolation.md` — Database = `plugin_namespace` vs 标量过滤
  - `002-single-domain-deployment.md` — 单域实例、无 UI 领域切换、多实例跨域
  - `003-mcp-tool-naming-and-registration.md` — `{namespace}_{name}`、G3 注册范围
  - `004-multi-encoder-rrf-fusion.md` — G4/G8/G14/G32 默认路由 + RRF 合并 + 跨 collection dedupe + Orchestrator best-effort
  - `005-knowhere-eagle-boundary.md` — G16：parse/doc_nav vs Milvus 检索；禁止 query 热路径调 Knowhere Agentic
  - `006-ingest-query-routing-contract.md` — G21/G23/G28/G29/G30/G31：ingest catalog、KB/document/tags scope-aware 并集、提交时机与 rebuild
- **架构对齐（G16/G21）**：ADR-005/006 固化职责表与 ingest–query 契约（原 P2-5 升格）。

---

## 五、交付顺序与里程碑

| 里程碑 | 阶段 | 可独立合并 | 核心验收 |
| --- | --- | --- | --- |
| M1 微内核地基 | Phase 0 | ✅ | 无行为变化；**HookBus namespace 过滤**、**G13 异常语义**、**PluginContext 契约**、**GET /health/plugins** |
| M2 领域隔离 | Phase 1 + §1.8–§1.9 | ✅ | **G6/G17/G24** spike + 池化；PG **G18**；**G25/G28** catalog；**G19**；MinIO/cache（G12） |
| M2.5 产品语义 UI | Phase 1.7 | ✅ | **G1/G19**；**G27** 探索性检索 UI 提示；KB 选择 + i18n |
| M3 Pipeline 注册表 | Phase 2 + §2.6 | ✅ | **G22/G26** IngestOrchestrator + hook 顺序；派发去硬编码（G7） |
| M3.5 检索编排 | Phase 2.5 | ✅ | **G21/G23/G29** scope-aware；RRF（G8）+ **G32 dedupe** + best-effort（G14）；SSE `collection_plans` |
| M4 MCP 注册表 | Phase 3 | ✅ | **`core_*` / `{ns}_{name}`（G2）**；**G3 联动校验** |
| M5 视觉模态归 Core | Phase 4 | ✅ | **G16**；**P0-13 path 前缀 spike**；**G5** parent_doc；`reconstruct_document` |
| M6 Biomed 插件 | Phase 5 | ✅ | **G15/G20/G21/G23**；G22 入库；MedImageInsight + UNI 2 |
| M7 Lakehouse 语义层 | Phase 6 | ✅ | `lakehouse_bi_*` MCP；语义上下文检索（无 SQL） |
| M8 文档同步 | Phase 7 | ✅ | AGENTS/README/docs；**ADR 六篇（006 含 G23/G28/G29–G31）** |

---

## 六、Grilling 审查清单（P0 / P1 / P2）

> 来源：2026-07-10 `/grill-with-docs` 对规划稿的架构审查 + 拍板决策（§拍板 G1–G33）。  
> **状态**：`已拍板` = 决策写入方案；`待实现` = 设计已闭合、按里程碑落地；`优化` = 不阻塞首版、可后续迭代。

### P0 — 必须在实现前闭合（设计矛盾 / 阻塞项）

| # | 问题 | 状态 | 决策 / 缓解 | 落地里程碑 |
| --- | --- | --- | --- | --- |
| P0-1 | 默认 `QueryRouteClassifier` 用 `text-embedding-v4` 查 `eagle_text_biomed`(768d) 不可行 | **已拍板** | G4：Core 默认**永不**查专用 collection；仅 `eagle_text` + 可选 `eagle_visual` | M1 接口；M3.5 编排 |
| P0-2 | `MilvusVectorStore(db_name=)` 假设过乐观（LlamaIndex 未必支持） | **已拍板** | G6：不接受降级到 `using_database` 竞态；**接受重写 text store** 为 `MilvusClient(uri, db_name=)` 薄封装 | **M2 阻塞 spike** |
| P0-3 | PyMilvus 同 URI 客户端**共享连接**；`close()` 影响全部；异步并发下 DB 上下文竞态 | **已拍板** | G17：构造时 `db_name=`；**禁止** `close()` / `using_database` 切换；M2 spike 验证；`alias`≠独立连接 | M2 §1.2 |
| P0-4 | 「单实例单 DB」与「UI 领域切换器」语义打架 | **已拍板** | G1：**单域部署**；UI **无**领域切换器，只读展示部署领域 | M2.5 §1.7 |
| P0-5 | 聚合 `/mcp` 暴露他域工具，但实例无对应 Milvus 数据 | **已拍板** | G3：仅注册 `core_*` + `default_namespace` 插件工具；`enabled`↔`default_namespace` **fail-fast** | M1 校验；M4 MCP |
| P0-6 | `RouteSelector`（模态 text/visual/hybrid）与 `QueryRouteClassifier`（collection plans）职责重叠、调用顺序未定义 | **已拍板** | 分层流水线 ADR（§2.5.2.1）；`QueryRouteClassifier.route(..., route_mode=)` 受 `RouteDecision.mode` 约束 | M3.5 |
| P0-7 | `CollectionQueryPlan` 未校验 encoder 维度与 collection 维度一致 | **✅ 已实现** | `EncoderRegistry.validate_plan(collection, encoder_name)`；ingest/retriever orchestrator 共用 | M3.5 |
| P0-8 | Hook 订阅者异常时 ingest/query 行为未定义 | **已拍板** | G13：`invoke_first`/`invoke_transform` **fail-fast**；`QUERY_ASSEMBLE` per-plugin 降级 | M1 §0.1 |
| P0-9 | Orchestrator 单路 ANN 失败是否拖垮整 query | **已拍板** | G14：**best-effort** 合并 + `PluginAudit` | M3.5 §2.5.2 |
| P0-10 | `alias` 误以为独立 TCP 连接，掩盖同 URI 共享连接 | **已拍板** | G17：文档化 PyMilvus 语义；禁止 `close()`；M2 spike | M2 §1.2 |
| P0-11 | 专用 encoder 入库路径未定义（`EMBED_VISUAL` 无 hook） | **已拍板** | G22：`IngestOrchestrator` + `EMBED_*`/`UPSERT_VECTORS` | M3 §2.6 |
| P0-12 | 入库 per-chunk 分类与 query 路由双轨，专用库向量查不到 | **已拍板** | G21/G23：scope-aware + document/KB catalog（G28）；ADR-006 | M3.5；M6 |
| P0-13 | 父文档 `path` 前缀 Milvus `LIKE` 未验证 | **✅ 已实现** | Stage 2 使用 LlamaIndex `FilterOperator.TEXT_MATCH` 做 path 前缀过滤（非字面 SQL `LIKE`） | M5 §4.6 |
| P0-14 | 现网 `MilvusClient.close()` 与 G17 冲突 | **已拍板** | G24：`MilvusClientPool`；M2 grep 清零 health/stats/lifecycle | M2 §1.2 |
| P0-15 | scope 仅 `kb_names` 时 G21 catalog 未定义 | **已拍板** | G23：`knowledge_bases.collections_used` KB 级并集 | M2 §1.9；M3.5 |
| P0-16 | `INGEST_VISUAL_EXTRACT` 与 `CLASSIFY_VISUAL` 顺序歧义 | **已拍板** | G26：固定 ingest hook 链（§0.1、§2.6） | M3 |

### P1 — 首版应完成（遗漏边界 / 数据一致性）

| # | 问题 | 状态 | 决策 / 缓解 | 落地里程碑 |
| --- | --- | --- | --- | --- |
| P1-1 | PG 元数据隔离不完整：`document_keywords` / `resolve_tags_to_document_ids` 仅按 `kb_name`，同名 KB 跨 namespace 串 tag | **已拍板** | G10：`document_keywords` 加 `plugin_namespace`；tag 解析 WHERE 强制 namespace | M2 §1.4 |
| P1-2 | `scope_filter` 标签解析未带 namespace | **已拍板** | G10：`router_engine._resolve_scope_filter` 传入 session/API 的 `plugin_namespace` | M2 |
| P1-3 | PG 查询靠「记得加 filter」，易漏 namespace | **已拍板** | G9：新增 `eagle_rag/db/repositories/`，**强制**注入 `plugin_namespace`；handler 禁止裸 SQL | M2 |
| P1-4 | 多路 RERANK 后合并算法未定义（跨空间 raw score 不可比） | **已拍板** | G8：分路 RERANK → **`RerankFusion.merge_rrf`**；禁止跨 embedding 空间比大小 | M3.5 |
| P1-5 | Hook 订阅「仅 biomed 生效」靠插件自觉判断，易漏 | **✅ 已实现** | `HookBus.subscribe(..., namespace=...)`；invoke 前按 `HookContext.plugin_namespace` 过滤 | M1 |
| P1-6 | Celery worker 多模型单例：每 worker 进程各加载一份 GPU 模型，内存 × concurrency | **待实现** | `PluginManifest.resource_hints`（`gpu_mb`/`load_order`）；biomed 实例 worker 拓扑文档；重编码可考虑独立 queue | M6 前文档；M6 实现 |
| P1-7 | biomed「独立 pipeline」与 knowhere 关系模糊 | **已拍板** | G7：**knowhere + hooks**；`provides_pipelines=()`；`BiomedFormatSelector` 仍路由 `knowhere` | M3；M6 |
| P1-8 | `parent_doc_retrieval` 默认开 = 相对现网行为变更（现未实现两阶段） | **已拍板** | G5：默认 `true`；`false` 退化为现单阶段；§4.6 仅 `eagle_text` 两阶段 | M5 |
| P1-9 | per-chunk 分类边界抖动 → 同一 chunk 双写 `eagle_text` + `eagle_text_biomed` | **✅ 已实现** | `ClassificationDecision.exclusive_group`；ingest_helpers 同组跳过 dual-write；RRF G32 dedupe + audit | M6 |
| P1-10 | lakehouse 元数据一次性导出，schema 变更无增量同步 story | **待实现** | 资产 chunk 增 `asset_version` / `source_export_id`；文档补「connector 重导出 → re-ingest」playbook | M7 |
| P1-11 | `reconstruct_document` 扇出 N collection，大文档 structure 超时 | **待实现** | M5 最低：**并行 fetch** + collection 清单缓存；P1 后续：`?section_path=` 分页、`document_chunk_index` 倒排表 | M5（并行）；M5+ 分页 |
| P1-12 | `attachments` 懒解析缓存 / `image_base64` query 未贯穿 `plugin_namespace` | **待实现** | `attachments/parser.py` cache key 与 MCP cache 对称加 namespace（§1.8 扩展） | M2 §1.8 扩展 |
| P1-13 | 英文文档与 ADR 缺失（`docs/en/`、Milvus DB 隔离 ADR、MCP breaking change） | **✅ 已实现** | `docs/en|zh/architecture/plugin-architecture.md` + ADR-001/002/003/007/008 | M8 |
| P1-14 | `PluginContext` / `PluginAudit` 契约未在 Phase 0 完整定义 | **✅ 已实现** | `eagle_rag/plugins/audit.py` 多 sink；`GET /health/plugins`；`ctx.audit.log_decision` | M1 |
| P1-15 | MCP `source_type` enum 仍含 finance 等领域硬编码（现 `mcp_server.py`） | **待实现** | M4 顺带改为行业无关 enum 或自由字符串；与 AGENTS「无领域硬编码」对齐 | M4 |
| P1-16 | KB 级联删除需扇出 namespace 内**全部** collection（含插件专用） | **待实现** | `kb/lifecycle.py` 从 `PluginManager` 取 `provides_specialized_collections` 列表逐库 `delete(kb_name)` | M2 / M6 |
| P1-17 | `task_audit` / `notifications` / `mcp_call_log` 无 namespace，共用 PG 时串线 | **已拍板** | G11：三表加 `plugin_namespace` + repository 强制注入 | M2 §1.4 |
| P1-18 | MinIO **原始文档** key 未隔离（仅 tile 路径在 §1.8） | **已拍板** | G12：`ingest/runner.py` → `{plugin_namespace}/{source_type}/{document_id}/{name}` | M2 §1.8 |
| P1-19 | `BiomedQueryRouteClassifier`「意图识别」实现未定义 | **已拍板** | G15：v1 **规则 + UMLS**，不用 LLM；§5.0 | M6 |
| P1-20 | Knowhere Agentic 与 Eagle 父文档检索重复建设 | **已拍板** | G16：Eagle 不调 Knowhere `RetrievalAgent`；§4.0 + ADR-005 | M5 / M8 |
| P1-21 | `documents` 子表仅 `document_id` FK，跨 namespace JOIN 串线 | **已拍板** | G18：子表复合 FK / 等价约束 + repository 强制 | M2 §1.4 |
| P1-22 | API `plugin_namespace` 不一致仅 warn，共用 PG 可读他域元数据 | **已拍板** | G19：生产忽略请求参数；不一致 **403** | M2.5 §1.7 |
| P1-23 | Biomed 实例默认双路 text ANN，每 query 固定 2× 延迟 | **已拍板** | G20：默认仅 `eagle_text`；UMLS 命中才加 `eagle_text_biomed` | M6 §5.0 |
| P1-24 | ingest 分类变更后无 reclassify / 重嵌入 story | **待实现** | Celery `reclassify_kb` 或全量 KB rebuild 文档；M6 后迭代 | M6+ |
| P1-25 | `kb/stats` 只统计 `eagle_text`/`eagle_visual` | **已拍板** | G25：扇出插件 collection + `MilvusClientPool` | M2 §1.9；M6 |
| P1-26 | catalog 存储方案二选一未决 | **已拍板** | G28：v1 `documents.extra` + `knowledge_bases.collections_used` | M2 §1.9 |
| P1-27 | 全库无 scope biomed 漏专用库，用户无感知 | **已拍板** | G27：UI i18n 提示 + 可选 `exploratory_search_collections` | M2.5 |
| P1-28 | `pixelrag_queue=1` 阻塞多 encoder ingest | **待实现** | M6 前评估分队列（升格 P2-7）；与 P1-6 联动 | M6 前 |
| P1-29 | `scope_filter.tags` 的 G21 catalog 路径未写入契约 | **已拍板** | G29：tags → `resolve_tags_to_document_ids(namespace)` → document catalog 并集 | M3.5 §2.5.2.2 |
| P1-30 | 失败/部分 ingest 污染 `collections_used` | **已拍板** | G30：仅 `documents.status=success` 且全 chunk upsert 后更新 catalog | M3 §2.6 |
| P1-31 | KB rebuild 后 `collections_used` 陈旧 | **已拍板** | G31：rebuild 清空 KB 并集、逐文档成功重算；delete 删行 | M2 §1.9；`kb/lifecycle` |
| P1-32 | RRF 后双 collection 重复节点（P1-9 双写） | **已拍板** | G32：`dedupe_cross_collection` by `source_chunk_id` / `(document_id, path)` | M3.5 §2.5 |
| P1-33 | `list_sessions` 无 namespace 过滤，共用 PG 泄漏元数据 | **已拍板** | G33：repository 强制 `plugin_namespace` on get/list/create | M2 §1.4 |

### P2 — 优化项（不阻塞 M1–M8 首版）

| # | 问题 | 建议 | 时机 |
| --- | --- | --- | --- |
| P2-1 | 自定义 `register_mcp_tool` vs FastMCP 原生 `mount(sub_mcp, namespace=)` | 首版保留自定义 registry（与 `TOOL_DEFINITIONS` REST 发现一致）；后续可评估 `mount()` 减少胶水代码 | M8 后 |
| P2-2 | `CollectionQueryPlan` / `QueryRouteDecision` 在文档 §0.1 与 §2.5 **重复定义** | 实现时单一来源：`eagle_rag/plugins/routing.py` | M1 代码结构 |
| P2-3 | `Plugin.on_unload()` 长驻进程几乎不调用 | 改为 `health_check()` / `ready()` 供 `GET /health/plugins`；`on_unload` 保留给测试 | M1 |
| P2-4 | `enabled` / `default_namespace` / `MILVUS_DB_NAME` 三处配置易漂移 | 引入 **`profiles:`** 部署配置块（**建议 M2 即做**） | M2 settings |
| P2-5 | Knowhere 自有 Agentic RAG / WorkflowOrchestrator / 3-channel RRF，与 Eagle 父文档两阶段可能重复建设 | **已拍板（G16）** | §4.0 职责表 + ADR-005；Eagle query 不调 Knowhere Agentic | M5 / M8 |
| P2-6 | biomed 6 collection × HNSW 索引，单 Milvus 集群资源 sizing 无指引 | 补充部署 sizing 表（collection 数、dim、预估向量量 → 内存/磁盘） | M6 前 ops 文档 |
| P2-7 | `pixelrag_queue` concurrency=1，多插件视觉编码排队 | **M6 前**评估 `medical_encode_queue` 或按 encoder 分 queue（见 P1-28） | M6 前 |
| P2-8 | 插件契约一致性测试套件（stub plugin 覆盖全部 hook 点） | `tests/plugins/test_contract_conformance.py` + 模板 `plugins/_template/` | M3 后 |

| P2-9 | SSE `step` 未暴露多 collection `collection_plans` | M3.5 `route` step 增加 `collection_plans` + `scope_aware_union`（§2.5.2.1） | M3.5 |

### P0/P1 与里程碑映射（速查）

```
M1  ← P1-5, P1-14, P0-5(校验), P0-8, P0-11(接口), P0-16(枚举), P2-3
M2  ← P0-2, P0-3, P0-10, P0-14, P0-15, P1-1, P1-2, P1-3, P1-12, P1-16, P1-17, P1-18, P1-21, P1-25, P1-26, P1-31, P1-33, P2-4, G24, G31
M2.5← P0-4, P1-22, P1-27, G19, G27
M3  ← P1-7, P0-11, P0-16, P1-30, P2-8, G22, G26, G30
M3.5← P0-1, P0-6, P0-7, P0-9, P0-12, P0-15, P1-4, P1-29, P1-32, G21, G23, G29, G32, P2-9
M4  ← P0-5, P1-15, P2-1(文档注记)
M5  ← P0-13, P1-8, P1-11, P1-20
M6  ← P1-6, P1-9, P1-19, P1-23, P1-24, P1-28, P2-6, P2-7
M7  ← P1-10
M8  ← P1-13, P2-5(G16), G23/G28/G29–G31(ADR-006)
```

---

## 七、风险与缓解

1. **PubMedBERT 维度（768）≠ Core text dim（1536）**：**已由"底座恒在 + 专用增量"设计解决**--biomed DB 的 `eagle_text` 基础底座恒为 1536d（`text-embedding-v4`），PubMedBERT 768d 只写入**新增**专用 collection `eagle_text_biomed`，两者同库不同 collection，不冲突。插件在 per-chunk 分流时决定落哪个 collection。无需替换基础底座维度。
2. **Milvus `db_name` / text store（G6，已拍板接受重写）**：Phase 1 **阻塞 spike** 验证 `llama-index-vector-stores-milvus`；不支持则 text store 改为原生 `MilvusClient(uri, db_name=)` 薄封装（与 visual store 对齐），**不**依赖 `using_database` 变异连接状态。
3. **连接级 DB 状态的并发安全（G17，已拍板）**：构造时 `db_name=` 绑定；**禁止** `MilvusClient.close()` 与 per-request `using_database()`；同 URI 共享连接（`alias`≠独立 TCP）；M2 阻塞 spike 验证 FastAPI + Celery 无竞态。
4. **跨 DB 检索（已拍板：不做）**：单服务实例绑定单一 Milvus Database（`settings.plugins.default_namespace`）。单次 query **可跨 collection、不可跨 DB**。与 core/biomed 同时检索需**多实例部署**或调用方发起多次请求自行合并。这是物理隔离 + 单实例模型的固有取舍。
5. **医学影像双 collection（已拍板）**：`eagle_medical_radiology`(MedImageInsight) 与 `eagle_medical_pathology`(UNI 2) 独立维度，不做 projection 合并。`BiomedQueryRouteClassifier` 按 query 意图选 collection + encoder。
6. **插件懒加载模型单例的 GPU 资源争用**：`on_load` 顺序按 `depends_on` 拓扑排序。biomed 依赖 Core Qwen3-VL 处理文档版式图；专用编码器（PubMedBERT/MolFormer/MedImageInsight/UNI 2）在 hook 前就绪。
7. **Celery worker 插件一致性**：`collect_celery_modules()` worker 启动 fail-fast；API/worker 共用 `settings.plugins.enabled`；**`GET /health/plugins`（M1）** 暴露 manifest 与 MCP 工具列表。
8. **lakehouse-bi 资产 YAML 兼容性**：采用 dbt Semantic Layer 兼容格式作为子集，EagleRAG 扩展 key 作为附加；解析器对未知 key 保留原文。Milvus DB 名为 `lakehouse_bi`（API namespace 仍为 `lakehouse-bi`）。
9. **lakehouse 元数据时效性**：connector 为一次性导出；需提供「重新导出 → 重新 ingest」刷新流程（dedup 按 sha256+namespace 去重）。
10. **父文档检索延迟（G5 默认开）**：两阶段模式比单阶段多一轮 ANN；默认仅在 `eagle_text` 执行（§4.6）；`settings.router.parent_doc_retrieval` 可关。
11. **多编码器 query 复杂度（G4/G8）**：Core 默认不查专用 collection；插件显式加查；跨 collection 合并**必须 RRF**（§2.5），禁止 raw score 排序。
12. **PG 主键 + repository（G9/G10）**：`document_dedup`/`knowledge_bases` PK 扩展；`document_keywords` 加 `plugin_namespace`；Alembic 回填；repository 层强制 namespace。
13. **MCP breaking change（G2）**：`core_*` 工具名无 alias；M4 后集成方须更新 tool 调用。
14. **对象存储隔离（已拍板）**：images/MinIO/cache 须与 Milvus DB 同步 `plugin_namespace`（§1.8）；否则向量与 tile 文件错位。
15. **插件信任**：同仓 `plugins/*` only；进程内无沙箱——ADR 写明信任模型。
16. **MCP 工具与实例域一致（G3）**：`enabled` 必须与 `default_namespace` 匹配；避免 Agent 发现无数据工具。
17. **LakehouseMetadataConnector**：ABC 放 `eagle_rag/plugins/contracts/lakehouse.py`，与 lakehouse 检索插件解耦。
18. **分类决策 telemetry**：`PluginContext.audit.log_decision`；日志/cache 含 `plugin_namespace`。
19. **Hook 异常（G13）**：ingest/query 主路径 fail-fast；`QUERY_ASSEMBLE` 单插件失败可降级，避免扩写拖垮生成。
20. **Orchestrator 分路失败（G14）**：单 collection ANN 失败不中止整 query；全路失败返回空；与现 retriever 降级一致。
21. **Biomed 查询路由（G15）**：v1 规则+UMLS，不用 LLM；避免不可测试的「意图黑盒」与额外延迟。
22. **Knowhere 边界（G16）**：Eagle 仅用 Knowhere parse/doc_nav；不调 `RetrievalAgent`/`WorkflowOrchestrator`，防止双轨 agentic 编排。
23. **运维表 PG 隔离（G11）**：`task_audit`/`notifications`/`mcp_call_log` 与业务表同步 namespace 维度。
24. **MinIO 原始文档（G12）**：与 tile 路径一致加 `plugin_namespace` 前缀，防跨域覆盖源文件。
25. **PG 子表硬隔离（G18）**：`document_id` 全局唯一；子表 FK 须带 `plugin_namespace`，禁止跨域 JOIN。
26. **API namespace 信任（G19）**：生产仅用 `default_namespace`；请求不一致 → 403。
27. **Biomed 默认查询成本（G20）**：默认单路 `eagle_text`；UMLS 命中才加专用库；避免每 query 双 ANN。
28. **Ingest–Query 契约（G21）**：scope 含专用库文档时强制并集 plans；ingest catalog 与 query 闭合。
29. **入库编码编排（G22）**：`IngestOrchestrator` + `EMBED_*`/`UPSERT_VECTORS`；与 RetrieverOrchestrator 对称。
30. **Milvus Database 租户上限**：Database 级多租户默认约 **64** DB/集群（可配额扩容）；多行业多实例规划须计入 ops sizing。
31. **KB 级 scope catalog（G23）**：`knowledge_bases.collections_used` 与 document catalog 并集；scope 仅 KB 时闭合 G21。
32. **Milvus 客户端池化（G24）**：禁止 `close()`；health/stats 迁移 `MilvusClientPool`。
33. **KB 可观测性（G25）**：stats/API 扇出插件专用 collection。
34. **Ingest hook 顺序（G26）**：`INGEST_VISUAL_EXTRACT` 在 `CLASSIFY_*` 之前。
35. **全库探索检索（G27）**：无 scope 不保证专用库召回；UI 须明示。
36. **Catalog 存储（G28）**：v1 用 PG JSON 列，不新建表。
37. **Tags scope（G29）**：tags 解析后走 document catalog 并集，闭合 G21。
38. **Catalog 提交时机（G30）**：仅 ingest 终态成功更新，失败不污染 KB catalog。
39. **KB rebuild catalog（G31）**：rebuild 清空并集、逐文档重算。
40. **RRF 去重（G32）**：双写场景 RRF 后按 `source_chunk_id` / path dedupe。
41. **Session 列表隔离（G33）**：repository 强制 namespace，防共用 PG 元数据泄漏。

---

## 八、执行说明

本方案为完整重构蓝图。建议按 M1 -> M8 顺序逐步实现，每个里程碑独立 PR。**已拍板决策**见 §拍板（G1–G33）；**审查清单**见 §六（P0/P1/P2）。如认可此方案，从 **M1（Phase 0：PluginManager + HookBus + core_defaults）** 开始实施；biomed 实例在 M6 完成后以独立部署 + `default_namespace: biomed` 启动。
