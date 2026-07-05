# 快速入门

约三分钟即可在本地跑起 Eagle-RAG。本文是最短路径：从零到可用栈；更深理论见[架构](../architecture/index.md)与[学习路径](../learning-path.md)。

---

## 理论与基础

### 你在启动什么

Eagle-RAG 是**多模态 RAG 数据层**——不是围绕单一 LLM 的聊天封装。它实现 [Lewis et al., 2020](https://arxiv.org/abs/2005.11401) 的 retrieve-then-generate 模式，配备双向量索引（文本 1536 维、视觉 2048 维）与双路 ingest 流水线。

| 层级 | 角色 | 技术 |
| --- | --- | --- |
| Client | 问答、入库、健康 UI | Next.js 16 + React 19 |
| API | REST、SSE、MCP | FastAPI `:8000` |
| Workers | 异步入库 | Celery — 3 个队列 |
| Parsers | 文档 → 分块 | Knowhere HTTP `:5005` + PixelRAG 库 |
| Storage | 向量 + 元数据 + 文件 | Milvus、PostgreSQL、MinIO、Redis |

单一 `Taskfile.yml` 编排安装；偏好容器时 `docker-compose.yml` 打包基础设施。

---

## Eagle-RAG 实现

### 引导序列

`task setup` 执行：

1. 复制 `.env.example` → `.env`（不覆盖已有文件）
2. `uv sync` —— 从 `pyproject.toml` 安装 Python 依赖
3. 在 `frontend/` 执行 `bun install`

`task up` 随后：

1. `knowhere:up` —— 在 `knowhere-net` 上自托管 Knowhere
2. `docker compose --profile dev up -d` —— 基础设施 + API + workers + frontend
3. 服务通过 Compose DNS 互联（`milvus`、`postgres`、`redis`、`minio`、`knowhere`）

### 首次请求路径

```mermaid
sequenceDiagram
    participant U as Browser :3000
    participant API as FastAPI :8000
    participant PG as PostgreSQL
    participant M as Milvus

    U->>API: GET /health
    API->>PG: probe
    API->>M: probe
    API-->>U: 200 JSON

    U->>API: POST /ingest (file)
    API->>API: ingest.runner → Celery ingest_router
    Note over API: Returns job_id immediately
```

配置单例：`eagle_rag/config.py` 中的 `get_settings()` —— 通过 `@lru_cache` 每进程加载一次。

---

## 本地开发模式

| 模式 | 适用场景 | 实用说明 |
| --- | --- | --- |
| `task up`（Docker） | 首次启动、演示、类 CI 环境 | worker 代码变更需重启容器，除非 bind mount |
| `task dev`（宿主机 API + 前端） | 快速 API/`--reload` 迭代 | 须自行运行 Milvus、Postgres、Redis、MinIO、Knowhere |
| 幂等 `task setup` | 新克隆仓库 | 不覆盖已有 `.env` — 新键需手动合并 |

默认关闭认证 — localhost 可接受；在非可信网络暴露前启用 `auth.enabled`。

---

## 前置条件（一行检查）

```bash
python3.12 --version && uv --version && bun --version && docker compose version
```

任一命令失败则安装缺失工具：

- **Python ≥ 3.12** + [`uv`](https://docs.astral.sh/uv/) —— 后端依赖
- **Node.js + [Bun](https://bun.sh/)** —— 前端
- **Docker + Docker Compose** —— 全栈启动

完整矩阵见[安装](installation.md)。

---

## 三分钟路径

```bash
# 1. 引导：复制 .env、安装依赖
task setup

# 2. 编辑 .env —— 设置 API 密钥与数据库凭据
$EDITOR .env

# 3a. Docker 全栈（推荐）
task up
task db:migrate    # 仅首次

# 3b. 或在宿主机热重载（基础设施自行启动）
task dev
```

`task up` 后打开：

| 服务 | URL |
| --- | --- |
| Frontend | <http://localhost:3000> |
| API | <http://localhost:8000/health> |
| API docs | <http://localhost:8000/docs> |
| MkDocs | <http://localhost:8001>（`task docs:serve`） |

!!! warning "警告"
    查询前至少设置 `LLM_API_KEY`、`VLM_API_KEY` 与 `DASHSCOPE_API_KEY`。见[安装 — 模型 API 密钥](installation.md#model-api-keys)。

---

## 配置（最小集）

| 变量 | 用途 |
| --- | --- |
| `KB_NAME` | 默认租户（`default`） |
| `LLM_API_KEY` | DeepSeek 路由 + 文本 |
| `VLM_API_KEY` | Qwen-VL 生成 |
| `DASHSCOPE_API_KEY` | 文本嵌入 + 重排 |
| `KNOWHERE_BASE_URL` | 解析服务（宿主机上 `http://localhost:5005`） |

完整分层见[配置](configuration.md)。

---

## 验证可用

```bash
task health              # API /health JSON
task knowhere:health     # Knowhere 解析器 :5005
task ps                  # docker compose ps —— 服务健康
```

预期 `/health` 形态：各依赖状态（`up` / `down` / `unknown`）。单一依赖为 `down` 时**降级**该能力而非拖垮 API —— 设计如此。见[可靠性](../architecture/reliability.md)。

### 冒烟：ingest + query

```bash
# 经 API 上传（替换为你的文件）
curl -F "file=@README.md" -F "kb_name=default" http://localhost:8000/ingest

# 轮询任务状态后查询
curl -s http://localhost:8000/query -H 'Content-Type: application/json' \
  -d '{"query":"What is Eagle-RAG?","kb_name":"default"}' | jq .answer
```

---

## 故障模式与运维

| 现象 | 可能原因 | 修复 |
| --- | --- | --- |
| `task up` 在 Knowhere 失败 | 缺少 `docker/knowhere-self-hosted/.env` | 复制示例 env；设置 `DS_KEY` |
| `/health` 显示 milvus `down` | Milvus 仍在启动（约 60s） | 等待；`task ps` |
| 查询返回 API 错误 | 缺少 `LLM_API_KEY` / `VLM_API_KEY` | 编辑 `.env`；重启 API |
| Ingest 任务 `FAILED` | Knowhere 不可达 | `task knowhere:health` |
| 前端无法访问 API | `NEXT_PUBLIC_API_URL` 错误 | 设为 `http://localhost:8000` |

---

## 开发工作流

```mermaid
flowchart TD
    SETUP["task setup<br/>uv sync + bun install"] --> EDIT["edit .env<br/>API keys + DB creds"]
    EDIT --> MIGRATE["task db:migrate"]
    MIGRATE --> DECIDE{Infra in Docker?}
    DECIDE -->|yes| UP["task up<br/>full compose stack"]
    DECIDE -->|no| DEV["task dev<br/>be:api + fe:dev on host"]
    UP --> HEALTH["task health"]
    DEV --> HEALTH
    HEALTH --> OPEN["localhost:3000<br/>API :8000"]
```

=== "Docker（`task up`）"

    基础设施、API、workers 与前端 HMR 均在 Compose 中。worker 代码变更需重启容器。

=== "宿主机（`task dev`）"

    Uvicorn 与 Next.js 在宿主机热重载。须单独运行 Milvus、PostgreSQL、Redis、MinIO、Knowhere，并将 `.env` 指向 `localhost`。

!!! note "说明"
    Knowhere（`Ontos-AI/knowhere`，HTTP `:5005`）在 Compose 栈中作为自托管服务打包。`task dev` 时将 `KNOWHERE_BASE_URL` 指向运行中的实例，并用 `task knowhere:health` 探测。

### Worker 进程（宿主机开发）

```bash
task be:worker QUEUES=router_queue CONCURRENCY=4
task be:worker QUEUES=knowhere_queue CONCURRENCY=8
task be:worker QUEUES=pixelrag_queue CONCURRENCY=1   # keep at 1
```

---

## 下一步

| 目标 | 文档 |
| --- | --- |
| 完整安装矩阵 | [安装](installation.md) |
| 配置深入 | [配置](configuration.md) |
| 开发 vs 生产部署 | [部署](deployment.md) |
| 系统设计 | [架构概览](../architecture/index.md) |
| RAG 理论路径 | [学习路径](../learning-path.md) |

---

## 参考文献

- [Lewis et al., 2020](https://arxiv.org/abs/2005.11401) —— RAG 基础
- [Knowhere](https://github.com/Ontos-AI/knowhere) —— 解析服务
- [uv 文档](https://docs.astral.sh/uv/)
- [Taskfile](https://taskfile.dev/) —— 项目自动化
