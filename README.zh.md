<div align="center">

  <img
    src="docs/images/banner.png"
    alt="Eagle-RAG — 面向更智能 AI 应用的企业级 RAG 平台"
    width="1000"
    style="max-width: 1000px; width: 100%; height: auto;"
  />

  <h1>Eagle-RAG</h1>

  <p>
    <a href="https://github.com/zhiweio/EagleRAG/stargazers"><img src="https://img.shields.io/github/stars/zhiweio/EagleRAG?style=social" alt="GitHub stars"/></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg" alt="License"/></a>
    <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.12+-blue.svg" alt="Python"/></a>
  </p>

  <p>
    <img src="https://img.shields.io/badge/Milvus-2.6-00A6FB?logo=milvus&logoColor=white&style=flat-square" alt="Milvus"/>
    <img src="https://img.shields.io/badge/LlamaIndex-RAG-0A0A0A?style=flat-square" alt="LlamaIndex"/>
    <img src="https://img.shields.io/badge/Knowhere-Ontos--AI-9F2B68?style=flat-square" alt="Knowhere"/>
    <img src="https://img.shields.io/badge/PixelRAG-StarTrail--org-8A2BE2?style=flat-square" alt="PixelRAG"/>
    <img src="https://img.shields.io/badge/MinerU-OpenDataLab-FF6B35?style=flat-square" alt="MinerU"/>
    <img src="https://img.shields.io/badge/MCP-HTTP+stdio-6366F1?style=flat-square" alt="MCP"/>
  </p>

  <p>
    <a href="https://zhiweio.github.io/EagleRAG/zh/"><strong>文档</strong></a>
    ·
    <a href="https://youtu.be/Bj6lI48p7Zw"><strong>演示</strong></a>
    ·
    <a href="README.md">English</a> | <a href="README.zh.md">中文</a>
  </p>

</div>

> **语义纵深 · 视觉澄明**
>
> 按文档「所说」与「所见」检索知识——而非二选一。  
> 将 Knowhere 语义分块与 PixelRAG 像素原生感知织入同一多租户数据层，点亮 Agent 智能。

Eagle-RAG 采用 **微内核 + 同仓插件**：Core（`namespace=core`）提供入库、多模态检索与 MCP（`core_*`）；领域插件经 `EAGLE_RAG_PROFILE` / `settings.plugins.enabled` + `default_namespace` 扩展 hooks、编码器与 MCP。**`plugins/biomed` 为实验性**；**`plugins/lakehouse_bi` 仍在开发中**。**内置前端 = Core knowhere+pixelrag 橱窗**；垂类为 **后端 + MCP**，供下游 Agent 消费。见 [插件架构](docs/zh/architecture/plugin-architecture.md)、[ADR-008](docs/zh/architecture/adr/008-rag-only-plugin-platform.md)、[二开指南](docs/zh/guides/authoring-industry-plugin.md)。
上传 PDF、Office、扫描件或网页即可——Eagle-RAG 同时理解正文与图表版式。回答流式返回、附可核对出处；多个团队可各建知识库，数据彼此隔离。

## 工作原理

<p align="center">
  <img
    src="docs/images/eaglerag-pipeline.png"
    alt="Eagle-RAG 管线图"
    width="1000"
    style="max-width: 1000px; width: 100%; height: auto; object-fit: contain;"
  />
</p>

## 眼见为实

