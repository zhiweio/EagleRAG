# 编写行业 RAG 插件（二开指南）

EagleRAG 是 **纯 RAG 数据层**：行业插件只提升垂直场景的 **召回质量 / 精度 / 资产结构化**，经 **MCP（主）/ API** 交给下游 Agent。本仓库 **不提供、不要求** 垂类前端。

英文对照：[`docs/en/guides/authoring-industry-plugin.md`](../../en/guides/authoring-industry-plugin.md)。

## 产品边界

| 做 | 不做 |
| --- | --- |
| ingest / chunk / encode / multi-collection retrieve / RRF / 溯源 | 业务工作流、多步 Agent 规划 |
| 返回结构化上下文包 + sources | Text-to-SQL 执行、改库、发邮件、下单 |
| 在 Knowhere 节点上做领域 metadata enrich、专用编码器、实体扩写 | 行业 Agent UI / 演示页 |

**内置前端 = Core 橱窗**（knowhere 语义结构 + pixelrag 视觉混合检索）。垂类一律后端 + MCP。

## 交付物清单

1. `plugins/<namespace>/` — 实现 `Plugin` 协议（可从 [`plugins/_template/`](../../../plugins/_template/) 复制）
2. `register_hooks` — 订阅热路径 hook（见下方矩阵）
3. `register_mcp_tools()` — 显式入口；工具用 `@register_mcp_tool`，命名 `{namespace}_{name}`
4. `settings.yaml` → `profiles.<name>` — `enabled` + `default_namespace` + `milvus.db_name`
5. 契约测试（热路径 hook 被调用；MCP 禁止执行类工具名）

成功标准 = **召回质量与溯源**，不是 UI 完整度。

## Hook 矩阵（RAG 热路径）

| Hook | 模式 | 插入点 | 典型用途 |
| --- | --- | --- | --- |
| `PARSE` | transform | Knowhere parse 后 | 解析 enrich / DDL→typed |
| `CHUNK` | transform | IngestOrchestrator 前 | **仅**领域 metadata enrich（保留 Knowhere `path` / 正文 / `doc_nav` / `chunk_id`） |
| `INGEST_VISUAL_EXTRACT` | first | 视觉 ingest | 提取视觉块 + 四锚点字段 |
| `CLASSIFY_CHUNK` / `CLASSIFY_VISUAL` | first | orchestrator | 路由到专用 collection；可选 `exclusive_group` 跳过 dual-write |
| `CLASSIFY_QUERY` | first | query 路由 | 多 collection plans |
| `QUERY_ASSEMBLE` | all（可降级） | ANN 前 | query 扩写 / 实体 hint |
| `QUERY_DENSE_EXPAND` | first | 分路 ANN 前 | 稠密改写 + 稀疏词项 + `QueryRetrievalIntent` |
| `RERANK` | first | 分路 ANN 后 | Tier-1 领域重排（实体过滤/加权在插件内） |
| `RETRIEVE_SUPPLEMENT` | all | 分路重排后 | 实体锚定或限定范围补充 ANN |
| `RRF_POST_MERGE` | first | RRF 合并后 | 向重排池注入 supplement 候选 |
| `RERANK_MERGED` | first | RRF（+ 注入）后 | 交叉编码器 / 领域合并重排 |
| `EMBED_TEXT` / `EMBED_VISUAL` | first | 写入前 | 专用编码器（`EncoderRegistry`） |
| `UPSERT_VECTORS` | transform | 写入前 | 向量落库（默认写 Milvus） |
| `RETRIEVE_VISUAL_FILTER` | first | 视觉检索 | 视觉过滤覆盖 |
| `CELERY_TASKS` | all | Worker 启动 | 额外 Celery include 模块 |
| `INGEST_ROUTE_SELECTORS` | first | 格式路由 | 额外 format → pipeline 选择器 |

Core 保证 `PARSE` / `CHUNK` / `QUERY_ASSEMBLE` 在 MCP/API 热路径上真实调用（见 `eagle_rag/plugins/hotpath_hooks.py`）。`RetrieverOrchestrator` 调用上表 query hook — **Core 不得在此路径 import 领域插件**。

