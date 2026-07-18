# Eval：召回冒烟与全量金标

## 数据集

| 文件 | 规模 | 用途 |
| --- | --- | --- |
| `datasets/eval_queries.smoke.jsonl` | 30 | 日常 `task biomed:eval` |
| `datasets/eval_queries.jsonl` | ≥120（当前 140） | 全量召回回归 |
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

# 全量 + 仅出报告不失败
task biomed:eval EVAL_ARGS='--queries eval/biomed/datasets/eval_queries.jsonl --no-fail'
```

报告写入 `eval/biomed/results/smoke_*.json`。

## 与 e2e 分层

| 命令 | 职责 |
| --- | --- |
| `task biomed:e2e` | profile / KB / 小规模入库 / 一次 search |
| `task biomed:eval` | 金标召回指标 |
