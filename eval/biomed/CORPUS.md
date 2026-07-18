# 语料：约 300 篇抗肿瘤创新药公开资料

## 质量门禁（重要）

早期版本曾在 PDF 失败时把**摘要**写成 `papers/*.md`，导致「300 篇」多为短 Markdown。现已修正：

| 类型 | 最低质量要求 |
| --- | --- |
| **paper** | 仅 OA **全文**：PDF ≥ 40KB，或 Europe PMC `fullTextXML` 转 MD ≥ 6k 字符；**禁止**摘要充数；跳过 erratum/correction |
| abstract | 完整摘要 ≥ 800 字符（明确标注为 abstract，非全文） |
| trial | 含 brief/detailed description + eligibility 等，全文 ≥ 1.5k 字符 |
| guidance | 优先真实 PDF |

清理瘦文献并重下全文：

```bash
export BIOMED_HTTP_PROXY=http://127.0.0.1:1087 BIOMED_SSL_INSECURE=1
uv run python eval/biomed/corpus/download_corpus.py \
  --local-proxy --insecure-ssl --purge-thin --only papers
```

## 配额（`corpus/manifest.yaml`）

| 类型 | source_type | 配额 | 来源 |
| --- | --- | --- | --- |
| A 全文 | paper | 120 | Europe PMC OA PDF / fullTextXML（HAS_PDF） |
| B 摘要 | abstract | 80 | Europe PMC 长摘要（证据池，非全文替代） |
| C 试验 | trial | 40 | ClinicalTrials.gov API v2（富字段） |
| D 化合物 | compound | 30 | PubChem PUG |
| E 标签 | label | 20 | openFDA |
| F 指导原则 | guidance | 15 | FDA / ICH 公开 PDF |
| G 企业公开 | company | 15 | HUTCHMED 公开页 |
| **合计** | | **≈300** | |

落盘目录（gitignore）：`assets/biomed/hutchmed/{papers,abstracts,trials,compounds,labels,guidance,company}/`  
锁文件：`eval/biomed/corpus/manifest.lock.json`（本地生成，gitignore）。

## 下载

```bash
# 全量（耗时与网络相关，支持断点续跑）
task biomed:corpus

# 冒烟子集
task biomed:corpus CORPUS_ARGS='--limit 40'

# 只拉化合物 + 试验
task biomed:corpus CORPUS_ARGS='--only compounds --only trials'
```

### 大陆访问外网卡住时：本地 HTTP 代理

Europe PMC / PubChem / FDA / ClinicalTrials.gov 等外网源在境内可能超时。脚本支持本地 HTTP 代理（常见 Clash/V2Ray 端口 `1087`）：

```bash
# 推荐：环境变量（对 HF datasets 等子库也生效）
export BIOMED_HTTP_PROXY=http://127.0.0.1:1087
# 若代理做 HTTPS MITM 导致 CERTIFICATE_VERIFY_FAILED：
export BIOMED_SSL_INSECURE=1
task biomed:corpus

# 或 CLI
task biomed:corpus CORPUS_ARGS='--local-proxy --insecure-ssl'
# 等价于:
uv run python eval/biomed/corpus/download_corpus.py \
  --proxy http://127.0.0.1:1087 --insecure-ssl
```

优先级：`--proxy` / `--local-proxy` → `BIOMED_HTTP_PROXY` → `HTTPS_PROXY` / `HTTP_PROXY`。

脚本：`corpus/download_corpus.py`（幂等：按 sha256 跳过已存在文件）。

## 入库建议（真实负载）

1. 先入库 D+C+fixtures（快）→ `task biomed:e2e`  
2. 再入库 A/B 主体（Knowhere 解析耗时）  
3. 最后 E/F/G  

`run_e2e.py --ingest-limit N` 可控制单次冒烟入库文件数；全量入库可对 `assets/biomed/hutchmed` 写循环脚本或多次调用 `/ingest`。

## HF 缓存

可选摘要填充使用 `datasets` streaming（Context7：`streaming` + `filter`）；缓存目录 `data/biomed/hf/`。无 `datasets` 包时自动跳过 HF，不影响 Europe PMC 摘要配额。
