# 管理模块

管理模块提供运维可见性：MCP 调用日志、Celery 队列指标、运行时配置检查与实时日志流。管理端点与健康检查一并挂载在 `/admin/*` 下。

**源模块：** `eagle_rag/admin/mcp_log.py`、`eagle_rag/admin/metrics.py`、`eagle_rag/admin/system_setting.py`、`eagle_rag/api/health.py`

---

## 1. 理论背景

### 1.1 RAG 流水线中的可观测性

生产 RAG 系统需要在入库、检索与生成阶段进行监控（Gao 等，arXiv:2312.10997）。Eagle-RAG 实现三大可观测性支柱：

| 支柱 | 实现 |
|--------|---------------|
| **指标** | Prometheus `/metrics` + 队列深度采样 |
| **日志** | structlog JSONL（AI 事件）+ loguru（运维） |
| **追踪** | OpenTelemetry（可选 OTLP 导出） |

### 1.2 时序队列指标

Celery 队列深度每 30 秒采样到 `metric_samples` — 支持趋势分析与入库积压告警，无需直接查看 Redis。

---

## 2. 管理端点

**模块：** `eagle_rag/api/health.py`（`admin_router`）

| 方法 | 路径 | 用途 |
|--------|------|---------|
| GET | `/admin/config` | 脱敏设置快照（密钥掩码） |
| GET | `/admin/mcp/logs` | MCP 调用历史 |
| GET | `/admin/metrics/queues` | 队列深度时序 |
| GET | `/admin/metrics/queues/latest` | 当前队列深度 |
| GET | `/admin/logs/stream` | SSE 实时日志尾 |
| GET | `/admin/knowhere/status` | Knowhere 服务健康 |
| GET | `/admin/system-settings` | 数据库持久化覆盖 |
| PUT | `/admin/system-settings/{key}` | 更新运行时设置 |

---

## 3. 代码走读：MCP 调用日志

**模块：** `eagle_rag/admin/mcp_log.py`

每次 MCP 工具调用记录：

| 字段 | 内容 |
|-------|---------|
| `tool_name` | `core_ingest` / `core_query` / `core_retrieve_text` / `core_retrieve_visual`（profile 激活时还有域 `{namespace}_*`） |
| `arguments` | JSON 参数（query 截断） |
| `result_summary` | 状态、命中数、错误类型 |
| `caller` | `mcp` |
| `latency_ms` | 墙钟时间 |
| `timestamp` | UTC |

存入 PostgreSQL `mcp_call_log` 表。非阻塞 — 写日志失败不影响工具响应。

---

## 4. 代码走读：队列指标

**模块：** `eagle_rag/admin/metrics.py`

### Celery Beat 任务

```python
@celery_app.task(name="eagle_rag.admin.metrics.sample_queue_metrics")
def sample_queue_metrics():
    for queue in ["router_queue", "knowhere_queue", "pixelrag_queue"]:
        depth = inspect_active_queue(queue)
        insert_metric_sample(queue_name=queue, depth=depth)
```

调度：经 `celery_app.conf.beat_schedule` 每 30s。

### 查询 API

从 `metric_samples` 表返回时序，供面板图表使用。

---

## 5. 代码走读：配置快照

`GET /admin/config` 返回完整 `Settings` 模型，密钥替换为 `***`：

- 无需 SSH 即可核对生效配置。
- 对应前端 `AdminConfigOut` TypeScript 类型。

---

## 6. 实时日志流

`GET /admin/logs/stream` — SSE 端点尾随：

- `logs/eagle_rag.log`（运维 loguru 输出）
- 可选 Redis pub/sub 通道（`telemetry.redis_log_channel`）

管理面板连接以实时监控入库进度。

---

## 7. Milvus 健康检查

管理健康探测验证 Milvus 连通性：

```python
count_text()    # eagle_text 可达
count_visual()  # eagle_visual 可达
```

包含在 `GET /health` 聚合状态中，与 PostgreSQL、Redis、Knowhere 并列。

---

## 8. 设计张力与调优

| 张力 | 信号 | 假阳/假阴 | 调节 |
| --- | --- | --- | --- |
| **Celery ping 超时** | `/health` 中 1.0s `inspect.ping` | 重 embed 时慢 worker → `down` | 不仅看 ping，还要看队列深度 |
| **指标采样间隔** | 30s beat | 分钟级积压尖峰图表不可见 | 事故时用 Redis `LLEN` |
| **MCP 日志保留** | DB 调用日志 | 高 Agent 流量撑满表 | 需要时外排日志 |
| **Redis 日志流回退** | Redis 宕机时内存队列 | API 重启丢 SSE 日志 | 先修 Redis；回退仅适合开发 |
| **Milvus list_collections 探测** | 冷启动 Milvus 健康检查 | Milvus 重启窗口内 `down` | 滚动升级时预期短暂黄灯 |
| **AI logger 体量** | 每查询 `retrieve` / `rerank` | 高 QPS 日志存储成本 | 采样或外送可观测性 |

---

## 9. 配置与调优

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

## 10. 测试

| 测试文件 | 覆盖 |
|-----------|----------|
| `tests/test_api_admin_health.py` | 管理配置、健康、指标 |
| `tests/test_mcp_metrics.py` | MCP 调用日志 |
| `tests/test_telemetry_logging.py` | AI 事件 JSONL 格式 |

---

## 11. AI 遥测事件

**模块：** `eagle_rag/telemetry/` — structlog JSONL 位于 `logs/ai_telemetry.jsonl`

各流水线阶段发出结构化事件，供管理工具查询：

| 事件 | 字段 | 阶段 |
|-------|--------|-------|
| `ingest` | job_id, pipeline, kb_name, chunks, duration_ms | Celery 任务 |
| `route` | mode, selected, reason, selector | 查询路由 |
| `retrieve` | retriever, top_k, hits, latency_ms | Milvus ANN |
| `rerank` | stage, kept, top, latency_ms | 交叉编码器 |
| `generate` | model, prompt（截断）, completion, latency_ms | VLM |
| `llm_intent` | model, response, fallback | LLM 路由 |

管理日志流可按这些事件类型过滤，做端到端查询追踪。

---

## 12. Prometheus 指标

**模块：** `eagle_rag/metrics.py`

| 指标 | 类型 | 标签 |
|--------|------|--------|
| `eagle_rag_mcp_calls_total` | Counter | tool_name, status |
| `eagle_rag_mcp_call_duration_seconds` | Histogram | tool_name |
| `eagle_rag_mcp_cache_hits_total` | Counter | — |

在 `GET /metrics` 抓取。MCP 工具使用 `@with_metrics("tool_name")` 装饰。

---

## 13. 系统设置覆盖

**模块：** `eagle_rag/admin/system_setting.py`

运行时键值覆盖存在 PostgreSQL `system_settings` 表。可在不重新部署的情况下更改路由启发式或功能开关。`GET /admin/system-settings` 返回全部；`PUT /admin/system-settings/{key}` 更新单项。

覆盖在 YAML/env 配置之后读取 — 设置解析链中优先级最高。

---

## 14. 参考文献

- Prometheus Python client：[github.com/prometheus/client_python](https://github.com/prometheus/client_python)
- OpenTelemetry：[opentelemetry.io/docs](https://opentelemetry.io/docs/)
- Celery monitoring：[docs.celeryq.dev/en/stable/userguide/monitoring.html](https://docs.celeryq.dev/en/stable/userguide/monitoring.html)
- Gao 等，*RAG Survey*，[arXiv:2312.10997](https://arxiv.org/abs/2312.10997)
