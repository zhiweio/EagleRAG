# 术语表 — 插件架构（实现）

| 术语 | 含义 |
| --- | --- |
| `plugin_namespace` | 实例域绑定（= Milvus Database）。由部署配置固定；非运行时 UI 切换器（G1）。 |
| `kb_name` | 单个 Milvus Database 内的知识库标量过滤。 |
| `EAGLE_RAG_PROFILE` | 激活 `settings.yaml` 的 `profiles:` 覆盖层（`core` / `biomed` / `lakehouse-bi`）。 |
| `plugins.options.<ns>` | 每插件旋钮（dict）；通过 `plugin_options(ns)` 读取。非 Core 类型化 settings。 |
| Hot-path hooks | `PARSE` / `CHUNK` / `QUERY_ASSEMBLE` 在 ingest/query 上通过 `hotpath_hooks.py` 调用。 |
| RAG-only MCP | 工具仅检索/组装上下文；`assert_rag_only_tool_name` 禁止副作用命名。 |
| Frontend scope | 内置 UI = Core knowhere + pixelrag 展示；域插件在仓库内无 UI。 |
| Base collections | 每个域 DB 内始终存在的 `eagle_text` + `eagle_visual`。 |
| Specialized collections | Biomed 专用扩展（`eagle_text_biomed`、`eagle_chemical`、`eagle_medical_*`）。 |
| Encoder mode | `auto` / `require_native` / `deterministic` — 医学编码器永不使用 Qwen3-VL。 |
| UMLS subset | `plugins/biomed/routing_rules.yaml` 中的本地本体，用于 G15 路由 + MCP。 |
| Lakehouse connector | 用户自有导出器（`LakehouseMetadataConnector`）；EagleRAG 仅 ingest 文件。 |
| `_template` | `plugins/_template/` 下的最简行业 RAG 插件骨架。 |