[在 YouTube 观看演示](https://youtu.be/Bj6lI48p7Zw) —— 多模态问答与可核对引用。

## 核心能力

- **双摄取管线** —— [Knowhere](https://github.com/Ontos-AI/knowhere)（外部 HTTP 服务 `:5005`，经官方 `knowhere-python-sdk` 调用）负责文本 / 结构化文档（PDF 文本版 / Word / Excel / CSV / PPTX / Markdown / txt / json）；**PixelRAG**（进程内库 `pixelrag_render` + `pixelrag_embed`）负责扫描版 PDF / 图片 / 网页。
- **双层隔离** —— 部署将 `plugin_namespace` 绑定到独立 Milvus **Database**（+ PG repository 过滤）；域内再用 `kb_name` 标量过滤知识库。去重 PK 为 `(sha256, kb_name, plugin_namespace)`。多行业 = 多实例（`EAGLE_RAG_PROFILE`），不做运行时领域切换。
- **混合检索** —— 在领域 Database 内做多 collection ANN（基础 `eagle_text` / `eagle_visual`，以及可选专用 collection），跨编码器 RRF 合并，文本节点图扩展，并支持 `kb_name` / `document_id` / `year` / `source_type` 等标量过滤。
- **多模态生成** —— DeepSeek-V4-Pro 负责路由与文本生成；Qwen-VL-Max 在文本分块与图像切片之上生成回答，并由 qwen3-rerank 重排。
- **MCP 工具服务器** —— 默认通过 streamable HTTP（`/mcp`）暴露 `core_ingest` / `core_query` / `core_retrieve_text` / `core_retrieve_visual`，可降级 stdio；领域 profile 追加 `{namespace}_*` RAG 工具。
- **可观测运维** —— 并发依赖探测（`/admin/probes`）、实时 SSE 日志流、队列指标时间序列，以及各服务管理面板。

## 系统架构

```
                         CLIENT TIER
              ┌─────────────────┐   ┌─────────────────┐
              │  Next.js UI     │   │ External Agents │
              │  QA·Ingest·KB   │   │  (MCP / HTTP)   │
              └────────┬────────┘   └────────┬────────┘
                       │ REST / SSE          │ MCP
                       └──────────┬──────────┘
                                  ▼
              ┌───────────────────────────────────────────┐
              │  FastAPI :8000  —  REST · SSE · MCP       │
              │  PluginManager · HookBus · Orchestrators  │
              │  Router Engine → Multimodal Engine        │
              └───────┬───────────────────────┬───────────┘
                      │ query / retrieve      │ ingest
                      │                       ▼
                      │            ┌──────────────────────┐
                      │            │  Celery workers      │
                      │            │  router_queue    ×4  │
                      │            │  knowhere_queue  ×8  │
                      │            │  pixelrag_queue  ×1  │
                      │            └──────┬───────┬───────┘
                      │                   │       │
                      │                   ▼       ▼
                      │     ┌─────────────────────────┐ ┌──────────┐
                      │     │ Knowhere (KNOWHERE_MODE)│ │ PixelRAG │
                      │     │  api    → HTTP :5005    │ │ in-proc  │
                      │     │  parser → parse-sdk     │ │ render   │
                      │     │  text + KG              │ │          │
                      │     └───────────┬─────────────┘ └────┬─────┘
                      │         1536d text│           2048d visual
                      │                 └──────┬─────┘
                      ▼                        ▼
              ┌───────────────────────────────────────────┐
              │  STORAGE（按 plugin_namespace）           │
              │  Milvus DB    eagle_text + eagle_visual   │
              │               [+ 专用 collections]        │
              │  PostgreSQL   namespace 注入的 repositories │
              │  MinIO        原件 · 视觉切片             │
              │  Redis 7      Celery broker · task logs   │
              └───────────────────────────────────────────┘
```

基础设施：Milvus（每个 `plugin_namespace` 一个 **Database**）+ PostgreSQL（namespace 作用域 repositories）+ Redis + MinIO。Knowhere 后端由 `KNOWHERE_MODE` 选择（`api` = `knowhere-python-sdk` → HTTP `:5005`；`parser` = 进程内 `knowhere-parse-sdk`）。

## 技术栈

| 层 | 技术 |
| --- | --- |
| **后端** | Python ≥ 3.12, FastAPI, Celery 5, LlamaIndex, Pydantic v2, SQLModel, Alembic |
| **前端** | Next.js 16 (App Router), React 19, TypeScript 5, HeroUI v3, Tailwind v4, TanStack Query, Zustand 5, next-intl（zh / en，light-only） |
| **AI 模型** | DeepSeek-V4-Pro（文本 LLM / 路由）、Qwen-VL-Max（VLM）、`text-embedding-v4`（文本 1536 维）、Qwen3-VL 视觉嵌入 2048 维经 `get_visual_encoder()`（`provider=pixelrag` 本地 HF 或 `dashscope` 百炼）、`qwen3-rerank`（rerank）。仅 DeepSeek + Qwen 系列，无 OpenAI / Cohere。 |
| **基础设施** | Milvus 2.6（按 `plugin_namespace` 分 Database；基础 `eagle_text` + `eagle_visual`）, PostgreSQL 16, Redis 7, MinIO, Docker Compose |
| **集成** | MCP（Model Context Protocol）over HTTP（默认 `/mcp`）+ stdio 降级, OpenAPI 生成的 TypeScript SDK |

> **多模态融合架构**：视觉切片经 Milvus 内置 HNSW / DiskANN 引擎（替代 PixelRAG 原生 FAISS）存储于 `eagle_visual`，并以语义树锚定四字段（`chunk_type` / `parent_section` / `content_summary` / `source_chunk_id`）回挂 Knowhere 语义树——详见 [多模态融合架构](docs/zh/architecture/multimodal-fusion.md)。

## 环境前置条件

### 运行时依赖

| 依赖 | 说明 |
| --- | --- |
| Python ≥ 3.12 | 后端运行时，包管理用 [`uv`](https://docs.astral.sh/uv/) |
| Node.js + Bun | 前端运行时与包管理（`bun install`） |
| Docker + Docker Compose | 一键启动全栈（含基础设施） |
| Milvus 2.6+ | 向量库；按领域一个 Database；基础 `eagle_text`（1536 维）/ `eagle_visual`（2048 维） |
| PostgreSQL 16 | 会话 / 去重 / 任务审计 |
| Redis 7 | Celery broker / result backend |
| MinIO | Tile PNG 与原始文件对象存储 |

### 外部服务

- **Knowhere `:5005`**：文档语义解析引擎（[Ontos-AI/knowhere](https://github.com/Ontos-AI/knowhere)），需独立部署并对外暴露 `:5005`。Eagle-RAG 通过官方 `knowhere-python-sdk`（`KNOWHERE_BASE_URL` 默认 `http://localhost:5005`）调用 `client.parse()`，经 `/v1/jobs` 同步返回内存态 `ParseResult`，全程不落盘 `~/.knowhere/`。SDK 不可达时 fail-closed：抛 `KnowhereError` 并将任务置为 `FAILED`，不回退 mock。
  > 注意区分：新版 Milvus 已内置 HNSW / DiskANN 向量检索引擎，承载视觉向量的存储与近邻检索（替代 PixelRAG 原生 FAISS，DiskANN 突破内存瓶颈）。仓库中的 `Ontos-AI/knowhere` 是文档解析服务，与此不同。
- **PixelRAG 库（核心依赖）**：`pixelrag_render` / `pixelrag_embed`，属 `pyproject.toml` 的 `[project.dependencies]`，由 `uv sync` 默认安装；`provider=="pixelrag"` 未配置时 fail-fast 抛错（无 mock 回退、无随机向量兜底）。**不再部署 `pixelrag-serve`，不再使用 FAISS。**

> **已移除**：LibreOffice（Excel 改走 Knowhere 直连）、pixelrag-serve、FAISS、OpenAI / Cohere。

### 模型 API Key

仅 DeepSeek + Qwen 系列：

| 用途 | 模型 | 环境变量 |
| --- | --- | --- |
| 文本 LLM / 路由 | DeepSeek-V4-Pro | `LLM_API_KEY`、`LLM_BASE_URL` |
| VLM（看图读数） | Qwen-VL-Max | `VLM_API_KEY`、`VLM_BASE_URL` |
| 文本嵌入 dim 1536 | Qwen `text-embedding-v4` | `DASHSCOPE_API_KEY`、`DASHSCOPE_BASE_URL` |
| 视觉嵌入 dim 2048 | Qwen3-VL-Embedding-2B（`pixelrag_embed`） | 由 PixelRAG 库托管 |
| 文本 rerank | Qwen `qwen3-rerank` | `DASHSCOPE_API_KEY` |

### 关键环境变量

> 以 `eagle_rag/settings.yaml` 为准（支持 `${VAR:-default}` 占位）。`EAGLE_RAG_PROFILE` 绑定领域（`plugin_namespace` / Milvus Database）；`KB_NAME` 在该领域内选择知识库；`KNOWHERE_MODE` / `KNOWHERE_BASE_URL` 选择 Knowhere 后端。**不再依赖 `LIBREOFFICE_PATH` 与 `PIXELRAG_SERVE_URL`**。

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `EAGLE_RAG_PROFILE` | `core` | 部署 profile：`core` / `biomed`（实验性）/ `lakehouse-bi`（开发中）；设定 `default_namespace` + Milvus `db_name` |
| `KB_NAME` | `default` | 绑定领域**内**的默认知识库 id，如 `finance` / `patent` / `pharma` |
| `KNOWHERE_BASE_URL` | `http://localhost:5005` | Knowhere HTTP 解析服务地址 |
| `LLM_API_KEY` / `LLM_BASE_URL` | — | DeepSeek |
| `VLM_API_KEY` / `VLM_BASE_URL` | — | Qwen-VL-Max（DashScope） |
| `DASHSCOPE_API_KEY` | — | Qwen 文本嵌入 / rerank 共用 |
| `MILVUS_HOST` / `MILVUS_PORT` | `localhost` / `19530` | Milvus |
| `MILVUS_VISUAL_INDEX_TYPE` | `hnsw` | 视觉索引类型，`hnsw` / `diskann` |
| `ROUTER_MODE` | `auto` | `auto` / `text` / `visual` / `hybrid` |
| `POSTGRES_DSN` | `postgresql://eagle:eagle@localhost:5432/eagle_rag` | PostgreSQL 连接串 |
| `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` | `redis://localhost:6379/0` / `1` | Celery |
| `MINIO_ENDPOINT` / `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` | `localhost:9000` / `minioadmin` / `minioadmin` | MinIO |

## 快速开始

```bash
# 1. 初始化（复制 .env、安装前后端依赖）
task setup
# 编辑 .env 填入 LLM_API_KEY / VLM_API_KEY / DASHSCOPE_API_KEY 与数据库凭证

# 2a. Docker 全栈（推荐，含基础设施）
task up                 # dev profile（自动合并 docker-compose.override.yml）
task up:prod            # prod profile（排除 dev override）

# 2b. 本机开发（需自行启动 Milvus / PostgreSQL / Redis / MinIO / Knowhere）
task dev                # 并行启动前后端热重载
task be:worker QUEUES=router_queue CONCURRENCY=4
task be:worker QUEUES=knowhere_queue CONCURRENCY=8
task be:worker QUEUES=pixelrag_queue CONCURRENCY=1   # 严格低并发防 OOM

# 3. 验证
task health             # curl http://localhost:8000/health
```

## 常用命令（Taskfile）

| 命令 | 说明 |
| --- | --- |
| `task setup` | 复制 `.env`、`uv sync`、`bun install` |
| `task up` / `task up:prod` / `task down` | Docker 启停（dev / prod profile） |
| `task dev` | 本机并行启动前后端（热重载） |
| `task be:api` / `task be:worker` | 后端 API / Celery Worker（参数化队列与并发） |
| `task be:test` / `task be:lint` / `task be:typecheck` | 测试 / Ruff / Mypy |
| `task fe:dev` / `task fe:build` / `task fe:lint` | 前端开发 / 构建 / Biome |
| `task docs:serve` / `task docs:build` | MkDocs 文档站（`:8001`） |
| `task db:migrate` | Alembic 迁移至最新版本（`alembic upgrade head`） |
| `task health` | 检查 API 健康状态 |

## MCP 工具

MCP Server（FastMCP，默认 streamable HTTP，挂载于 `/mcp`，可降级 stdio）暴露 **命名空间** 工具（`{namespace}_{name}`）。Core 工具始终注册；领域工具仅在 `EAGLE_RAG_PROFILE` / `default_namespace` 匹配时出现（G3）。见 [MCP 工具文档](docs/zh/api/mcp-tools.md) 与 ADR-008。

| 工具 | 参数 | 返回 |
| --- | --- | --- |
| `core_ingest` | `source_uri`, `source_type?`, `kb_name?` | `{job_id, status, document_id, dedup_hit}` |
| `core_query` | `query`, `mode?`, `scope?`, `kb_name?`, `scope_filter?` | `{answer, sources, route, steps}` |
| `core_retrieve_text` | `query`, `scope?`, `top_k=5`, `kb_name?` | `[{node_id, text, score, metadata}]` |
| `core_retrieve_visual` | `query`, `scope?`, `top_k=5`, `kb_name?` | `[{image_id, document_id, page, position, score}]` |
| `biomed_query_entities` | `entity`, `kb_name?` | 实体别名 / 通路（biomed profile，**实验性**） |
| `biomed_retrieve_compounds` | `smiles_or_name`, `top_k?`, `kb_name?` | 化学 ANN 命中（biomed profile，**实验性**） |
| `lakehouse_bi_query_semantic_context` | `question`, `kb_name?` | 语义上下文包（lakehouse-bi profile，**开发中**） |
| `lakehouse_bi_retrieve_historical_analysis` | `topic`, `kb_name?` | 历史分析分块（**开发中**） |

`kb_name` 缺省时回退 `settings.kb_name`。用 `EAGLE_RAG_PROFILE=biomed`（**实验性**）或 `lakehouse-bi`（**开发中**）启用领域（见 `eagle_rag/settings.yaml` 的 `profiles:`）。生产默认仍为 `core`。

## 目录结构

```
eagle-rag/
├─ eagle_rag/            # 后端
│  ├─ admin/             # 管理面板（probes / metrics / system_setting / mcp_log）
│  ├─ api/               # FastAPI 路由（app / query / ingest / documents / health / mcp_server / mcp_http）
│  ├─ attachments/       # 问答附件懒解析
│  ├─ db/                # SQLModel + Alembic 模型
│  ├─ generation/        # 多模态生成引擎
│  ├─ images/            # 图片存储
│  ├─ index/             # Milvus 存储（milvus_text_store / milvus_visual_store / registry）
│  ├─ ingest/            # 摄入管道（router / selectors / knowhere_adapter / pixelrag_adapter / runner / preprocess）
│  ├─ kb/                # 知识库生命周期与健康
│  ├─ notifications/     # 通知
│  ├─ plugins/           # 微内核（PluginManager / HookBus / orchestrators / core_defaults）
│  ├─ retrievers/        # 检索器（knowhere_graph_retriever / pixelrag_visual_retriever）
│  ├─ router/            # 路由引擎（router_engine / llm_factory / models / selectors）
│  ├─ sessions/          # 会话存储
│  ├─ storage/           # MinIO 客户端 + 去重
│  ├─ tasks/             # Celery（celery_app / dead_letter / state）
│  ├─ telemetry/         # 结构化日志 + OpenTelemetry
│  └─ config.py  settings.yaml
├─ plugins/              # 同仓垂类插件（biomed 实验性 / lakehouse_bi 开发中 / _template）
├─ frontend/             # Next.js + Bun + HeroUI v3（仅 Core 橱窗）
├─ docker/               # Dockerfile（api / worker / frontend / docs / mcp）+ knowhere-self-hosted
├─ tests/  examples/  design/
├─ docs/                 # MkDocs Material 双语（zh / en）
├─ docker-compose.yml  Taskfile.yml  mkdocs.yml  pyproject.toml
└─ README.md  README.zh.md  AGENTS.md
```

## 文档

- **English docs** → [docs/en/index.md](docs/en/index.md)
- **中文文档** → [docs/zh/index.md](docs/zh/index.md)
- **学习路径** → [docs/zh/learning-path.md](docs/zh/learning-path.md)（RAG 推荐阅读顺序）
- **架构设计** → [docs/zh/architecture/index.md](docs/zh/architecture/index.md) · [插件架构](docs/zh/architecture/plugin-architecture.md) · [多模态融合](docs/zh/architecture/multimodal-fusion.md)
- **API 参考** → [docs/zh/api/index.md](docs/zh/api/index.md)
- **MCP 工具** → [docs/zh/api/mcp-tools.md](docs/zh/api/mcp-tools.md)

## Knowledges

Eagle-RAG 依赖以下开源项目与服务：

| 项目 | 在 Eagle-RAG 中的角色 |
| --- | --- |
| [**Milvus**](https://milvus.io/docs) | 向量数据库，承载双 Collection `eagle_text`（1536 维文本）与 `eagle_visual`（2048 维视觉）；HNSW / DiskANN 近似检索，并对 `kb_name`、`document_id` 及语义树锚定字段做标量过滤。 |
| [**Ontos-AI/Knowhere**](https://github.com/Ontos-AI/knowhere) | 外部文档语义解析服务（`:5005`，`knowhere-python-sdk`）；产出类型化 chunk、章节树（`doc_nav`）与知识图谱边，供文本管线入库与检索。 |
| [**PixelRAG**](https://github.com/StarTrail-org/PixelRAG) | 进程内视觉编码器 + 切片库（`pixelrag_render` + `pixelrag_embed`）；将扫描版 PDF / 图片 / 网页渲染为 tile，并以 Qwen3-VL-Embedding-2B 写入 `eagle_visual`。 |
| [**MinerU**](https://github.com/opendatalab/MinerU) | Knowhere 自托管栈用于 PDF 首轮版式/OCR 解析的引擎（配置见 `docker/knowhere-self-hosted/` 的 `MINERU_API_KEYS` / `MINERU_URL`）；Eagle-RAG 不直接调用，但自托管 Knowhere 且启用 MinerU 解析路径时需配置。 |

## 许可

[Apache License 2.0](LICENSE)。第三方归属见 [NOTICE](NOTICE)（Milvus、Knowhere、PixelRAG、MinerU、LlamaIndex）。
