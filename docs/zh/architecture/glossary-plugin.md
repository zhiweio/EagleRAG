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
| Encoder label | Biomed 运行时名：`pubmedbert`（768）、`molformer`（768）、`medcpt-query` / `medcpt-article`（768）、`medcpt-rerank`（交叉编码器）、`medimageinsight`（1024 BiomedCLIP/`open_clip`）、`uni2`（1536）。 |
| Encoder mode | `auto` / `require_native` / `deterministic` - 医学编码器永不使用 Qwen3-VL。`EAGLE_BIOMED_ALLOW_DETERMINISTIC=1` 控制 `auto` 模式下的哈希回退。 |
| TDR | 分层文档路由器（`plugins/biomed/doc_profile.py`）- 3 层 biomedical/general 分类，决定用 PubMedBERT 还是 Core `text-embedding-v4`。 |
| 原型余弦差 | TDR Tier-1 信号：`score_bio - score_gen`（PubMedBERT 嵌入与 biomedical/general 原型向量的余弦）。 |
| IMRaD 章节标签 | `chunker.biomed_chunk_transform` 写入的 `biomed_section` 元数据（`abstract` / `methods` / `results` / `claims` / `indications_and_usage` / `warnings` / `dosage` / `body`）。 |
| `primary_drugs` | 入库时写入的节点级药物列表（最多 8）；查询时支持零重扫的 `entity_boost_score`。 |
| MedCPT CE | Tier-2 `RERANK_MERGED` 用的 `medcpt-rerank` 交叉编码器（min-max 归一化 logits）。 |
| 跨药惩罚 | Tier-2 信号：`primary_drugs` 元数据与查询药物不相交时为 1.0；乘以 `w_xdrug_penalty`（2.0-3.0）后减去。 |
| 实体锚定补召回 | `supplement_entity_anchored_hits` - PG registry 名查询 + 限定 ANN；文件名无关。`require_entity_match` 时经 `RRF_POST_MERGE` 注入。 |
| 字母边界匹配 | `umls._entity_pattern` - `EGFR` 不会在 `VEGFR` 内命中，`MET` 不会在 `metastatic` 内命中；`VEGFR` 仍能匹配 `VEGFR1-3`，`PD-1` 保留。 |
| 化学再重排 | Tier-2 `chemical` 工作流特殊路径：对实体匹配节点用 MolFormer 余弦重排；取 (融合, MolFormer) 中较高者。 |
| `exclusive_group` | `ClassificationDecision` 字段；同组内跳过 dual-write（如 `biomed_text` -> `eagle_text_biomed` 与 `eagle_text` 二选一）。 |
| 重排策略 | `domain`（插件 `RERANK_MERGED`）/ `general`（Core `qwen3-rerank`）/ `none`（透传）。Biomed 默认：`domain`。 |
| BiomedCLIP / `open_clip` | `medimageinsight` 编码器经 `open_clip` 加载，文本塔与图像塔共享同一嵌入空间（支持文本 -> 影像跨模态检索）。 |
| `EAGLE_BIOMED_*` 环境变量 | `EAGLE_BIOMED_ENCODER_MODE`、`EAGLE_BIOMED_ALLOW_DETERMINISTIC`、`EAGLE_BIOMED_*_MODEL`（checkpoint 覆盖）、`EAGLE_BIOMED_UMLS_MRCONSO_PATH`、`EAGLE_BIOMED_OPENCLIP_ARCH`/`_PRETRAINED`。 |
| UMLS 子集 | `plugins/biomed/routing_rules.yaml` + `umls.py` 中的精选本体，供 G15 路由 + MCP。 |
| MRCONSO 合并 | 可选 `EAGLE_BIOMED_UMLS_MRCONSO_PATH` — 合并 ENG + `ISPREF=Y` 别名/CUI（需 NLM 许可）。 |
| PluginAudit | 多 sink 决策遥测（`audit.py`）：AI JSONL + Redis `eagle:plugin_audit:{ns}:recent` + 内存 ring + Prometheus。 |
| Audit category | 如 `classify_chunk`、`route_query`、`scope_routing_error`、`hook_failure`。 |
| Lakehouse connector | 用户自有导出器（`LakehouseMetadataConnector`）；EagleRAG 只摄入文件。 |
| `_template` | `plugins/_template/` 下的最小行业 RAG 插件骨架。 |
