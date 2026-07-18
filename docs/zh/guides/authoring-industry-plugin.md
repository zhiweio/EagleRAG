# 编写行业 RAG 插件（二开指南）

EagleRAG 是 **纯 RAG 数据层**：行业插件只提升垂直场景的 **召回质量 / 精度 / 资产结构化**，经 **MCP（主）/ API** 交给下游 Agent。本仓库 **不提供、不要求** 垂类前端。

## 产品边界

| 做 | 不做 |
| --- | --- |
| ingest / chunk / encode / multi-collection retrieve / RRF / 溯源 | 业务工作流、多步 Agent 规划 |
| 返回结构化上下文包 + sources | Text-to-SQL 执行、改库、发邮件、下单 |
| 领域分块、专用编码器、实体扩写 | 行业 Agent UI / 演示页 |

**内置前端 = Core 橱窗**（knowhere 语义结构 + pixelrag 视觉混合检索）。垂类一律后端 + MCP。

## 交付物清单

1. `plugins/<namespace>/` — 实现 `Plugin` 协议（可从 [`plugins/_template/`](../../plugins/_template/) 复制）
2. `register_hooks` — 订阅热路径 hook（见下方矩阵）
3. `register_mcp_tools()` — 显式入口；工具用 `@register_mcp_tool`，命名 `{namespace}_{name}`
4. `settings.yaml` → `profiles.<name>` — `enabled` + `default_namespace` + `milvus.db_name`
5. 契约测试（热路径 hook 被调用；MCP 禁止执行类工具名）

成功标准 = **召回质量与溯源**，不是 UI 完整度。

## Hook 矩阵（RAG 热路径）

| Hook | 模式 | 插入点 | 典型用途 |
| --- | --- | --- | --- |
| `PARSE` | transform | Knowhere parse 后 | 解析 enrich / DDL→typed |
| `CHUNK` | transform | nodes 后、IngestOrchestrator 前 | 行业分块 / metadata |
| `CLASSIFY_CHUNK` / `CLASSIFY_VISUAL` | first | orchestrator | 路由到专用 collection |
| `CLASSIFY_QUERY` | first | query 路由 | 多 collection plans |
| `QUERY_ASSEMBLE` | all（可降级） | ANN 前 | query 扩写 / 实体 hint |
| `EMBED_*` / `UPSERT_VECTORS` | first / transform | 写入前 | 专用编码器 |
| `RERANK` | … | 召回后 | 领域重排 |

Core 保证 `PARSE` / `CHUNK` / `QUERY_ASSEMBLE` 在 MCP/API 热路径上真实调用（见 `eagle_rag/plugins/hotpath_hooks.py`）。

## MCP 约定（RAG-only）

- 工具名：`{namespace}_{verb_noun}`，如 `biomed_query_entities`、`acme_retrieve_assets`
- 允许：`retrieve_*`、`query_*`、`list_*`、`get_*_context`、`assemble_*`
- 禁止：`execute_sql`、`run_sql`、`send_email`、`place_order`、`write_db`、`mutate_*` 等副作用（注册时由 `assert_rag_only_tool_name` 拦截）
- 单实例只暴露 `core_*` + `default_namespace` 工具（G3）

## 配置

```yaml
# settings.yaml
plugins:
  options:
    acme:                    # 非 Core 类型字段；用 plugin_options("acme") 读取
      some_knob: true

profiles:
  acme:
    plugins:
      enabled: [eagle_rag.plugins.core_defaults, plugins.acme]
      default_namespace: acme
    milvus:
      db_name: acme
```

启用：`EAGLE_RAG_PROFILE=acme`。

## 最小步骤

1. `cp -r plugins/_template plugins/acme` 并改 namespace / 类名 / MCP 前缀
2. 实现分类器或 `QUERY_ASSEMBLE`（按需）
3. 加 profile；本地 `pnpm`/`task` 或 compose 设 `EAGLE_RAG_PROFILE=acme`
4. 用 MCP/`/search` 验证召回；**不要**为验收补前端

## 参考实现

- `plugins/biomed` — 专用 collection + 编码器 + 实体 MCP
- `plugins/lakehouse_bi` — 语义层上下文包（只读检索）
- ADR-008：`docs/zh/architecture/adr/008-rag-only-plugin-platform.md`
