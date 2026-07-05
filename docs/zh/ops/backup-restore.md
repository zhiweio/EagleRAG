# :material-database: 备份与恢复

Eagle-RAG 所用各持久化存储的规程。卷名与 [`docker-compose.yml`](https://github.com/fintax-ai/eagle-rag/blob/master/docker-compose.yml) 及 [`docker/knowhere-self-hosted/compose.yaml`](https://github.com/fintax-ai/eagle-rag/blob/master/docker/knowhere-self-hosted/compose.yaml) 一致。

**警告：** `task clean` 对两个项目执行 `docker compose down -v` 并**销毁**命名卷。生产环境应禁用或限制。

## 存储清单

```mermaid
flowchart LR
    subgraph eagle["eagle-rag compose"]
        VP["vol-postgres"]
        VMi["vol-minio"]
        VV["vol-milvus"]
        VE["vol-etcd"]
        VR["vol-redis"]
        BD["./data bind mount"]
    end

    subgraph kh["knowhere-self-hosted"]
        KPG["postgres_data"]
        KRD["redis_data"]
        KLS["localstack_data"]
        KUD["knowhere_user_data"]
        KMC["knowhere_model_cache"]
        KSE["knowhere_secrets"]
    end

    VP --> SessionsTasks
    VMi --> Blobs
    VV --> Vectors
    VE --> MilvusMeta
    BD --> HFCacheFiles
```

| 存储 | 卷 / 路径 | 关键性 | 内容 |
| --- | --- | --- | --- |
| PostgreSQL（eagle） | `vol-postgres` | **关键** | 会话、消息、`scope_filter` JSONB、文档注册、去重、`task_audit`、`metric_sample`、MCP 日志 |
| MinIO | `vol-minio` | **关键** | 原文件、渲染瓦片、图片存储 |
| Milvus 数据 | `vol-milvus` | **关键** | `eagle_text`、`eagle_visual` 向量 |
| etcd | `vol-etcd` | **关键** | Milvus collection 元数据（与 Milvus 备份一起） |
| Redis（eagle） | `vol-redis` | 中等 | Celery 代理队列、结果、pubsub 日志 —— 常可重建 |
| 宿主机 `./data` | 绑定挂载 | 中等 | HF 模型缓存、镜像 MinIO 路径的本地上传 |
| Knowhere Postgres | `postgres_data` | 高（解析器） | Knowhere 应用状态 |
| Knowhere 卷 | `knowhere_*` | 中等 | 用户数据、模型、密钥 |

## 备份前检查清单

1. 若可能暂停写入（暂停 ingest、排空队列）—— 非快照一致性严格必需，但改善跨存储一致性。
2. 部分恢复时记录 `kb_name` 租户。
3. 记录镜像标签（`milvusdb/milvus:v2.6.19` 等）。
4. 经密钥管理器导出 `.env` **密钥**，勿用 git。

```bash
task ps
curl -s localhost:8000/admin/celery | jq '.queues'
```

---

## PostgreSQL（eagle-rag）

**卷：** `vol-postgres` → `/var/lib/postgresql/data`  
**默认 DSN：** `postgresql://eagle:eagle@postgres:5432/eagle_rag`

### 备份（逻辑 dump）

可移植性与时间点标签的首选。

```bash
# From host with port exposed (dev override) or exec into container
docker compose exec -T postgres \
  pg_dump -U eagle -d eagle_rag -Fc -f /tmp/eagle_rag.dump

docker compose cp postgres:/tmp/eagle_rag.dump ./backups/eagle_rag_$(date +%Y%m%d).dump
```

纯 SQL 替代：

```bash
docker compose exec -T postgres \
  pg_dump -U eagle -d eagle_rag --no-owner --no-acl \
  > ./backups/eagle_rag_$(date +%Y%m%d).sql
```

### 备份（卷快照）

VM / 云盘快照时，短暂停止 postgres：

```bash
docker compose stop postgres
# snapshot vol-postgres at hypervisor / docker volume driver
docker compose start postgres
```

### 恢复

```bash
# Destructive — drops existing objects in target DB
docker compose exec -T postgres dropdb -U eagle --if-exists eagle_rag
docker compose exec -T postgres createdb -U eagle eagle_rag

docker compose cp ./backups/eagle_rag.dump postgres:/tmp/eagle_rag.dump
docker compose exec -T postgres pg_restore -U eagle -d eagle_rag /tmp/eagle_rag.dump
```

恢复后，若 dump 早于代码则运行迁移：

```bash
task db:migrate
```

### `sessions.scope_filter` 说明

[`sessions`](https://github.com/fintax-ai/eagle-rag/blob/master/eagle_rag/db/models/sessions.py) 上 JSONB 列。随 pg_dump 自动备份。无消息时仅恢复 scope 无意义 —— 一并恢复 `sessions` + `messages`。

---

## MinIO

**卷：** `vol-minio` → `/data`  
**默认桶：** `eagle-rag`（`MINIO_BUCKET`）

### 用 MinIO Client（`mc`）备份

```bash
docker compose exec minio mc alias set local http://localhost:9000 minioadmin minioadmin
docker compose exec minio mc mirror local/eagle-rag /backup/eagle-rag
```

从宿主机（dev 暴露 9000/9001）：

```bash
mc alias set eagle http://localhost:9000 "$MINIO_ACCESS_KEY" "$MINIO_SECRET_KEY"
mc mirror eagle/eagle-rag ./backups/minio/eagle-rag/
```

### 备份（卷 tarball）

```bash
docker compose stop minio
docker run --rm \
  -v eagle-rag_vol-minio:/data:ro \
  -v $(pwd)/backups:/backup \
  alpine tar czf /backup/vol-minio_$(date +%Y%m%d).tar.gz -C /data .
docker compose start minio
```

卷名前缀为 compose 项目名（默认 `eagle-rag`）。

### 恢复

```bash
mc mirror ./backups/minio/eagle-rag/ eagle/eagle-rag
```

经 `GET /admin/minio` 验证对象数。

---

## Milvus + etcd

Milvus standalone 将 segment 存在 `vol-milvus`，元数据在 etcd（`vol-etcd`）。**两者一起备份**才有完整向量库。

### 快照前优雅 flush

```bash
curl -X POST http://localhost:8000/admin/milvus/flush
# or per-collection via MilvusClient
```

### 卷 tarball（协调）

```bash
docker compose stop milvus
# optional: stop etcd if filesystem snapshot requires quiet metadata
docker compose stop etcd

docker run --rm \
  -v eagle-rag_vol-milvus:/data:ro \
  -v $(pwd)/backups:/backup \
  alpine tar czf /backup/vol-milvus_$(date +%Y%m%d).tar.gz -C /data .

docker run --rm \
  -v eagle-rag_vol-etcd:/data:ro \
  -v $(pwd)/backups:/backup \
  alpine tar czf /backup/vol-etcd_$(date +%Y%m%d).tar.gz -C /data .

docker compose start etcd milvus
```

### 恢复

1. 停止 milvus + etcd。
2. 用 tarball 替换卷内容。
3. 启动 etcd，等健康，启动 milvus（60 s start_period）。
4. `GET /admin/milvus` —— 确认 `eagle_text` / `eagle_visual` 行数。

### 从源重新索引（灾难）

Milvus 丢失但 MinIO + Postgres 仍在：

1. 恢复 Postgres + MinIO。
2. 对每个文档重新 ingest（去重可能跳过未变 SHA）。
3. 在 `pixelrag_queue`（并发 1）上预期长重建时间。

---

## Redis（eagle-rag）

**卷：** `vol-redis`

通常**可不**恢复 —— Celery 队列与临时结果会重建。例外：依赖 Redis pubsub 日志历史。

```bash
docker compose exec redis redis-cli SAVE
docker compose cp redis:/data/dump.rdb ./backups/redis_$(date +%Y%m%d).rdb
```

恢复：停 redis，将 `dump.rdb` 放入卷，启动 redis。

---

## 宿主机 `./data` 绑定挂载

含 HuggingFace 缓存（`HF_HOME=/app/data/huggingface`）、可选本地产物。

```bash
tar czf ./backups/data_$(date +%Y%m%d).tar.gz -C ./data .
```

恢复：在启动 `worker-pixelrag` 前解压到 `./data`，避免重新下载 Qwen3-VL 权重。

---

## Knowhere 子栈

独立 compose 项目 —— 卷**不**以 `vol-*` 为前缀。

| 卷 | 备份 |
| --- | --- |
| `postgres_data` | `pg_dump` DB `Knowhere` 用户 `root`（见 knowhere compose） |
| `redis_data` | 可选 RDB 复制 |
| `localstack_data` | 若 Knowhere S3 桩有数据则 tarball |
| `knowhere_user_data` | `docker run … tar czf` |
| `knowhere_model_cache` | Tarball —— 体积大；可重新下载 |
| `knowhere_secrets` | **静态加密** —— 含 API 密钥 |

```bash
cd docker/knowhere-self-hosted
unset POSTGRES_PASSWORD APP_ENV
docker compose exec -T postgres pg_dump -U root -d Knowhere -Fc > ../../backups/knowhere_$(date +%Y%m%d).dump
```

若依赖解析器侧状态，在 eagle-rag ingest 前恢复 Knowhere。

---

## 跨存储恢复顺序

```mermaid
sequenceDiagram
    participant etcd
    participant minio
    participant milvus
    participant pg as postgres
    participant kh as knowhere
    participant api

    Note over etcd,minio: 1. Infrastructure volumes
    etcd->>milvus: start healthy
    minio->>milvus: start healthy
    milvus->>milvus: start healthy
    pg->>pg: restore dump + migrate
    Note over kh: 2. Knowhere (parallel OK)
    kh->>kh: restore if needed
    Note over api: 3. Application
    api->>api: verify /health
```

1. `vol-etcd`、`vol-minio` → 启动 → `vol-milvus`
2. `vol-postgres` 恢复 + `task db:migrate`
3. Knowhere 卷 + `task knowhere:up`
4. 若需要 `./data`
5. `task up:prod` 或 `docker compose --profile prod up -d`
6. `GET /health`、`GET /admin/milvus`、抽查查询

Redis 最后或留空。

---

## 部分租户恢复（`kb_name`）

无单按钮租户导出。做法：

1. Postgres：从 `documents`、`sessions` 等 dump `kb_name = 'pharma'` 行（自定义 SQL）。
2. Milvus：经 Milvus 备份 API 或从 MinIO 前缀重新 ingest，用 `expr="kb_name == 'pharma'"` 导出实体。
3. MinIO：从注册表路径镜像带标签对象。

Milvus 部分导出不现实时，优先从源文件重新 ingest。

---

## 备份计划模板

| 存储 | 频率 | 保留 | 方法 |
| --- | --- | --- | --- |
| Postgres | 每日 | 30 天 | `pg_dump -Fc` |
| MinIO | 每日 | 30 天 | `mc mirror` |
| Milvus+etcd | 每周 | 4 周 | flush 后协调卷 tar |
| Knowhere PG | 每周 | 4 周 | `pg_dump` |
| `./data` HF 缓存 | 可选 | — | 带宽便宜可跳过 |
| Redis | 无 | — | — |

用 cron / Velero / 云快照自动化；每季度测试恢复。

---

## 恢复后验证

```bash
task health
curl -s localhost:8000/admin/milvus | jq '.collections'
curl -s localhost:8000/admin/knowhere | jq '{parsed, chunks}'
# Spot query
curl -s -X POST localhost:8000/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"test","kb_name":"default"}' | jq '.sources | length'
```

---

## 相关

- [Docker — 卷名](docker.md#volumes-compose-names)
- [排障](troubleshooting.md)
- [运维索引](index.md)