### Query 检索 hook 模式（参考 biomed）

```text
QUERY_DENSE_EXPAND → ANN（按配置 hybrid）→ RERANK
  → RETRIEVE_SUPPLEMENT → RRF → RRF_POST_MERGE → RERANK_MERGED
```

在 `plugins/<namespace>/retrieval_hooks.py` 注册处理器；领域打分放在独立模块（如 `scoring.py`）。经 `EncoderRegistry.register_collection(..., hybrid_enabled=True)` 和/或 profile 中 `settings.router.hybrid_text_collections` 声明 hybrid collection。

Biomed 评测套件：[`eval/biomed/`](../../../eval/biomed/) — [`RETRIEVAL.md`](../../../eval/biomed/RETRIEVAL.md)、[`EVAL.md`](../../../eval/biomed/EVAL.md)。

## 可观测与审计

在 hook 处理器中使用 `ctx.audit.log_decision(...)`（`PluginContext.audit` → `PluginAudit`）。决策扇出到 AI JSONL、Redis 近期窗口、内存 ring 与 Prometheus（best-effort）。用 `GET /health/plugins`（`recent_decisions` / `audit_stats`）验证加载与路由。

编码器 label、UMLS/MRCONSO、PluginAudit sink 细节见 [ADR-007](../architecture/adr/007-plugin-implementation-status.md)。

## MCP 约定（RAG-only）

- 工具名：`{namespace}_{verb_noun}`，如 `biomed_query_entities`、`acme_retrieve_assets`
- 允许：`retrieve_*`、`query_*`、`list_*`、`get_*_context`、`assemble_*`
- 禁止：`execute_sql`、`run_sql`、`send_email`、`place_order`、`write_db`、`mutate_*`（由 `assert_rag_only_tool_name` 拦截）
- 单实例仅暴露 `core_*` + `default_namespace` 工具（G3）

## 配置

```yaml
# settings.yaml
plugins:
  options:
    acme:                    # 非 Core 强类型字段；经 plugin_options("acme") 读取
      some_knob: true
    # biomed 示例（namespace=biomed 时）：
    # biomed:
    #   default_dual_text_search: false
    #   exploratory_search_collections: []
    #   encoder_mode: auto   # auto | require_native | deterministic

profiles:
  acme:
    plugins:
      enabled: [eagle_rag.plugins.core_defaults, plugins.acme]
      default_namespace: acme
    milvus:
      db_name: acme
```

启用：`EAGLE_RAG_PROFILE=acme`。

Biomed 相关环境变量（参考）：`EAGLE_BIOMED_ENCODER_MODE`、`EAGLE_BIOMED_*_MODEL`、`EAGLE_BIOMED_UMLS_MRCONSO_PATH`、`EAGLE_BIOMED_ALLOW_DETERMINISTIC`；BiomedCLIP/`open_clip` 需 `uv sync --extra biomed`。

## 最小步骤

1. `cp -r plugins/_template plugins/acme`，重命名 namespace / 类 / MCP 前缀
2. 按需实现 classifier 或 `QUERY_ASSEMBLE`；CHUNK 只做 metadata enrich（禁止从零重切）
3. 增加 profile；在 compose / env 中设 `EAGLE_RAG_PROFILE=acme`
4. 用 MCP 或 `/search` 验证召回，并用 `GET /health/plugins` 检查 — **不要**用前端作为验收条件

## 参考实现

- `plugins/biomed`（**实验性**）— 专用 collection + 编码器 + 实体锚定检索 hook + IMRaD CHUNK enrich；评测见 `eval/biomed/`
- `plugins/lakehouse_bi`（**开发中**）— 语义层上下文包（只读检索骨架）
- ADR-007：[`docs/zh/architecture/adr/007-plugin-implementation-status.md`](../architecture/adr/007-plugin-implementation-status.md)
- ADR-008：[`docs/zh/architecture/adr/008-rag-only-plugin-platform.md`](../architecture/adr/008-rag-only-plugin-platform.md)
