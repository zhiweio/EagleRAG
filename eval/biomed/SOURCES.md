# 语料来源与许可

仅使用**公开可复现**来源，模拟药企资料类型；**不含**和黄内部非公开 IND/CSR/IB。

| 来源 | 用途 | 合规要点 |
| --- | --- | --- |
| Europe PMC / PMC OA | 全文与摘要 | 仅 OA；遵守 [PMC OA](https://pmc.ncbi.nlm.nih.gov/tools/openftlist/) 与各篇 license |
| ClinicalTrials.gov | 试验登记 MD | 公共 API；保留 NCT 与出处 URL |
| PubChem | 化合物卡 | 公共领域化学信息 |
| openFDA | 标签摘要 | FDA 开放数据 |
| FDA / ICH guidance | 注册指导原则 | 公开 PDF；保留原 URL |
| HUTCHMED 官网 | 管线/简介 | 仅公开页；HTML→MD 注明 URL，不做大段再分发 |
| Hugging Face PubMed 流 | 摘要补充 | 可选；遵循数据集与 PubMed 使用条款 |

## 禁止

- 系统化抓取非 OA 全文（绕过 PMC/Europe PMC 官方通道）
- 入库付费数据库导出或内部机密
- 将大体积 PDF 提交进 git（应留在 `assets/`）

下载脚本默认 `User-Agent: eagle-rag-biomed-eval/1.0`，并带间隔限速。
