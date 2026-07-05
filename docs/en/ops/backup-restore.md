# :material-database: Backup and restore

Procedures for each durable store Eagle-RAG uses. Volume names match [`docker-compose.yml`](https://github.com/fintax-ai/eagle-rag/blob/master/docker-compose.yml) and [`docker/knowhere-self-hosted/compose.yaml`](https://github.com/fintax-ai/eagle-rag/blob/master/docker/knowhere-self-hosted/compose.yaml).

**Warning:** `task clean` runs `docker compose down -v` on both projects and **destroys** named volumes. Disable or restrict in production.

## Store inventory

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

| Store | Volume / path | Criticality | Holds |
| --- | --- | --- | --- |
| PostgreSQL (eagle) | `vol-postgres` | **Critical** | Sessions, messages, `scope_filter` JSONB, documents registry, dedup, `task_audit`, `metric_sample`, MCP logs |
| MinIO | `vol-minio` | **Critical** | Original files, rendered tiles, image store |
| Milvus data | `vol-milvus` | **Critical** | `eagle_text`, `eagle_visual` vectors |
| etcd | `vol-etcd` | **Critical** | Milvus collection metadata (with Milvus backup) |
| Redis (eagle) | `vol-redis` | Medium | Celery broker queues, results, pubsub logs — often rebuildable |
| Host `./data` | bind mount | Medium | HF model cache, local uploads mirroring MinIO paths |
| Knowhere Postgres | `postgres_data` | High (parser) | Knowhere app state |
| Knowhere volumes | `knowhere_*` | Medium | User data, models, secrets |

## Pre-backup checklist

1. Quiesce writes if possible (pause ingest, drain queues) — not strictly required for crash-consistent snapshots but improves coherence across stores.
2. Note `kb_name` tenants if doing partial restore.
3. Record image tags (`milvusdb/milvus:v2.6.19`, etc.).
4. Export `.env` **secrets** via your secret manager, not git.

```bash
task ps
curl -s localhost:8000/admin/celery | jq '.queues'
```

---

## PostgreSQL (eagle-rag)

**Volume:** `vol-postgres` → `/var/lib/postgresql/data`  
**Default DSN:** `postgresql://eagle:eagle@postgres:5432/eagle_rag`

### Backup (logical dump)

Preferred for portability and point-in-time labels.

```bash
# From host with port exposed (dev override) or exec into container
docker compose exec -T postgres \
  pg_dump -U eagle -d eagle_rag -Fc -f /tmp/eagle_rag.dump

docker compose cp postgres:/tmp/eagle_rag.dump ./backups/eagle_rag_$(date +%Y%m%d).dump
```

Plain SQL alternative:

```bash
docker compose exec -T postgres \
  pg_dump -U eagle -d eagle_rag --no-owner --no-acl \
  > ./backups/eagle_rag_$(date +%Y%m%d).sql
```

### Backup (volume snapshot)

For VM / cloud disk snapshots, stop postgres briefly:

```bash
docker compose stop postgres
# snapshot vol-postgres at hypervisor / docker volume driver
docker compose start postgres
```

### Restore

```bash
# Destructive — drops existing objects in target DB
docker compose exec -T postgres dropdb -U eagle --if-exists eagle_rag
docker compose exec -T postgres createdb -U eagle eagle_rag

docker compose cp ./backups/eagle_rag.dump postgres:/tmp/eagle_rag.dump
docker compose exec -T postgres pg_restore -U eagle -d eagle_rag /tmp/eagle_rag.dump
```

After restore, run migrations if dump is older than code:

```bash
task db:migrate
```

### `sessions.scope_filter` note

Column type JSONB on [`sessions`](https://github.com/fintax-ai/eagle-rag/blob/master/eagle_rag/db/models/sessions.py). Backs up with pg_dump automatically. Partial restore of scope without messages is useless — restore whole `sessions` + `messages` together.

---

## MinIO

**Volume:** `vol-minio` → `/data`  
**Default bucket:** `eagle-rag` (`MINIO_BUCKET`)

### Backup with MinIO Client (`mc`)

```bash
docker compose exec minio mc alias set local http://localhost:9000 minioadmin minioadmin
docker compose exec minio mc mirror local/eagle-rag /backup/eagle-rag
```

From host (ports 9000/9001 exposed in dev):

```bash
mc alias set eagle http://localhost:9000 "$MINIO_ACCESS_KEY" "$MINIO_SECRET_KEY"
mc mirror eagle/eagle-rag ./backups/minio/eagle-rag/
```

### Backup (volume tarball)

```bash
docker compose stop minio
docker run --rm \
  -v eagle-rag_vol-minio:/data:ro \
  -v $(pwd)/backups:/backup \
  alpine tar czf /backup/vol-minio_$(date +%Y%m%d).tar.gz -C /data .
docker compose start minio
```

Volume name prefix is the compose project name (`eagle-rag` by default).

### Restore

```bash
mc mirror ./backups/minio/eagle-rag/ eagle/eagle-rag
```

Verify object count via `GET /admin/minio`.

---

## Milvus + etcd

Milvus standalone stores segments on `vol-milvus` and metadata in etcd (`vol-etcd`). **Back up both** for a coherent vector store.

### Graceful flush before snapshot

```bash
curl -X POST http://localhost:8000/admin/milvus/flush
# or per-collection via MilvusClient
```

### Volume tarball (coordinated)

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

### Restore

1. Stop milvus + etcd.
2. Replace volume contents from tarballs.
3. Start etcd, wait healthy, start milvus (60 s start_period).
4. `GET /admin/milvus` — confirm `eagle_text` / `eagle_visual` row counts.

### Re-index from source (disaster)

If Milvus is lost but MinIO + Postgres remain:

1. Restore Postgres + MinIO.
2. Re-run ingest for each document (dedup may skip unchanged SHA).
3. Expect long rebuild time on `pixelrag_queue` (concurrency 1).

---

## Redis (eagle-rag)

**Volume:** `vol-redis`

Usually acceptable to **not** restore — Celery queues and ephemeral results rebuild. Exception: if you rely on Redis pubsub log history.

```bash
docker compose exec redis redis-cli SAVE
docker compose cp redis:/data/dump.rdb ./backups/redis_$(date +%Y%m%d).rdb
```

Restore: stop redis, place `dump.rdb` in volume, start redis.

---

## Host `./data` bind mount

Contains HuggingFace cache (`HF_HOME=/app/data/huggingface`), optional local artefacts.

```bash
tar czf ./backups/data_$(date +%Y%m%d).tar.gz -C ./data .
```

Restore: extract to `./data` before starting `worker-pixelrag` to avoid re-downloading Qwen3-VL weights.

---

## Knowhere sub-stack

Separate compose project — volumes are **not** prefixed `vol-*`.

| Volume | Backup |
| --- | --- |
| `postgres_data` | `pg_dump` DB `Knowhere` user `root` (see knowhere compose) |
| `redis_data` | Optional RDB copy |
| `localstack_data` | Tarball if Knowhere S3 stub holds data |
| `knowhere_user_data` | `docker run … tar czf` |
| `knowhere_model_cache` | Tarball — large; can re-download |
| `knowhere_secrets` | **Encrypt at rest** — contains API keys |

```bash
cd docker/knowhere-self-hosted
unset POSTGRES_PASSWORD APP_ENV
docker compose exec -T postgres pg_dump -U root -d Knowhere -Fc > ../../backups/knowhere_$(date +%Y%m%d).dump
```

Restore Knowhere **before** eagle-rag ingest if you depend on parser-side state.

---

## Cross-store restore order

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

1. `vol-etcd`, `vol-minio` → start → `vol-milvus`
2. `vol-postgres` restore + `task db:migrate`
3. Knowhere volumes + `task knowhere:up`
4. `./data` if needed
5. `task up:prod` or `docker compose --profile prod up -d`
6. `GET /health`, `GET /admin/milvus`, spot-check query

Redis last or empty.

---

## Partial tenant restore (`kb_name`)

No single-button tenant export. Approach:

1. Postgres: dump rows where `kb_name = 'pharma'` from `documents`, `sessions`, etc. (custom SQL).
2. Milvus: export entities with `expr="kb_name == 'pharma'"` via Milvus backup API or re-ingest from MinIO prefixes.
3. MinIO: mirror objects tagged by document paths from registry.

Prefer re-ingest from source files when Milvus partial export is impractical.

---

## Backup schedule template

| Store | Frequency | Retention | Method |
| --- | --- | --- | --- |
| Postgres | Daily | 30 d | `pg_dump -Fc` |
| MinIO | Daily | 30 d | `mc mirror` |
| Milvus+etcd | Weekly | 4 w | Coordinated volume tar after flush |
| Knowhere PG | Weekly | 4 w | `pg_dump` |
| `./data` HF cache | Optional | — | Skip if bandwidth cheap |
| Redis | None | — | — |

Automate with cron / Velero / cloud snapshots; test restore quarterly.

---

## Verification after restore

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

## Related

- [Docker — volume names](docker.md#volumes-compose-names)
- [Troubleshooting](troubleshooting.md)
- [Operations index](index.md)
