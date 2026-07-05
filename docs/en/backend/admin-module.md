# Admin module

The admin module provides operational visibility: MCP call logging, Celery queue metrics, runtime config inspection, and live log streaming. Admin endpoints are mounted under `/admin/*` alongside health checks.

**Source modules:** `eagle_rag/admin/mcp_log.py`, `eagle_rag/admin/metrics.py`, `eagle_rag/admin/system_setting.py`, `eagle_rag/api/health.py`

---

## 1. Theoretical background

### 1.1 Observability in RAG pipelines

Production RAG systems require monitoring across ingest, retrieval, and generation stages (Gao et al., arXiv:2312.10997). Eagle-RAG implements three observability pillars:

| Pillar | Implementation |
|--------|---------------|
| **Metrics** | Prometheus `/metrics` + queue depth sampling |
| **Logs** | structlog JSONL (AI events) + loguru (ops) |
| **Traces** | OpenTelemetry (optional OTLP export) |

### 1.2 Time-series queue metrics

Celery queue depth is sampled every 30 seconds into `metric_samples` — enabling trend analysis and alerting on ingest backlogs without direct Redis inspection.

---

## 2. Admin endpoints

**Module:** `eagle_rag/api/health.py` (`admin_router`)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/admin/config` | Sanitized settings snapshot (secrets masked) |
| GET | `/admin/mcp/logs` | MCP call history |
| GET | `/admin/metrics/queues` | Queue depth time series |
| GET | `/admin/metrics/queues/latest` | Current queue depths |
| GET | `/admin/logs/stream` | SSE live log tail |
| GET | `/admin/knowhere/status` | Knowhere service health |
| GET | `/admin/system-settings` | DB-persisted overrides |
| PUT | `/admin/system-settings/{key}` | Update runtime setting |

---

## 3. Code walkthrough: MCP call log

**Module:** `eagle_rag/admin/mcp_log.py`

Every MCP tool invocation records:

| Field | Content |
|-------|---------|
| `tool_name` | ingest/query/retrieve_text/retrieve_visual |
| `arguments` | JSON args (query truncated) |
| `result_summary` | Status, hit count, error type |
| `caller` | `mcp` |
| `latency_ms` | Wall clock |
| `timestamp` | UTC |

Stored in `mcp_call_log` PostgreSQL table. Non-blocking — log write failure doesn't affect tool response.

---

## 4. Code walkthrough: queue metrics

**Module:** `eagle_rag/admin/metrics.py`

### Celery Beat task

```python
@celery_app.task(name="eagle_rag.admin.metrics.sample_queue_metrics")
def sample_queue_metrics():
    for queue in ["router_queue", "knowhere_queue", "pixelrag_queue"]:
        depth = inspect_active_queue(queue)
        insert_metric_sample(queue_name=queue, depth=depth)
```

Schedule: every 30s via `celery_app.conf.beat_schedule`.

### Query API

Returns time series from `metric_samples` table for dashboard charting.

---

## 5. Code walkthrough: config snapshot

`GET /admin/config` returns the full `Settings` model with secrets replaced by `***`:

- Useful for verifying effective configuration without SSH access.
- Mirrors frontend `AdminConfigOut` TypeScript type.

---

## 6. Live log streaming

`GET /admin/logs/stream` — SSE endpoint tailing:

- `logs/eagle_rag.log` (ops loguru output)
- Optional Redis pub/sub channel (`telemetry.redis_log_channel`)

Frontend admin dashboard connects for real-time ingest progress monitoring.

---

## 7. Milvus health checks

Admin health probes verify Milvus connectivity:

```python
count_text()    # eagle_text reachable
count_visual()  # eagle_visual reachable
```

Included in `GET /health` aggregate status alongside PostgreSQL, Redis, and Knowhere.

---

## 8. Design tensions and tuning

| Tension | Signal | False positive / negative | Dial |
| --- | --- | --- | --- |
| **Celery ping timeout** | 1.0s `inspect.ping` in `/health` | Slow worker → `down` during heavy embed | Check queue depth, not only ping |
| **Metrics sampling gap** | 30s beat interval | Sub-minute backlog spikes invisible on chart | Redis `LLEN` for incidents |
| **MCP log retention** | DB-backed call log | High agent traffic fills table | External log drain if needed |
| **Redis log stream fallback** | In-memory queue when Redis down | SSE logs lost on API restart | Fix Redis first; fallback is dev-only |
| **Milvus list_collections probe** | Health check on cold Milvus | `down` during Milvus restart window | Expect transient yellow during rolling upgrade |
| **AI logger volume** | `retrieve` / `rerank` per query | Log storage cost in high QPS | Sample or ship to external observability |

---

## 9. Config & tuning

```yaml
telemetry:
  ai_log_file: logs/ai_telemetry.jsonl
  op_log_file: logs/eagle_rag.log
  tracing_enabled: false
  otlp_endpoint: ""

mcp:
  tool_timeout: 30
  circuit_fail_threshold: 5
  cache_ttl: 300
```

---

## 10. Tests

| Test file | Coverage |
|-----------|----------|
| `tests/test_api_admin_health.py` | Admin config, health, metrics |
| `tests/test_mcp_metrics.py` | MCP call logging |
| `tests/test_telemetry_logging.py` | AI event JSONL format |

---

## 11. AI telemetry events

**Module:** `eagle_rag/telemetry/` — structlog JSONL at `logs/ai_telemetry.jsonl`

Each pipeline stage emits structured events queryable by admin tooling:

| Event | Fields | Stage |
|-------|--------|-------|
| `ingest` | job_id, pipeline, kb_name, chunks, duration_ms | Celery tasks |
| `route` | mode, selected, reason, selector | Query routing |
| `retrieve` | retriever, top_k, hits, latency_ms | Milvus ANN |
| `rerank` | stage, kept, top, latency_ms | Cross-encoder |
| `generate` | model, prompt (truncated), completion, latency_ms | VLM |
| `llm_intent` | model, response, fallback | LLM routing |

Admin log stream can filter on these event types for end-to-end query tracing.

---

## 12. Prometheus metrics

**Module:** `eagle_rag/metrics.py`

| Metric | Type | Labels |
|--------|------|--------|
| `eagle_rag_mcp_calls_total` | Counter | tool_name, status |
| `eagle_rag_mcp_call_duration_seconds` | Histogram | tool_name |
| `eagle_rag_mcp_cache_hits_total` | Counter | — |

Scraped at `GET /metrics`. MCP tools decorated with `@with_metrics("tool_name")`.

---

## 13. System settings overrides

**Module:** `eagle_rag/admin/system_setting.py`

Runtime key-value overrides stored in `system_settings` PostgreSQL table. Allows changing router heuristics or feature flags without redeployment. `GET /admin/system-settings` returns all; `PUT /admin/system-settings/{key}` updates one.

Overrides are read after YAML/env config — highest priority in the settings resolution chain.

---

## 14. References

- Prometheus Python client: [github.com/prometheus/client_python](https://github.com/prometheus/client_python)
- OpenTelemetry: [opentelemetry.io/docs](https://opentelemetry.io/docs/)
- Celery monitoring: [docs.celeryq.dev/en/stable/userguide/monitoring.html](https://docs.celeryq.dev/en/stable/userguide/monitoring.html)
- Gao et al., *RAG Survey*, [arXiv:2312.10997](https://arxiv.org/abs/2312.10997)
