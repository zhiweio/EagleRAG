# HUTCHMED Biomed 垂类 RAG 端到端与 Eval

本目录包含**和黄医药（HUTCHMED）肿瘤创新药研发**场景下的 biomed 插件端到端部署说明、约 300 篇公开语料下载、召回评测金标与冒烟脚本。

> 不修改默认 `.env`（core）。使用独立 `.env.biomed`。Core 视觉嵌入固定 **DashScope**（`VISUAL_EMBEDDING_PROVIDER=dashscope`），不使用 PixelRAG 本地嵌入模型。

## 快速开始

```bash
# 0) 依赖（垂类编码器）
uv sync --extra biomed

# 1) 生成/更新 .env.biomed（从 .env 复制密钥并覆盖 profile）
task biomed:env
# 确认 DASHSCOPE_API_KEY / LLM / VLM 已填写

# 2) 停掉 core 栈后启动 biomed
task down          # 若 core 正在跑
task biomed:up
task biomed:health

# 3) 下载公开语料（≈300；可先 --limit 40 冒烟）
export BIOMED_HTTP_PROXY=http://127.0.0.1:1087   # 大陆外网按需
export BIOMED_SSL_INSECURE=1
task biomed:corpus

# 4) 入库后（可选）回填 Milvus 检索元数据
export MILVUS_HOST=localhost EAGLE_RAG_PROFILE=biomed PLUGIN_NAMESPACE=biomed
task biomed:reindex-sparse
uv run python eval/biomed/scripts/reindex_biomed_metadata.py --kb-name hutchmed

# 5) 部署冒烟 + 召回 eval
task biomed:e2e
task biomed:eval
task biomed:eval:aligned   # 推荐：46 条 aligned 公平回归
```

## 文档索引

| 文档 | 内容 |
| --- | --- |
| [SCENARIO.md](./SCENARIO.md) | 企业场景、角色、真实研发工作流 |
| [SETUP.md](./SETUP.md) | 环境、与 core 切换、DashScope visual |
| [CORPUS.md](./CORPUS.md) | 300 篇配额、来源、下载与入库 |
| [SOURCES.md](./SOURCES.md) | 许可与合规 |
| [EVAL.md](./EVAL.md) | 金标字段、指标、smoke vs full |
| [RETRIEVAL.md](./RETRIEVAL.md) | 检索管线、Hook 边界、元数据回填、诊断与已知失败 |

架构级说明（中英）：[`docs/en/architecture/plugin-architecture.md`](../../docs/en/architecture/plugin-architecture.md)、[`docs/zh/architecture/plugin-architecture.md`](../../docs/zh/architecture/plugin-architecture.md)。

## 目录结构

```text
eval/biomed/
  corpus/           # manifest + download_corpus.py
  datasets/         # eval_queries*.jsonl, workflows, compounds
  scripts/          # e2e / eval / diagnose / reindex / metrics
  fixtures/         # 可提交的最小样例 MD
  results/          # 评测报告（gitignore）
```

## 验收清单

- [ ] `GET /health/plugins` → `default_namespace=biomed`
- [ ] MCP 工具列表含 `biomed_query_entities`、`biomed_retrieve_compounds`
- [ ] `VISUAL_EMBEDDING_PROVIDER=dashscope`
- [ ] 语料入库 `kb_name=hutchmed`，`plugin_namespace=biomed`
- [ ] `task biomed:reindex-sparse` + `reindex_biomed_metadata.py` 已执行（存量 KB）
- [ ] `task biomed:eval:aligned` 过线（Hit@5 ≥ 0.65；当前基线约 0.87 / MRR 0.85，见 EVAL.md）
