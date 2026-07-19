# Eval：召回冒烟与全量金标

## 数据集

| 文件 | 规模 | 用途 |
| --- | --- | --- |
| `datasets/eval_queries.smoke.jsonl` | 30 | 日常 `task biomed:eval` |
| `datasets/eval_queries.jsonl` | corpus-aligned 全量集（约 55，随语料变化） | 全量召回回归 |
| `datasets/eval_queries.aligned.jsonl` | 审计为 aligned 的子集 | 公平检索回归（不含缺语料金标） |
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

## 指标（对 live `POST /search`）

| 指标 | Smoke（native） | Smoke（deterministic / offline） | Full 建议 |
| --- | --- | --- | --- |
| Hit@K | ≥ 0.70 | ≥ 0.20 | ≥ 0.65 |
| Recall@K | ≥ 0.50 | ≥ 0.15 | ≥ 0.45 |
| MRR | ≥ 0.55 | ≥ 0.15 | ≥ 0.50 |
| Term coverage | ≥ 0.80 | ≥ 0.50 | ≥ 0.80 |
| NonLLMContextRecall | 记录（≥0.40 参考） | 记录 | 记录 |

`EAGLE_BIOMED_ENCODER_MODE=deterministic` 时 `run_eval_smoke.py` 自动改用 offline 门槛（hash 向量无语义，仅验证端到端通路）。  
Native 门槛需要可用的 PubMedBERT 权重 + DashScope `text-embedding-v4`（账号欠费会导致 Core `eagle_text` 召回为空）。

实现：`scripts/metrics.py` + `scripts/run_eval_smoke.py`。  
Ragas `NonLLMContextRecall` 可选；未安装时回退到词项重叠（Context7）。

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

## 金标与语料对齐

`generate_eval_queries.py` 会扫描 `assets/biomed/hutchmed/`，仅生成语料中存在的 `expected_doc_name_substrings`，并跳过无摘要/试验正文的 literature/clinical 扩展题（例如仅有 compound 卡的药物）。

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

全量 140 条原始金标可能包含已删除药物（如 `camrelizumab`）或 workflow 与语料类型不符的条目；**公平回归请用 aligned 子集**。

## Compound eval mode

`compound_match` 条目带 `route_hint.collections: ["eagle_chemical"]`；药物名 UMLS 命中也会路由 chemical。`run_eval_smoke.py` 在 `respect_route_hint` 下对含 `eagle_chemical` 的条目使用 `mode=hybrid`（`eagle_text_biomed` + `eagle_chemical` RRF）。

## 检索失败诊断

对 smoke 未满分 query 做根因分类（语料缺口 / 路由缺口 / 排序 / 金标过严）：

```bash
uv run python eval/biomed/scripts/diagnose_retrieval.py \
  --report eval/biomed/results/smoke_<latest>.json
```

产出 `results/diagnosis_smoke8_*.json` 与 `.md`；`failure_class` 取值见脚本内注释。

## 与 e2e 分层

| 命令 | 职责 |
| --- | --- |
| `task biomed:e2e` | profile / KB / 小规模入库 / 一次 search |
| `task biomed:eval` | 金标召回指标 |
