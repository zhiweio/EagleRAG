# 检索管线与评测运维

本文档描述 HUTCHMED biomed eval 所依赖的**检索设计**、Milvus 元数据回填、失败诊断与已知边界。实现遵循 ADR-008：**Core 不 import 垂类插件**；领域逻辑经 Hook 扩展。

## 检索流水线（live `POST /search`）

```text
QUERY_DENSE_EXPAND (biomed)     # intent + dense 扩写 + sparse_terms
  → ANN per CollectionQueryPlan # PubMedBERT / MolFormer / …
  → hybrid fuse (Core)          # 仅 dense + 词项稀疏；collection 由 EncoderRegistry 声明
  → RERANK (biomed)             # Tier-1 cosine + 实体过滤（plugins/biomed/scoring.py）
RETRIEVE_SUPPLEMENT (biomed)    # 实体锚定补召回（registry 文档名匹配 + 限定 ANN）
  → merge_rrf + dedupe (Core)
RRF_POST_MERGE (biomed)         # require_entity_match 时注入 supplement 候选
  → RERANK_MERGED (biomed)      # MedCPT CE + section / entity 信号
  → final_top_k (5)
```

| 阶段 | 归属 | 模块 |
| --- | --- | --- |
| 查询意图 | biomed | `plugins/biomed/query_intent.py` |
| 路由 | biomed | `plugins/biomed/query_route.py` |
| 稠密扩写 / supplement / RRF 注入 / 合并重排 | biomed | `plugins/biomed/retrieval_hooks.py` |
| 实体打分 | biomed | `plugins/biomed/scoring.py` |
| RRF / inject 原语 | Core | `eagle_rag/router/rerank_fusion.py` |
| 编排（无 biomed import） | Core | `eagle_rag/plugins/retriever_orchestrator.py` |

### 查询意图（非 eval workflow 标签）

`detect_retrieval_intent()` 仅从**查询文本**推断，不用金标里的 `workflow` 字段：

| workflow | 触发条件 | 行为摘要 |
| --- | --- | --- |
| `chemical` | SMILES / compound / molecular formula 等 | 路由 `eagle_chemical`；`require_entity_match` |
| `regulatory` | drug label / prescribing / indications and usage 等 | 抑制 chemical；章节 cue |
| `combination` | 多药 + combination  cue | 可含 visual |
| `drug_entity` | UMLS 药物实体命中 | 实体锚定 + supplement |
| `general` | 兜底 | 无强制实体匹配 |

### 实体锚定补召回

`supplement_entity_anchored_hits`：用 `lookup_document_ids_by_name_terms` 在 PG registry 按药名找文档，再在 `eagle_text_biomed` / `eagle_chemical` 内做限定 ANN。不依赖 `label_*` / `compound_*` 文件名前缀。

`RRF_POST_MERGE` 在 `require_entity_match=True` 时将 supplement Top 命中注入 rerank 候选池（`inject_supplement_candidates`）。

### Hybrid 稀疏融合

- Core `hybrid_fuse_dense_sparse`：**仅**稠密 ANN + 词项重叠，无领域实体逻辑。
- 哪些 collection 做 hybrid：优先 `settings.router.hybrid_text_collections`（biomed profile 默认 `eagle_text_biomed`、`eagle_text_medcpt`），否则 `EncoderRegistry.register_collection(..., hybrid_enabled=True)`。
- biomed 的 `sparse_terms`（药名、章节 cue）经 `QUERY_DENSE_EXPAND` 传入 hybrid。

## Milvus 元数据（ingest 后可选回填）

| 字段 | 来源 | 回填脚本 |
| --- | --- | --- |
| `primary_drugs` | CHUNK hook / 稀疏融合 | `task biomed:reindex-sparse` |
| `biomed_section` | CHUNK hook（Knowhere path） | 见下方 `reindex_biomed_metadata.py` |

在**宿主机**直连 Milvus / Postgres 时：

```bash
export MILVUS_HOST=localhost
export EAGLE_RAG_PROFILE=biomed
export PLUGIN_NAMESPACE=biomed

# primary_drugs
task biomed:reindex-sparse

# biomed_section（从 path 推断章节）
uv run python eval/biomed/scripts/reindex_biomed_metadata.py --kb-name hutchmed
```

容器内 API 已挂载 `plugins/` 时，改代码后 `docker compose restart api` 即可；Milvus 回填一般在宿主机执行。

可选 MedCPT 双索引（默认关闭 `medcpt_dual_search: false`）：

```bash
uv run python eval/biomed/scripts/reindex_medcpt.py --kb-name hutchmed
```

## 当前回归基线（aligned smoke，46 条）

报告：`results/smoke_20260719T054615Z.json`（`eval_queries.aligned.jsonl`）

| 指标 | 结果 | Smoke 门槛 |
| --- | --- | --- |
| Hit@5 | **0.87** | ≥ 0.70 |
| Recall@5 | **0.87** | ≥ 0.50 |
| MRR | **0.85** | ≥ 0.55 |
| Term coverage | **0.87** | ≥ 0.80 |

相对优化前（`smoke_20260719T050921Z`：hit@5=0.65，MRR=0.43），原 16 条 `ranking_gap` 已全部过线。

### 仍失败的 6 条（expansion / 数据或 UMLS 缺口）

| ID | 类型 | 根因（诊断） |
| --- | --- | --- |
| q-exp-042 | competitive_intelligence | 金标在库；UMLS 未覆盖 gefitinib → 无实体锚定；PubMedBERT 召回未进 Top-50 |
| q-exp-043 | compound_match | 金标在 `eagle_chemical`；Molformer 对空 SMILES 卡召回弱 |
| q-exp-049 | competitive_intelligence | 金标仅 `eagle_chemical`；text 路由未搜 chemical collection |
| q-exp-050 / q-exp-052 | compound_match | capmatinib / tepotinib 缺 `name_aliases` SMILES；Molformer 未进 Top-50 |
| q-exp-053 | competitive_intelligence | everolimus 在 UMLS 但 `_resolve_drug_terms` 误用 related_drugs |

详见 `results/diagnosis_smoke8_20260719T060327Z.md`。公平回归仍以 **aligned** 子集为准；上述 6 条为扩展题，修复方向是 UMLS 补全、compound 卡 SMILES、化学路由而非 Core 耦合。

## 失败诊断

```bash
uv run python eval/biomed/scripts/diagnose_retrieval.py \
  --queries eval/biomed/datasets/eval_queries.aligned.jsonl \
  --report eval/biomed/results/smoke_<latest>.json
```

| `failure_class` | 含义 |
| --- | --- |
| `gold_corpus_gap` | 语料 / KB 无金标文件 |
| `gold_over_specified` | 金标文件名在语料中不全 |
| `query_route_gap` | 金标仅在 chemical，text 模式未路由到 |
| `ranking_gap` | 金标在库但 Top-K 未命中（含召回未入池） |
| `term_metric_strict` | 命中金标文档但 must 词未覆盖 |
| `ok` | 通过 |

## 相关文档

- [EVAL.md](./EVAL.md) — 金标字段与 smoke 命令
- [SETUP.md](./SETUP.md) — 栈与环境
- [docs/en/architecture/plugin-architecture.md](../../docs/en/architecture/plugin-architecture.md) — Hook 与 Core/插件边界
- [docs/en/backend/router-engine.md](../../docs/en/backend/router-engine.md) — RouterEngine 与 RetrieverOrchestrator
