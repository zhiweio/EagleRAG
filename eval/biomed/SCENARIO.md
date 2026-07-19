# 企业场景：和黄医药（HUTCHMED）肿瘤创新药 R&D

## 模拟企业

**和黄医药（HUTCHMED）** 是处于商业化阶段的全球创新型生物医药公司，专注发现、开发及商业化治疗癌症和免疫性疾病的靶向疗法与免疫疗法。

本 eval 将 Eagle-RAG **biomed profile** 部署为该公司内部的「创新药 / 抗肿瘤新药」知识检索层，服务研发调研阶段的文献查阅与医药数据库匹配，而**不是**通用聊天机器人前端（垂类仅后端 + MCP，符合 ADR-008）。

## 知识库

| 字段 | 值 |
| --- | --- |
| `EAGLE_RAG_PROFILE` | `biomed` |
| Milvus DB | `biomed` |
| `kb_name` | `hutchmed` |
| display_name | HUTCHMED Oncology R&D |

## 管线锚点

| 分子 | 别名 | 靶点 | 场景 |
| --- | --- | --- | --- |
| Fruquintinib | HMPL-013, ELUNATE, FRUZAQLA | VEGFR-1/2/3 | mCRC；RCC + PD-1 |
| Savolitinib | HMPL-504, ORPATHYS | MET | EGFR-mut NSCLC + MET amp；+ osimertinib |
| Surufatinib | HMPL-012, SULANDA | VEGFR/FGFR/CSF-1R | NET；PDAC 联合 |

竞品与联合：regorafenib、sunitinib、cabozantinib、lenvatinib、osimertinib、sintilimab、camrelizumab 等。

## 角色与一日工作流（真实场景）

### Discovery

1. 查 VEGFR / MET 通路与耐药综述  
2. `biomed_query_entities("MET")` 扩展别名  
3. `/search` 命中 `eagle_text_biomed` 文献块  

### MedChem

1. 打开化合物卡（SMILES/InChI）  
2. `biomed_retrieve_compounds` 或化学关键词检索  
3. 对照竞品 TKI 结构信息  

### 临床科学

1. ClinicalTrials.gov 衍生 MD（干预 / 终点）  
2. 与全文论文交叉验证联合方案证据  

### 竞品情报

1. 同靶点 TKI 对照查询  
2. 公司公开 pipeline 页面锚定语境  

### 注册事务

1. openFDA 标签适应症 / 警告  
2. FDA / ICH 公开 guidance（终点、GCP）  

详见 `datasets/workflows.yaml`。

## 评测与检索设计

召回金标、smoke 门槛与 aligned 回归见 [EVAL.md](./EVAL.md)。实体锚定检索管线、Milvus 元数据回填与失败诊断见 [RETRIEVAL.md](./RETRIEVAL.md)。
