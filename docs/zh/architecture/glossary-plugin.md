# 术语表 — 插件架构（实现）

| 术语 | 含义 |
| --- | --- |
| `plugin_namespace` | 实例域绑定（= Milvus Database）。由部署配置固定；不是运行时 UI 切换器（G1）。 |
| `kb_name` | 单个 Milvus Database 内的知识库标量过滤。 |
| `EAGLE_RAG_PROFILE` | 激活 `settings.yaml` 的 `profiles:` 覆盖层（`core` / `biomed` 实验性 / `lakehouse-bi` 开发中）。 |
| `plugins.options.<ns>` | 每插件旋钮（dict）；经 `plugin_options(ns)` 读取。非 Core 强类型设置。 |
| 热路径 hook | 经 `hotpath_hooks.py` 在 ingest/query 上调用的 `PARSE` / `CHUNK` / `QUERY_ASSEMBLE`。 |
| RAG-only MCP | 工具只检索/组装上下文；`assert_rag_only_tool_name` 禁止副作用类名称。 |
| 前端范围 | 内置 UI = Core knowhere + pixelrag 橱窗；垂类插件在本仓无 UI。 |
| 基础 collection | 每个域 DB 内始终存在的 `eagle_text` + `eagle_visual`。 |
| 专用 collection | Biomed 增量（`eagle_text_biomed`、`eagle_chemical`、`eagle_medical_*`）。 |
| Encoder label | Biomed 运行时名：`pubmedbert`（768）、`molformer`（768）、`medimageinsight`（1024 BiomedCLIP/`open_clip`）、`uni2`（1536）。 |
| Encoder mode | `auto` / `require_native` / `deterministic` — 医学编码器永不使用 Qwen3-VL。 |
| `exclusive_group` | `ClassificationDecision` 字段；同组内跳过 dual-write。 |
| UMLS 子集 | `plugins/biomed/routing_rules.yaml` + `umls.py` 中的精选本体，供 G15 路由 + MCP。 |
| MRCONSO 合并 | 可选 `EAGLE_BIOMED_UMLS_MRCONSO_PATH` — 合并 ENG + `ISPREF=Y` 别名/CUI（需 NLM 许可）。 |
| PluginAudit | 多 sink 决策遥测（`audit.py`）：AI JSONL + Redis `eagle:plugin_audit:{ns}:recent` + 内存 ring + Prometheus。 |
| Audit category | 如 `classify_chunk`、`route_query`、`scope_routing_error`、`hook_failure`。 |
| Lakehouse connector | 用户自有导出器（`LakehouseMetadataConnector`）；EagleRAG 只摄入文件。 |
| `_template` | `plugins/_template/` 下的最小行业 RAG 插件骨架。 |
