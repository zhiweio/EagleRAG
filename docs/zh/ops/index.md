# :material-server: 运维

Eagle-RAG 以分层 Docker Compose 栈交付：基础设施（etcd、MinIO、Milvus、PostgreSQL、Redis）、自托管 [Knowhere](https://github.com/Ontos-AI/knowhere) 文档解析子栈、FastAPI API、三个 Celery worker 与 Next.js 前端。本节面向在生产环境部署、观测、排障与备份的运维人员。

项目入口为 [`Taskfile.yml`](https://github.com/fintax-ai/eagle-rag/blob/master/Taskfile.yml) 与 [`docker-compose.yml`](https://github.com/fintax-ai/eagle-rag/blob/master/docker-compose.yml)。贡献者与 Agent 约束见 [`AGENTS.md`](https://github.com/fintax-ai/eagle-rag/blob/master/AGENTS.md)；产品概览见 [`README.md`](https://github.com/fintax-ai/eagle-rag/blob/master/README.md)。

## 快速命令

```bash
task setup          # copy .env files, uv sync, bun install, create knowhere-net
task up             # dev profile (auto-merges docker-compose.override.yml)
task up:prod        # prod profile (excludes the dev override)
task down           # stop eagle-rag + knowhere compose projects
task health         # curl http://localhost:8000/health
task ps             # docker compose ps (both projects)
task logs           # docker compose logs -f
task db:migrate     # alembic upgrade head
task knowhere:health # probe Knowhere HTTP :5005
```

### Taskfile 任务组

| 组 | 代表任务 | 用途 |
| --- | --- | --- |
| Frontend | `fe:dev`、`fe:build`、`fe:lint`、`fe:format` | Bun / Next.js 本地开发与 Biome 门禁 |
| Backend | `be:api`、`be:worker`、`be:test`、`be:lint`、`be:format`、`be:typecheck` | uvicorn、Celery、pytest、ruff、mypy |
| Docker | `up`、`up:prod`、`down`、`build`、`logs`、`ps`、`clean` | Compose 生命周期 |
| Knowhere | `knowhere:up`、`knowhere:down`、`knowhere:health`、`knowhere:logs` | 独立解析子栈 |
| Docs | `docs:serve`、`docs:build`、`docs:up` | MkDocs 本地预览与容器 |
| Data | `db:migrate` | 对 PostgreSQL 的 Alembic 迁移 |

`task be:worker` 接受参数：

```bash
task be:worker QUEUES=router_queue,knowhere_queue,pixelrag_queue CONCURRENCY=4
```

在笔记本上可将三条流水线队列合并到一个进程。Docker 中每队列有独立容器与调优的 `CONCURRENCY`（见 [Docker](docker.md)）。

## 本节内容

| 页面 | 主题 |
| --- | --- |
| [Docker](docker.md) | Compose 拓扑、Dockerfile、healthcheck 门控启动、dev override |
| [可观测性](observability.md) | `/health`、`/metrics`、`/admin/*`、队列采样、SSE 日志、OpenTelemetry |
| [排障](troubleshooting.md) | 症状 → 原因 → 修复矩阵，对应探测与日志行 |
| [备份与恢复](backup-restore.md) | PostgreSQL、MinIO、Milvus、Knowhere、Redis —— 按存储与 compose 卷名 |

## 运维模型

栈分三层，按依赖顺序启动。应用服务使用 `depends_on` 且 `condition: service_healthy`，依赖异常时暂停启动而非连接错误雪崩。

```mermaid
flowchart TB
    subgraph L1["Layer 1 — Infrastructure (always on)"]
        etcd["etcd"]
        minio["minio"]
        milvus["milvus"]
        pg["postgres"]
        redis["redis"]
    end

    subgraph L2["Layer 2 — Knowhere sub-stack (knowhere-net)"]
        kh["knowhere :5005"]
        kh_pg["postgres 15"]
        kh_redis["redis"]
        kh_ls["localstack"]
    end

    subgraph L3["Layer 3 — Application (dev/test/prod profile)"]
        api["api :8000"]
        wr["worker-router c=4"]
        wk["worker-knowhere c=8"]
        wp["worker-pixelrag c=1"]
        fe["frontend :3000"]
    end

    etcd --> milvus
    minio --> milvus
    pg --> api
    redis --> api
    minio --> api
    milvus --> api
    redis --> wr & wk & wp
    milvus --> wr & wk & wp
    api --> fe
    kh -.->|knowhere-net DNS| api & wk
```

| 层 | 服务 | 说明 |
| --- | --- | --- |
| 基础设施 | `etcd`、`minio`、`milvus`、`postgres`、`redis` | etcd + MinIO 供给 Milvus 2.6.19；PostgreSQL 16 与 Redis 7 由应用共享 |
| Knowhere 子栈 | `docker/knowhere-self-hosted/` 中的 `app`、`postgres`、`redis`、`localstack` | 自托管解析器，自有 Postgres 15（`Knowhere` DB）、Redis（2 GB LRU）、LocalStack 3.8；经外部网络 `knowhere-net` 访问 |
| 应用 | `api`、`worker-router`、`worker-knowhere`、`worker-pixelrag`、`frontend`、`docs` | API `:8000`；三个 Celery worker 共享一镜像，由 `QUEUES` / `CONCURRENCY` 参数化；frontend `:3000` |

### 为何三个 Celery worker？

入库是三阶段流水线：

1. **`router_queue`**（并发 4）—— 按格式 + 内容形态路由，分发下游任务。
2. **`knowhere_queue`**（并发 8）—— 对 Knowhere 的 HTTP 结构化解析；I/O 密集，可更高并行。
3. **`pixelrag_queue`**（并发 1）—— 进程内 `pixelrag_render` + `pixelrag_embed` + Qwen3-VL 编码器；内存密集，严格串行。

拆分 worker 避免长视觉编码饿死路由分发，并将 OOM 风险隔离在 `worker-pixelrag` 的 4 GB 内存限制后。见 [Docker — pixelrag_queue](docker.md#why-pixelrag_queue-concurrency-is-1)。

## Profile 与 dev override

基础设施服务**无 profile**，任意调用即启动。应用服务属于 `[dev, test, prod]`；`docs` 属于 `[docs, prod]`。

```bash
docker compose --profile dev up -d
COMPOSE_FILE=docker-compose.yml docker compose --profile prod up -d
docker compose --profile docs up -d docs
```

未显式 `-f` / `COMPOSE_FILE` 时，[`docker-compose.override.yml`](https://github.com/fintax-ai/eagle-rag/blob/master/docker-compose.override.yml) 自动合并。它启用 `uvicorn --reload`、只读挂载 `eagle_rag/`、暴露基础设施端口，frontend 经 Bun 运行。**生产部署必须用 `COMPOSE_FILE=docker-compose.yml` 锁定 compose 文件列表**，防止 dev 挂载与 `--reload` 泄漏到生产。

## 网络与外部依赖

| 网络 | 范围 | 用途 |
| --- | --- | --- |
| `eagle-net` | eagle-rag compose 项目 | etcd、minio、milvus、postgres、redis、api、workers、frontend 内部 DNS |
| `knowhere-net` | **external**，共享 | DNS 别名 `knowhere` → Knowhere API `:5005`；由 `task setup` 或 `task net:ensure` 创建 |

Knowhere **不在**主 `docker-compose.yml` 中，因维护为 `docker/knowhere-self-hosted/` 下的独立 compose 项目。Eagle-RAG 无法对另一 compose 文件中的服务 `depends_on`；API 与 `worker-knowhere` 加入 `knowhere-net` 并使用 `KNOWHERE_BASE_URL=http://knowhere:5005`。Knowhere 宕机时解析任务**失败关闭**（状态 `FAILED`），而非静默回退。

## 配置注入

[`eagle_rag/settings.yaml`](https://github.com/fintax-ai/eagle-rag/blob/master/eagle_rag/settings.yaml) 对每个外部端点使用 `${VAR:-default}` 占位符。容器内必须注入服务 DNS 名 —— 像 `localhost` 的默认值无法到达 compose 服务：

| 变量 | 容器值 | 宿主机开发值 |
| --- | --- | --- |
| `MILVUS_HOST` | `milvus` | `localhost` |
| `CELERY_BROKER_URL` | `redis://redis:6379/0` | `redis://localhost:6379/0` |
| `POSTGRES_DSN` | `postgresql://eagle:eagle@postgres:5432/eagle_rag` | `postgresql://eagle:eagle@localhost:5432/eagle_rag` |
| `MINIO_ENDPOINT` | `minio:9000` | `localhost:9000` |
| `KNOWHERE_BASE_URL` | `http://knowhere:5005` | `http://localhost:5005` |

VLM / LLM / 嵌入 API 密钥仅从 `.env` 注入；compose 中不硬编码。

## 健康与就绪

| 端点 | 消费者 | 行为 |
| --- | --- | --- |
| `GET /health` | Docker `api` healthcheck、`task health`、负载均衡 | 并发探测 8 个依赖；任一 `down` → `status: degraded`（HTTP 200） |
| `GET /admin/probes` | 管理 UI、深度运维 | 相同探测 + `latency_ms`、psutil CPU/内存 |
| `celery inspect ping` | Worker healthcheck | 每容器，范围 `celery@$(hostname)` |
| `GET http://knowhere:5005/health` | Knowhere 子栈 | 与 eagle-rag compose 独立 |

Worker 容器使用 60 s `start_period`，因 Milvus 与 LlamaIndex 客户端在首次 import 时预热。API 因同样原因使用 40 s。

## 数据目录

| 路径 | 挂载 | 内容 |
| --- | --- | --- |
| `./data` | `api` + 所有 workers | `storage.data_dir` —— 上传、HuggingFace 缓存（`HF_HOME=/app/data/huggingface`）、Chrome/PixelRAG 产物 |
| 命名卷 | 仅基础设施 | `vol-*` 名称见 [备份与恢复](backup-restore.md) |

切勿提交 `.env` 或密钥。`task setup` 用 `cp -n` 复制 `.env.example` 与 `docker/knowhere-self-hosted/.env.example`。

## Celery 可靠性（运维摘要）

Eagle-RAG 将 Celery 配置为**至少一次**投递：

- `task_acks_late = True` —— 任务完成前消息不从 Redis 移除。
- `worker_prefetch_multiplier = 1` —— worker 忙时不囤积消息。
- `task_reject_on_worker_lost = True` —— 被杀 worker 将进行中任务重新入队。

带 `@with_retry` 的任务使用指数退避（`retry_backoff * 2^retries`），耗尽后进入 **`dead_letter`** 队列供管理检视（`drain_dead_letter` / `replay_dead_letter`）。死信队列**不**由业务 worker 消费。

完整理论与重放流程见[排障 — Celery 与死信](troubleshooting.md#celery-at-least-once-delivery-and-dead-letters)。

## 可观测性（运维摘要）

| 信号 | 位置 | 用途 |
| --- | --- | --- |
| 运维日志 | loguru → stderr + `logs/eagle_rag.log`（+ Redis `logs` 频道） | 请求错误、worker 堆栈 |
| AI 事件 | structlog → `logs/ai_telemetry.jsonl`（`get_ai_logger`） | 查询/入库业务事件（JSONL） |
| 追踪 | OpenTelemetry `trace_span` + 可选 OTLP 导出 | API → Celery → 检索端到端延迟 |
| Prometheus | MCP 独立 `/metrics` 上的 `mcp_tool_calls_total`、`mcp_tool_duration_seconds` 等 | MCP 云上抓取目标 |
| 队列指标 | Celery beat → 每 30 s `metric_sample` 表 | `/admin/celery` 积压时间序列 |

详情：[可观测性](observability.md)。

## 运维中的多租户

每个文档、向量行、会话与 Celery 任务带 `kb_name`（默认 `default`，可由 `KB_NAME` 覆盖）。备份或恢复单租户时应在 PostgreSQL 与 Milvus 标量字段按 `kb_name` 过滤，而非仅按桶前缀。会话 scope 过滤（`sessions.scope_filter` JSONB）持久化用户选的 KB / 文档 / 标签并集 —— 恢复 PostgreSQL 后期望 scope 感知查询才有效。

## 生产检查清单

1. 复制并填写 `.env` 与 `docker/knowhere-self-hosted/.env`（API 密钥、密码）。
2. `docker network create knowhere-net`（幂等）。
3. `task up:prod` 或等价且 `COMPOSE_FILE=docker-compose.yml`。
4. 对生产 DSN 执行 `task db:migrate`。
5. 验证 `task health` → 关键依赖均为 `up`（若省略 vision extra，pixelrag 可能为 `unknown` —— 见排障）。
6. 确认三个 worker 健康：`docker compose ps worker-router worker-knowhere worker-pixelrag`。
7. 抓取 `/admin/celery` 队列大小；若需积压图表须运行 beat（compose 无独立 beat 容器 —— 需要时运行 `celery -A eagle_rag.tasks.celery_app beat`）。
8. 配置日志轮转（compose `json-file` 每服务最大 10 MB × 3 文件）。
9. 按 [备份与恢复](backup-restore.md) 排程备份。

## 无 Docker 的本地开发

```bash
task setup
# Start infra only, or use existing local Postgres/Redis/Milvus/MinIO
task be:api          # terminal 1
task be:worker       # terminal 2 — all queues, CONCURRENCY=4
task fe:dev          # terminal 3
task knowhere:up     # if parsing is needed
```

或 `task dev` 并行运行 API + 前端（worker 仍需单独终端）。

## 相关文档

- 架构与多模态融合：`docs/en/architecture/`
- 后端模块深入：`docs/en/backend/`
- 开发工作流：`docs/en/development/`
