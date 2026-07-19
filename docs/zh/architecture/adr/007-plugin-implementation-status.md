# ADR-007: Plugin Architecture Implementation Status

- **Status**: Accepted
- **Date**: 2026-07-14（2026-07-18 修订：encoder label + UMLS MRCONSO + namespace 接线 + BiomedCLIP open_clip + PluginAudit 多 sink）
- **Context**: 补充部署 / 运行时决策，与已落地的 [插件架构](../plugin-architecture.md) 文档配套。

## Decision

1. **Docker packages `plugins/`** in API/worker/MCP images and mounts `./plugins` in compose override so domain plugins are importable without image rebuild in dev.
2. **Deployment profiles** via `EAGLE_RAG_PROFILE=core|biomed|lakehouse-bi` merge `settings.yaml` `profiles:` (P2-4).
3. **Medical encoders never fall back to Qwen3-VL**. Modes: `deterministic` (CI), `require_native` (prod fail-fast), `auto` (native with optional `EAGLE_BIOMED_ALLOW_DETERMINISTIC=1`).
4. **Biomed encoder label 以公开 HF checkpoint 为真实默认**：`pubmedbert` → microsoft/BiomedNLP-PubMedBERT-...、`molformer` → seyonec/ChemBERTa-zinc-base-v1、`medimageinsight` → microsoft/BiomedCLIP-PubMedBERT_256-...（open_clip）、`uni2` → MahmoodLab/UNI2-h。可用 `EAGLE_BIOMED_*_MODEL` 覆盖。**放射（BiomedCLIP）优先走 `open_clip`**（`hf-hub:` + `create_model_from_pretrained` / `get_tokenizer`），图像塔与文本塔同空间，支持对 `eagle_medical_radiology` 的文本→影像 ANN；`transformers` 为回退。病理（`uni2`）仍走 `transformers`。可选 extra：`uv sync --extra biomed` 安装 `open-clip-torch`。Core `eagle_visual` / Qwen 不变。文本+化学编码器不依赖该 extra。
5. **Biomed UMLS** 以可扩充 curated 子集形式发布（~70 实体，`plugins/biomed/routing_rules.yaml` + `umls.py`）；将 `EAGLE_BIOMED_UMLS_MRCONSO_PATH` 指向真实 UMLS MRCONSO RRF 文件（需 NLM 许可证）可合并额外英文别名/CUI。化合物 MCP 使用 `chemical` 编码器在 `eagle_chemical` 上做 ANN。
6. **Lakehouse-bi 仍在开发中**，且保持只读检索；`FileExportLakehouseConnector` 为元数据导出 → 入库的参考用户扩展。非生产就绪。
7. **`plugin_namespace` 接线端到端闭合**：Celery ingest 任务（`knowhere_parse`/`pixelrag_build`/`knowhere_visual_chunks`）、core retriever（`KnowhereGraphRetriever`/`PixelRAGVisualRetriever`）、visual store 读路径（`search_visual`/`count`/`delete`/`fetch`/`distinct_years`）、`RetrieverOrchestrator` core 文本/视觉分路、MCP 检索工具调用点全部贯穿 `plugin_namespace`，使非 core 实例绑定到自有 Milvus Database（G17）。
8. **PluginAudit 为多 sink 决策遥测**（`eagle_rag/plugins/audit.py`）：每次分类/路由/hook 决策扇出到 (1) AI JSONL（`get_ai_logger`，`event=plugin_audit_decision`，持久），(2) Redis LIST 近期窗口（`LPUSH`+`LTRIM`，跨进程），(3) 内存 ring 回退，(4) Prometheus 计数器（`plugin_audit_decisions_total`、`plugin_audit_rrf_dedupe_total`）。`GET /health/plugins` 暴露 `recent_decisions` + `audit_stats`。各 sink 均为 best-effort，不拖垮热路径。Category：`scope_routing` 标签解析失败 → `scope_routing_error`；HookBus `invoke_all` 降级 → `hook_failure`。

## Consequences

- 默认 compose profile 仍为 `core`（对现有部署安全）。
- **`plugins/biomed` 为实验性**；启用需 `EAGLE_RAG_PROFILE=biomed` 并重启；首次原生编码器加载可能拉取 HF 权重。API/collection 可能变更。
- **`plugins/lakehouse_bi` 仍在开发中** — 仅参考骨架；勿视为生产稳定。
- 架构文档描述已实现的微内核（不再是规划蓝图）。

## Follow-up

见 [ADR-008](008-rag-only-plugin-platform.md)：热路径 hook、`plugins.options`、RAG-only MCP、前端 = Core only。
