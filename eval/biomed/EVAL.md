# Eval：召回冒烟与全量金标

## 数据集

| 文件 | 规模 | 用途 |
| --- | --- | --- |
| `datasets/eval_queries.smoke.jsonl` | 30 | 日常 `task biomed:eval` |
| `datasets/eval_queries.jsonl` | corpus-aligned 全量集（约 55，随语料变化） | 全量召回回归 |
| `datasets/eval_queries.aligned.jsonl` | 审计为 aligned 的子集（**46**） | 公平检索回归（推荐 CI） |
| `datasets/eval_queries.smoke.aligned.jsonl` | smoke 中 aligned 子集 | 冒烟公平回归 |
| `datasets/workflows.yaml` | — | 多角色工作流说明 |
| `datasets/compounds.json` | — | 管线/竞品化合物元数据 |

重新生成：

```bash
uv run python eval/biomed/scripts/generate_eval_queries.py
```

### 金标字段

```json
{
  "id": "q-seed-001",
  "workflow": "literature_review",
  "role": "discovery",
  "query": "...",
  "must_include_terms": ["fruquintinib", "VEGFR"],
  "expected_doc_name_substrings": ["fruquintinib"],
  "route_hint": {"umls": ["VEGFR"], "collections": ["eagle_text_biomed"]},
  "k": 5
}
```

- `workflow` / `role`：**仅用于数据集分层与报告**；线上检索意图由 `plugins/biomed/query_intent.py` 从查询文本推断，不读取此字段。
- `route_hint.collections`：含 `eagle_chemical` 时 eval 使用 `mode=hybrid`（见下文）。

## 指标（对 live `POST /search`）

| 指标 | Smoke（native） | Smoke（deterministic / offline） | Aligned 回归 |
| --- | --- | --- | --- |
| Hit@K | ≥ 0.70 | ≥ 0.20 | ≥ 0.65 (`biomed:eval:aligned`) |
| Recall@K | ≥ 0.50 | ≥ 0.15 | — |
| MRR | ≥ 0.55 | ≥ 0.15 | — |
| Term coverage | ≥ 0.80 | ≥ 0.50 | — |
| NonLLMContextRecall | 记录（≥0.40 参考） | 记录 | 记录 |

`EAGLE_BIOMED_ENCODER_MODE=deterministic` 时 `run_eval_smoke.py` 自动改用 offline 门槛（hash 向量无语义，仅验证端到端通路）。  
Native 门槛需要可用的 PubMedBERT 权重 + 运行中的 biomed API 栈。

实现：`scripts/metrics.py` + `scripts/run_eval_smoke.py`。  
Ragas `NonLLMContextRecall` 可选；未安装时回退到词项重叠。

### 当前基线（aligned，2026-07-19）

`eval_queries.aligned.jsonl`（46 条）在实体锚定检索优化后：

| 指标 | 值 |
| --- | --- |
| Hit@5 / Recall@5 | 0.87 |
| MRR | 0.85 |
| Term coverage | 0.87 |
| 失败数 | 6（均为 expansion 题，见 [RETRIEVAL.md](./RETRIEVAL.md)） |

报告文件：`results/smoke_20260719T054615Z.json`。

## 运行

```bash
# 需 biomed 栈已启动且语料已入库
task biomed:eval

# aligned 公平回归（CI 门槛 Hit@K ≥ 0.65）
task biomed:eval:aligned

# 金标文件名 oracle（语料覆盖上限，非 live 检索）
task biomed:eval:oracle

# 全量 + 仅出报告不失败
task biomed:eval EVAL_ARGS='--queries eval/biomed/datasets/eval_queries.jsonl --no-fail'
```

报告写入 `eval/biomed/results/smoke_*.json`。

**评测前建议**（首次部署或 Milvus 存量数据）：

```bash
export MILVUS_HOST=localhost EAGLE_RAG_PROFILE=biomed PLUGIN_NAMESPACE=biomed
task biomed:reindex-sparse
uv run python eval/biomed/scripts/reindex_biomed_metadata.py --kb-name hutchmed
```

## 金标与语料对齐

`generate_eval_queries.py` 会扫描 `assets/biomed/hutchmed/`，仅生成语料中存在的 `expected_doc_name_substrings`，并跳过无摘要/试验正文的 literature/clinical 扩展题。

审计与 aligned 子集：

```bash
uv run python eval/biomed/scripts/audit_gold_corpus.py
# 产出 datasets/eval_queries.aligned.jsonl
#      datasets/eval_queries.smoke.aligned.jsonl
#      results/gold_audit_*.json / .md
```

对齐标签：

| 标签 | 含义 |
| --- | --- |
| `aligned` | 文件名、must 词项、workflow 文档类型均匹配 |
| `partial` | 有文件名匹配但正文词项或文档类型不符 |
| `absent` | 语料中无 expected 文件名 |

公平回归请用 **aligned** 子集；全量集可能含已删除药物或 workflow 与语料类型不符的条目。

## Compound eval mode

`compound_match` 条目带 `route_hint.collections: ["eagle_chemical"]`；查询侧化学意图也会路由 `eagle_chemical`。`run_eval_smoke.py` 在 `respect_route_hint` 下对含 `eagle_chemical` 的条目使用 `mode=hybrid`。

## 检索失败诊断

```bash
uv run python eval/biomed/scripts/diagnose_retrieval.py \
  --queries eval/biomed/datasets/eval_queries.aligned.jsonl \
  --report eval/biomed/results/smoke_<latest>.json
```

产出 `results/diagnosis_smoke8_*.json` 与 `.md`。`failure_class` 说明见 [RETRIEVAL.md](./RETRIEVAL.md)。

脚本会对比：语料文件、KB registry、`POST /search` text/hybrid Top-5、本地 intent 预览。

## 与 e2e 分层

| 命令 | 职责 |
| --- | --- |
| `task biomed:e2e` | profile / KB / 小规模入库 / 一次 search |
| `task biomed:eval` | 金标召回指标 |
| `task biomed:eval:aligned` | aligned 子集 + Hit@K 门槛 0.65 |

检索设计与 Hook 边界详见 [RETRIEVAL.md](./RETRIEVAL.md)。
