# ADR-008：纯 RAG 插件平台 + 前端范围锁定

- **状态**：已接受（Accepted）
- **日期**：2026-07-14
- **背景**：在保持 EagleRAG 为纯 RAG 数据层（而非业务 Agent 平台）的前提下，关闭死 hook、Core 行业耦合，并补齐二开 DX。

## 决策

1. **产品红线**：EagleRAG 只做 ingest / retrieve / assemble-context / admin-metadata。行业插件只提升召回质量，不得长出 Agent 行为或副作用 MCP 工具。
2. **热路径 hook**：`PARSE`、`CHUNK`、`QUERY_ASSEMBLE` 经 `eagle_rag/plugins/hotpath_hooks.py` 在 ingest/query 路径真实调用（不仅是订阅）。
3. **Core 解耦**：垂类旋钮放在 `settings.plugins.options[<namespace>]`（`plugin_options()`）。Core `source_type.rules` 默认为空（无 finance/tax 硬编码）。文档 reconstruct 按 `PluginManifest.provides_specialized_collections` 扇出。
4. **MCP**：插件暴露 `register_mcp_tools()`；工具名 RAG-only（`assert_rag_only_tool_name`）。实例仅暴露 `core_*` + `default_namespace` 工具（G3）。
5. **前端范围**：内置 UI 只展示 **Core** knowhere + pixelrag 混合检索。垂类（biomed、lakehouse-bi 等）**仅后端 + MCP**，本仓库无垂类 UI。
6. **二开 SDK**：`plugins/_template/` + `docs/zh/guides/authoring-industry-plugin.md`；成功标准 = 召回/溯源，不是 UI 完整度。

## 后果

- 新行业插件：复制模板 → profile → MCP；无需改 Core、无需前端。
- 文档明确区分 Core 橱窗 UI 与垂类 MCP 后端。
- 禁止的 MCP 名称片段在注册时失败。

## 相关

- [ADR-007](007-plugin-implementation-status.md) — 实现状态与 profile
- [插件架构](../plugin-architecture.md) — 已落地架构说明
- [编写行业插件](../../guides/authoring-industry-plugin.md)
