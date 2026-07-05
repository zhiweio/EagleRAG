"""Service health and ops endpoints.

Exposes two ``APIRouter`` instances:

- ``router`` (``/health``, ``/mcp/tools``): real connectivity probes for
  dependencies (asyncio.gather concurrency, per-probe try/except, 3s timeout),
  plus an MCP tool listing placeholder.
- ``admin_router`` (``/admin/*``): ops views covering Celery/Milvus/PixelRAG/
  Knowhere/VLM/MCP/config/probes, plus the ``/admin/logs`` SSE live log stream.

Under the new architecture PixelRAG is demoted to a "visual encoder + slicer"
library call (pixelrag_render / pixelrag_embed) and no longer has a standalone
serve deployment; Knowhere is called via HTTP :5005; Milvus keeps dual
Collections (eagle_text + eagle_visual). Health probes adjusted accordingly:
- pixelrag probe checks library availability (import success) instead of serve
  connectivity;
- knowhere probe is new (HTTP GET base_url);
- milvus probe still lists collections; admin/milvus shows row counts for both
  Collections.

No auth. All probes are read-only and do not modify any external state.
"""

from __future__ import annotations

import asyncio
import time
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, HTTPException
from sse_starlette.sse import EventSourceResponse

from eagle_rag import __version__
from eagle_rag.admin.mcp_log import list_recent_mcp_calls
from eagle_rag.admin.metrics import get_metric_aggregate, get_queue_backlog_series
from eagle_rag.admin.system_setting import get_setting, set_setting
from eagle_rag.api.schemas.health import (
    AdminActionDetail,
    AdminActionResult,
    AdminCeleryResponse,
    AdminConfigOut,
    AdminKnowhereResponse,
    AdminMcpResponse,
    AdminMilvusResponse,
    AdminMinioResponse,
    AdminPixelragResponse,
    AdminProbesResponse,
    AdminRedisResponse,
    AdminVlmResponse,
    CeleryActiveTaskOut,
    CeleryQueueInfo,
    CollectionDetailOut,
    DependencyStatus,
    DependencySummary,
    HealthResponse,
    KbPartitionOut,
    McpCallLogOut,
    McpToolDefinition,
    McpToolsResponse,
    MilvusCollectionOut,
    MinioBucketOut,
    ModelRouterOut,
    ModelRouterUpdate,
    ProbeConfigOut,
    ProbeDetail,
    QueueSeriesPoint,
    RedisInfoOut,
    ResourceLimitOut,
    ResourceLimitsOut,
    WorkerDetailOut,
)
from eagle_rag.config import get_settings
from eagle_rag.db import async_fetch, async_fetchrow
from eagle_rag.tasks.celery_app import app as celery_app
from eagle_rag.telemetry import get_logger

__all__ = ["router", "admin_router"]

logger = get_logger(__name__)

_PROBE_TIMEOUT = 3.0

router = APIRouter(tags=["health"])
admin_router = APIRouter(prefix="/admin", tags=["admin"])

# ---------------------------------------------------------------------------
# Uptime tracking: record the monotonic timestamp when each dependency was first
# observed up; clear on down. In-process state; API restart resets the timer
# (does not affect trend display). Duration formatting reuses the mature
# ``humanize.naturaldelta`` library (localized, multi-language).
# ---------------------------------------------------------------------------
_UPTIME_SINCE: dict[str, float] = {}


def _format_duration(seconds: float) -> str:
    """Convert seconds to a human-readable duration via ``humanize.naturaldelta``.

    naturaldelta accepts a ``timedelta`` and returns strings like '14 days' /
    '5 hours' / '3 minutes' / '12 seconds' / 'a second'; returns an empty string
    for negative seconds (unknown/invalid).
    """
    import humanize

    if seconds < 0:
        return ""
    delta = timedelta(seconds=seconds)
    return humanize.naturaldelta(delta)


def _update_uptime(results: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Update ``_UPTIME_SINCE`` from this probe round; return {name: uptime_str}.

    On up: record the current monotonic time if not already recorded. On
    down/unknown: clear the record. The returned uptime string is non-empty only
    when status=up and a record exists.
    """
    now = time.monotonic()
    uptime_map: dict[str, str] = {}
    for name, res in results.items():
        status = res.get("status")
        if status == "up":
            if name not in _UPTIME_SINCE:
                _UPTIME_SINCE[name] = now
            uptime_map[name] = _format_duration(now - _UPTIME_SINCE[name])
        else:
            _UPTIME_SINCE.pop(name, None)
            uptime_map[name] = ""
    return uptime_map


# ---------------------------------------------------------------------------
# Probe primitives: each returns {"status": "up"|"down"|"unknown", "detail": str}
# ---------------------------------------------------------------------------


def _milvus_probe_sync() -> dict[str, Any]:
    """Probe Milvus synchronously: connect with MilvusClient and list_collections."""
    from pymilvus import MilvusClient

    cfg = get_settings().milvus
    client = MilvusClient(uri=f"http://{cfg.host}:{cfg.port}")
    try:
        cols = client.list_collections()
        return {"status": "up", "detail": f"collections={len(cols)}"}
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass


async def _probe_milvus() -> dict[str, Any]:
    return await asyncio.to_thread(_milvus_probe_sync)


async def _probe_pixelrag() -> dict[str, Any]:
    """Probe PixelRAG library availability (can pixelrag_render / pixelrag_embed be imported).

    PixelRAG is now a library call, no longer deployed as a standalone serve.
    The library is an **optional dependency** (pyproject ``[vision]`` extra,
    commented out by default); when not enabled the system falls back to mock and
    still works. Therefore a missing install is reported as ``unknown`` (optional
    dependency not enabled) rather than ``down`` (service failure) -- this avoids
    conflating with a real "should be up but isn't" failure and keeps dashboard
    coloring/semantics accurate.
    """
    import importlib.util

    def _check() -> dict[str, Any]:
        modules = [m for m in ("pixelrag_render", "pixelrag_embed") if importlib.util.find_spec(m)]
        if modules:
            return {"status": "up", "detail": f"libraries={','.join(modules)}"}
        return {
            "status": "unknown",
            "detail": "optional vision extra not installed (mock fallback)",
        }

    return await asyncio.to_thread(_check)


async def _probe_knowhere() -> dict[str, Any]:
    """Probe the Knowhere parser service (HTTP :5005) availability."""
    import httpx

    base_url = get_settings().knowhere.base_url
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
            # Try the root path or health endpoint.
            resp = await client.get(base_url)
            return {
                "status": "up",
                "detail": f"base_url={base_url}, status_code={resp.status_code}",
            }
    except Exception as exc:  # noqa: BLE001
        return {"status": "down", "detail": f"{type(exc).__name__}: {exc}"}


async def _probe_vlm() -> dict[str, Any]:
    """Lightweight VLM probe: ``GET {base_url}/models`` (OpenAI-compatible, free, no token cost).

    - api_key empty -> down (not configured)
    - GET /models returns 200 -> up (API reachable and auth passes)
    - GET /models returns 401/403 -> down (auth failed)
    - Network error / timeout -> down

    Uses the OpenAI-compatible ``/models`` endpoint rather than ``complete()``:
    only lists available models, generates no tokens, zero cost and fast. Both
    DashScope (qwen-vl-max) and DeepSeek are compatible with this endpoint.
    """
    import httpx

    cfg = get_settings().vlm
    if not cfg.api_key:
        return {"status": "down", "detail": "api_key not set"}
    url = f"{cfg.base_url.rstrip('/')}/models"
    try:
        async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {cfg.api_key}"})
    except Exception as exc:  # noqa: BLE001
        return {"status": "down", "detail": f"{type(exc).__name__}: {exc}"}
    if resp.status_code == 200:
        # Best-effort parse of model count (some implementations return {"data": [...]}).
        try:
            n = len(resp.json().get("data", []))
            return {"status": "up", "detail": f"base_url={cfg.base_url}, models={n}"}
        except Exception:  # noqa: BLE001
            return {"status": "up", "detail": f"base_url={cfg.base_url}, status_code=200"}
    return {"status": "down", "detail": f"status_code={resp.status_code}"}


def _redis_probe_sync() -> dict[str, Any]:
    import redis

    url = get_settings().celery.broker_url
    client = redis.Redis.from_url(
        url, socket_connect_timeout=_PROBE_TIMEOUT, socket_timeout=_PROBE_TIMEOUT
    )
    try:
        client.ping()
        return {"status": "up", "detail": f"broker={url}"}
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass


async def _probe_redis() -> dict[str, Any]:
    return await asyncio.to_thread(_redis_probe_sync)


def _minio_probe_sync() -> dict[str, Any]:
    from eagle_rag.storage.minio_client import get_minio_client

    cfg = get_settings().minio
    client = get_minio_client()
    buckets = client.list_buckets()
    return {"status": "up", "detail": f"endpoint={cfg.endpoint}, buckets={len(buckets)}"}


async def _probe_minio() -> dict[str, Any]:
    return await asyncio.to_thread(_minio_probe_sync)


def _celery_probe_sync() -> dict[str, Any]:
    # Note: Celery 5.6 ``inspect.ping()`` runs for the entire inspect.timeout even
    # after all workers have already ponged (it broadcasts to all workers then waits
    # to aggregate responses). Measured ``timeout=3`` -> ~3.2s elapsed, exceeding
    # the ``wait_for(3s)`` cap from ``_PROBE_TIMEOUT`` -> ``asyncio.TimeoutError``
    # -> /health falsely marks celery as down. 1.0s is enough to cover the broadcast
    # latency for 3 local workers (measured ~1.5s to return) and leaves 2s of buffer
    # for ``wait_for`` to absorb edge jitter and avoid the false positive.
    inspect = celery_app.control.inspect(timeout=1.0)
    ping = inspect.ping()
    if ping:
        return {"status": "up", "detail": f"workers={len(ping)}"}
    return {"status": "down", "detail": "no worker responded"}


async def _probe_celery() -> dict[str, Any]:
    return await asyncio.to_thread(_celery_probe_sync)


async def _probe_postgres() -> dict[str, Any]:
    import asyncpg

    dsn = get_settings().postgres.dsn
    conn = await asyncpg.connect(dsn=dsn, timeout=_PROBE_TIMEOUT)
    try:
        await conn.fetchval("SELECT 1")
        return {"status": "up", "detail": "SELECT 1 ok"}
    finally:
        try:
            await conn.close()
        except Exception:  # noqa: BLE001
            pass


# Probe registry: order is fixed for stable frontend display.
_PROBES: dict[str, Any] = {
    "milvus": _probe_milvus,
    "knowhere": _probe_knowhere,
    "pixelrag": _probe_pixelrag,
    "vlm": _probe_vlm,
    "redis": _probe_redis,
    "minio": _probe_minio,
    "celery": _probe_celery,
    "postgres": _probe_postgres,
}


async def _run_probe(name: str, fn: Any) -> dict[str, Any]:
    """Run a single probe, attach latency_ms, never raise."""
    start = time.perf_counter()
    try:
        result = await asyncio.wait_for(fn(), timeout=_PROBE_TIMEOUT)
        latency = int((time.perf_counter() - start) * 1000)
        status = result.get("status", "down")
        detail = result.get("detail", "")
        return {"status": status, "detail": detail, "latency_ms": latency}
    except TimeoutError:
        latency = int((time.perf_counter() - start) * 1000)
        return {
            "status": "down",
            "detail": f"timeout after {_PROBE_TIMEOUT}s",
            "latency_ms": latency,
        }
    except Exception as exc:  # noqa: BLE001
        latency = int((time.perf_counter() - start) * 1000)
        return {"status": "down", "detail": f"{type(exc).__name__}: {exc}", "latency_ms": latency}


async def _probe_all() -> dict[str, dict[str, Any]]:
    """Run all probes concurrently; return {name: {status, detail, latency_ms}}."""
    names = list(_PROBES.keys())
    results = await asyncio.gather(*[_run_probe(n, _PROBES[n]) for n in names])
    return dict(zip(names, results, strict=True))


def _aggregate_status(deps: dict[str, dict[str, Any]]) -> str:
    """Return 'degraded' if any dependency is down, else 'ok' (unknown does not degrade)."""
    return "degraded" if any(d["status"] == "down" for d in deps.values()) else "ok"


def _dependency_status(value: str) -> DependencyStatus:
    try:
        return DependencyStatus(value)
    except ValueError:
        return DependencyStatus.unknown


# ---------------------------------------------------------------------------
# Health endpoints
# ---------------------------------------------------------------------------


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Dependency health probe.

    Probes 8 dependencies concurrently; any down -> status=degraded (still
    returns 200).
    """
    deps_full = await _probe_all()
    uptime_map = _update_uptime(deps_full)
    deps = {
        name: DependencySummary(
            status=_dependency_status(v["status"]),
            detail=v.get("detail", ""),
            uptime=uptime_map.get(name, ""),
        )
        for name, v in deps_full.items()
    }
    return HealthResponse(
        status=_aggregate_status(deps_full),
        app=get_settings().app.name,
        version=__version__,
        dependencies=deps,
    )


@router.get("/mcp/tools", response_model=McpToolsResponse)
async def mcp_tools() -> McpToolsResponse:
    """List registered MCP tools.

    Reads ``eagle_rag.api.mcp_server.TOOL_DEFINITIONS`` (mirrors the functions
    registered with FastMCP ``@mcp.tool``) and returns
    ``[{"name", "description", "parameters"}]``. On module import failure returns
    an empty list plus an error field (graceful degradation, does not block
    /health).
    """
    try:
        from eagle_rag.api.mcp_server import TOOL_DEFINITIONS

        tools = [McpToolDefinition.model_validate(t) for t in TOOL_DEFINITIONS]
        return McpToolsResponse(tools=tools)
    except Exception as exc:  # noqa: BLE001
        return McpToolsResponse(tools=[], error=f"{type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# Admin endpoints
# ---------------------------------------------------------------------------


@admin_router.get("/celery", response_model=AdminCeleryResponse)
async def admin_celery() -> AdminCeleryResponse:
    """Celery workers / active tasks / queue lengths.

    On no worker response or inspect timeout, **degrades gracefully** to empty
    workers with best-effort queue lengths (Redis broker BACKLOG is still
    readable) and does not raise 503. Only when inspect raises a real exception
    (e.g. broker unreachable) is 503 returned; the detail includes
    ``type(exc).__name__`` so that exceptions with empty ``str()`` (like
    ``asyncio.TimeoutError``) do not produce a blank detail.
    """

    def _read_queue_sizes() -> list[dict[str, Any]]:
        """Read per-queue LIST length from the Redis broker (best-effort).

        On failure returns an {error} record.
        """
        queues: list[dict[str, Any]] = []
        try:
            import redis

            client = redis.Redis.from_url(
                get_settings().celery.broker_url,
                socket_connect_timeout=_PROBE_TIMEOUT,
                socket_timeout=_PROBE_TIMEOUT,
            )
            try:
                for qname in get_settings().celery.queues:
                    queues.append({"queue": qname, "size": int(client.llen(qname))})
            finally:
                client.close()
        except Exception as exc:  # noqa: BLE001
            queues.append({"error": f"redis unavailable: {type(exc).__name__}"})
        return queues

    def _inspect_sync() -> dict[str, Any]:
        inspect = celery_app.control.inspect(timeout=_PROBE_TIMEOUT)
        ping = inspect.ping() or {}
        # No worker responded: active()/stats() would each idle for the full
        # timeout then return None/{}, totaling ~2x timeout and triggering the
        # outer ``asyncio.wait_for`` -> ``asyncio.TimeoutError`` (whose ``str()``
        # is empty -> blank detail) -> a false 503. Degrade gracefully: skip
        # active/stats and still try to read Redis queue lengths (best-effort).
        if not ping:
            return {
                "workers": [],
                "active_tasks": [],
                "worker_details": [],
                "queues": _read_queue_sizes(),
            }
        active = inspect.active() or {}
        # stats: {worker_name: {pid, rusage: {rss: bytes, ...}, ...}}
        stats = inspect.stats() or {}
        active_tasks: list[dict[str, Any]] = []
        for worker, tasks in active.items():
            for t in tasks:
                active_tasks.append({"worker": worker, **t})
        # worker_details: pid / state / current / memory (rss bytes -> MB).
        worker_details: list[dict[str, Any]] = []
        for worker in ping.keys():
            wstat = stats.get(worker) or {}
            rusage = wstat.get("rusage") or {}
            rss_bytes = rusage.get("rss")
            memory_mb: float | None = None
            if rss_bytes is not None:
                try:
                    memory_mb = float(rss_bytes) / 1024.0 / 1024.0
                except (TypeError, ValueError):  # noqa: BLE001
                    memory_mb = None
            wactive = active.get(worker) or []
            current = wactive[0].get("name") if wactive else None
            state = "active" if current else "idle"
            worker_details.append(
                {
                    "name": worker,
                    "pid": wstat.get("pid"),
                    "state": state,
                    "current": current,
                    "memory": memory_mb,
                }
            )
        return {
            "workers": list(ping.keys()),
            "active_tasks": active_tasks,
            "queues": _read_queue_sizes(),
            "worker_details": worker_details,
        }

    try:
        payload = await asyncio.wait_for(
            asyncio.to_thread(_inspect_sync),
            timeout=_PROBE_TIMEOUT * 3 + 2,  # accommodate serial ping/active/stats + queue reads
        )
        # pending: aggregate per-queue size (best-effort; skip error entries).
        pending: int | None = None
        try:
            sizes = [q["size"] for q in payload["queues"] if q.get("size") is not None]
            if sizes:
                pending = int(sum(sizes))
            else:
                pending = 0
        except Exception:  # noqa: BLE001
            pending = None
        # succeeded: success count in task_audit over the last 24h (best-effort;
        # returns None if the table is missing or the query fails).
        succeeded: int | None = None
        try:
            row = await async_fetchrow(
                "SELECT COUNT(*)::int AS cnt FROM task_audit "
                "WHERE status='success' AND created_at >= NOW() - INTERVAL '24 hours'"
            )
            if row is not None:
                succeeded = row["cnt"]
        except Exception:  # noqa: BLE001
            succeeded = None
        # queue_backlog_series: last 20 sampled time-series points (best-effort;
        # empty list on failure).
        queue_backlog_series: list[QueueSeriesPoint] = []
        try:
            series = await get_queue_backlog_series(limit=20)
            queue_backlog_series = [
                QueueSeriesPoint(
                    sampled_at=p.get("sampled_at", ""),
                    knowhere=p.get("knowhere", 0.0),
                    pixelrag=p.get("pixelrag", 0.0),
                    router=p.get("router", 0.0),
                )
                for p in series
            ]
        except Exception:  # noqa: BLE001
            queue_backlog_series = []
        return AdminCeleryResponse(
            workers=list(payload["workers"]),
            active_tasks=[
                CeleryActiveTaskOut.model_validate(task) for task in payload["active_tasks"]
            ],
            queues=[CeleryQueueInfo.model_validate(q) for q in payload["queues"]],
            worker_details=[WorkerDetailOut.model_validate(w) for w in payload["worker_details"]],
            pending=pending,
            succeeded=succeeded,
            queue_backlog_series=queue_backlog_series,
        )
    except Exception as exc:  # noqa: BLE001
        # Include the exception type name so exceptions with empty ``str()`` (like
        # ``asyncio.TimeoutError``) do not produce a blank detail.
        raise HTTPException(
            status_code=503,
            detail=f"celery inspect failed: {type(exc).__name__}: {exc}",
        ) from exc


def _mask_url(url: str) -> str:
    """Mask the password in a URL: ``redis://:pass@host`` -> ``redis://***@host``.

    Returned unchanged when there is no password or parsing fails. Used for
    display only; does not affect the real connection.
    """
    from urllib.parse import urlparse, urlunparse

    try:
        parsed = urlparse(url)
        if parsed.password:
            # Replace the password part of userinfo with *** (keep the username).
            user = parsed.username or ""
            netloc = f"{user}:***@{parsed.hostname or ''}"
            if parsed.port:
                netloc = f"{netloc}:{parsed.port}"
            return urlunparse(parsed._replace(netloc=netloc))
    except Exception:  # noqa: BLE001
        pass
    return url


@admin_router.get("/minio", response_model=AdminMinioResponse)
async def admin_minio() -> AdminMinioResponse:
    """MinIO object storage overview.

    Endpoint / default bucket / bucket list (with best-effort object count).

    Reuses ``_probe_minio`` for status / detail / latency_ms; when the probe is
    up, lists buckets and does a best-effort object count on the default bucket
    (capped at 10000 to avoid scanning a huge bucket and blocking). Any exception
    degrades gracefully to ``status="down"`` + an ``error`` field, not a 503.
    """
    cfg = get_settings().minio
    probe = await _run_probe("minio", _probe_minio)

    def _list_buckets_sync() -> list[dict[str, Any]]:
        from eagle_rag.storage.minio_client import get_minio_client

        client = get_minio_client()
        default_bucket = cfg.bucket
        buckets: list[dict[str, Any]] = []
        for b in client.list_buckets():
            entry: dict[str, Any] = {
                "name": b.name,
                "creation_date": b.creation_date.isoformat() if b.creation_date else None,
                "object_count": None,
                "is_default": b.name == default_bucket,
            }
            # Best-effort object count only for the default bucket (list_objects is
            # heavy, and non-default buckets usually hold no business data).
            if b.name == default_bucket:
                try:
                    count = 0
                    for _obj in client.list_objects(b.name):
                        count += 1
                        if count >= 10000:  # safety cap to avoid huge-bucket blocking
                            break
                    entry["object_count"] = count
                except Exception:  # noqa: BLE001
                    pass
            buckets.append(entry)
        return buckets

    if probe.get("status") != "up":
        return AdminMinioResponse(
            endpoint=cfg.endpoint,
            secure=cfg.secure,
            bucket=cfg.bucket,
            buckets=[],
            status=_dependency_status(probe.get("status", "down")),
            detail=probe.get("detail", ""),
            latency_ms=int(probe.get("latency_ms", 0)),
            error=probe.get("detail") or None,
        )

    try:
        raw_buckets = await asyncio.wait_for(
            asyncio.to_thread(_list_buckets_sync),
            timeout=_PROBE_TIMEOUT * 2,
        )
    except Exception as exc:  # noqa: BLE001
        return AdminMinioResponse(
            endpoint=cfg.endpoint,
            secure=cfg.secure,
            bucket=cfg.bucket,
            buckets=[],
            status=DependencyStatus.down,
            detail=f"list_buckets failed: {type(exc).__name__}: {exc}",
            latency_ms=int(probe.get("latency_ms", 0)),
            error=f"{type(exc).__name__}: {exc}",
        )

    return AdminMinioResponse(
        endpoint=cfg.endpoint,
        secure=cfg.secure,
        bucket=cfg.bucket,
        buckets=[MinioBucketOut.model_validate(b) for b in raw_buckets],
        status=_dependency_status(probe.get("status", "up")),
        detail=probe.get("detail", ""),
        latency_ms=int(probe.get("latency_ms", 0)),
        error=None,
    )


@admin_router.get("/redis", response_model=AdminRedisResponse)
async def admin_redis() -> AdminRedisResponse:
    """Redis broker overview: broker_url / db_size / key INFO fields.

    Reuses ``_probe_redis`` for status / detail / latency_ms; when the probe is
    up, reads ``client.info()`` and ``client.dbsize()``. Any exception degrades
    gracefully to ``status="down"`` + an ``error`` field, not a 503.
    """
    broker_url = get_settings().celery.broker_url
    masked_url = _mask_url(broker_url)
    probe = await _run_probe("redis", _probe_redis)

    def _inspect_sync() -> dict[str, Any]:
        import redis

        client = redis.Redis.from_url(
            broker_url,
            socket_connect_timeout=_PROBE_TIMEOUT,
            socket_timeout=_PROBE_TIMEOUT,
        )
        try:
            info = client.info()
            return {
                "db_size": int(client.dbsize()),
                "info": {
                    "version": info.get("redis_version"),
                    "uptime_days": (
                        int(info["uptime_in_days"])
                        if info.get("uptime_in_days") is not None
                        else None
                    ),
                    "connected_clients": (
                        int(info["connected_clients"])
                        if info.get("connected_clients") is not None
                        else None
                    ),
                    "used_memory_human": info.get("used_memory_human"),
                    "used_memory_peak_human": info.get("used_memory_peak_human"),
                    "role": info.get("role"),
                    "maxmemory_human": info.get("maxmemory_human"),
                },
            }
        finally:
            try:
                client.close()
            except Exception:  # noqa: BLE001
                pass

    if probe.get("status") != "up":
        return AdminRedisResponse(
            broker_url=masked_url,
            db_size=None,
            info=None,
            status=_dependency_status(probe.get("status", "down")),
            detail=probe.get("detail", ""),
            latency_ms=int(probe.get("latency_ms", 0)),
            error=probe.get("detail") or None,
        )

    try:
        payload = await asyncio.wait_for(
            asyncio.to_thread(_inspect_sync),
            timeout=_PROBE_TIMEOUT * 2,
        )
    except Exception as exc:  # noqa: BLE001
        return AdminRedisResponse(
            broker_url=masked_url,
            db_size=None,
            info=None,
            status=DependencyStatus.down,
            detail=f"info failed: {type(exc).__name__}: {exc}",
            latency_ms=int(probe.get("latency_ms", 0)),
            error=f"{type(exc).__name__}: {exc}",
        )

    return AdminRedisResponse(
        broker_url=masked_url,
        db_size=payload.get("db_size"),
        info=RedisInfoOut.model_validate(payload.get("info", {})),
        status=_dependency_status(probe.get("status", "up")),
        detail=probe.get("detail", ""),
        latency_ms=int(probe.get("latency_ms", 0)),
        error=None,
    )


@admin_router.get("/milvus", response_model=AdminMilvusResponse)
async def admin_milvus() -> AdminMilvusResponse:
    """List Milvus collections and per-collection row count (num_entities)."""

    def _milvus_admin_sync() -> dict[str, Any]:
        from pymilvus import DataType, MilvusClient

        cfg = get_settings().milvus
        client = MilvusClient(uri=f"http://{cfg.host}:{cfg.port}")
        try:
            collections: list[dict[str, Any]] = []
            collection_details: list[dict[str, Any]] = []
            for name in client.list_collections():
                # num_entities (existing logic).
                try:
                    stats = client.get_collection_stats(name)
                    row_count = int(stats.get("row_count", 0))
                    collections.append({"name": name, "num_entities": row_count})
                except Exception as exc:  # noqa: BLE001
                    collections.append({"name": name, "num_entities": None, "error": str(exc)})

                # Collection detail: fields / dim / metric_type / index_type.
                detail: dict[str, Any] = {"name": name}
                try:
                    desc = client.describe_collection(name)
                    fields_out: list[dict[str, Any]] = []
                    vector_field_name: str | None = None
                    for f in desc.get("fields", []):
                        fname = f.get("name", "")
                        ftype = f.get("type")
                        dtype_str = ""
                        if ftype is not None:
                            try:
                                dtype_str = DataType(ftype).name
                            except Exception:  # noqa: BLE001
                                dtype_str = str(ftype)
                        fields_out.append(
                            {
                                "name": fname,
                                "dtype": dtype_str,
                                "is_primary": bool(f.get("is_primary", False)),
                            }
                        )
                        # Identify the vector field and extract dim.
                        if ftype is not None:
                            try:
                                dt = DataType(ftype)
                                if dt.name.endswith("_VECTOR"):
                                    vector_field_name = fname
                                    params = f.get("params") or {}
                                    dim_val = params.get("dim")
                                    if dim_val is not None:
                                        detail["dim"] = int(dim_val)
                            except Exception:  # noqa: BLE001
                                pass
                    detail["fields"] = fields_out
                    # num_entities (best-effort fill).
                    if detail.get("num_entities") is None:
                        try:
                            st = client.get_collection_stats(name)
                            rc = st.get("row_count")
                            if rc is not None:
                                detail["num_entities"] = int(rc)
                        except Exception:  # noqa: BLE001
                            pass
                    # index_type / metric_type (best-effort).
                    try:
                        if vector_field_name is not None:
                            idx_info = client.describe_index(name, vector_field_name)
                        else:
                            idx_info = client.describe_index(name)
                        idx_list = idx_info if isinstance(idx_info, list) else [idx_info]
                        for idx in idx_list:
                            if not isinstance(idx, dict):
                                continue
                            if not detail.get("index_type") and idx.get("index_type"):
                                detail["index_type"] = str(idx.get("index_type"))
                            if not detail.get("metric_type") and idx.get("metric_type"):
                                detail["metric_type"] = str(idx.get("metric_type"))
                    except Exception:  # noqa: BLE001
                        pass
                except Exception as exc:  # noqa: BLE001
                    detail["error"] = str(exc)
                collection_details.append(detail)
            return {
                "collections": collections,
                "collection_details": collection_details,
            }
        finally:
            try:
                client.close()
            except Exception:  # noqa: BLE001
                pass

    payload = await asyncio.to_thread(_milvus_admin_sync)
    return AdminMilvusResponse(
        collections=[MilvusCollectionOut.model_validate(c) for c in payload["collections"]],
        collection_details=[
            CollectionDetailOut.model_validate(d) for d in payload["collection_details"]
        ],
        # index_size / memory: no reliable source yet; best-effort None.
        index_size=None,
        memory=None,
    )


def _milvus_action_sync(action: str) -> dict[str, Any]:
    """Run flush / compact on all Milvus collections; return a details list.

    action: "flush" -> ``client.flush(name)``; "compact" -> ``client.compact(name)``
    (falls back to ``Collection(name).compact()`` when MilvusClient has no
    compact). Each collection is wrapped in its own try/except; failures are
    recorded in detail.
    """
    from pymilvus import MilvusClient

    cfg = get_settings().milvus
    client = MilvusClient(uri=f"http://{cfg.host}:{cfg.port}")
    details: list[dict[str, Any]] = []
    try:
        names = client.list_collections()
        for name in names:
            try:
                if action == "flush":
                    client.flush(name)
                else:
                    # MilvusClient may lack a compact method; fall back to ORM API.
                    try:
                        client.compact(name)
                    except AttributeError:
                        from pymilvus import Collection, connections

                        if not connections.has_connection("default"):
                            connections.connect(uri=f"http://{cfg.host}:{cfg.port}")
                        Collection(name).compact()
                details.append({"collection": name, "action": action, "success": True})
            except Exception as exc:  # noqa: BLE001
                details.append(
                    {
                        "collection": name,
                        "action": action,
                        "success": False,
                        "detail": f"{type(exc).__name__}: {exc}",
                    }
                )
        return {"details": details}
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass


def _build_action_result(action: str, payload: dict[str, Any]) -> AdminActionResult:
    """Build an AdminActionResult from the payload returned by _milvus_action_sync."""
    details = [AdminActionDetail.model_validate(d) for d in payload.get("details", [])]
    ok_count = sum(1 for d in details if d.success)
    fail_count = len(details) - ok_count
    if not details:
        return AdminActionResult(
            success=True,
            message=f"No collections available for {action}",
            details=details,
        )
    if fail_count == 0:
        return AdminActionResult(
            success=True,
            message=f"{action} completed: all {ok_count} collection(s) succeeded",
            details=details,
        )
    return AdminActionResult(
        success=False,
        message=f"{action} partially failed: {ok_count} succeeded / {fail_count} failed",
        details=details,
    )


@admin_router.post("/milvus/flush", response_model=AdminActionResult)
async def admin_milvus_flush() -> AdminActionResult:
    """Force-flush all Milvus collections (persist sealed segments to disk)."""
    payload = await asyncio.to_thread(_milvus_action_sync, "flush")
    return _build_action_result("flush", payload)


@admin_router.post("/milvus/clean", response_model=AdminActionResult)
async def admin_milvus_clean() -> AdminActionResult:
    """Clean stale indexes: compact all Milvus collections.

    Merges segments and removes deleted entities.
    """
    payload = await asyncio.to_thread(_milvus_action_sync, "compact")
    return _build_action_result("compact", payload)


@admin_router.get("/pixelrag", response_model=AdminPixelragResponse)
async def admin_pixelrag() -> AdminPixelragResponse:
    """PixelRAG library availability + Milvus eagle_visual Collection stats."""
    # Library availability.
    lib_result = await _probe_pixelrag()

    # Milvus eagle_visual stats.
    def _visual_stats() -> dict[str, Any]:
        from eagle_rag.index.milvus_visual_store import count_visual

        try:
            total = count_visual()
            return {"visual_vectors": total}
        except Exception as exc:  # noqa: BLE001
            return {"visual_vectors": None, "error": str(exc)}

    stats = await asyncio.to_thread(_visual_stats)
    # render_count / embed_count: 24h metric counts (best-effort; None on failure).
    render_count: int | None = None
    embed_count: int | None = None
    try:
        rc_val = await get_metric_aggregate("pixelrag_render", "count", 24)
        render_count = int(rc_val) if rc_val is not None else None
    except Exception:  # noqa: BLE001
        render_count = None
    try:
        ec_val = await get_metric_aggregate("pixelrag_embed", "count", 24)
        embed_count = int(ec_val) if ec_val is not None else None
    except Exception:  # noqa: BLE001
        embed_count = None
    return AdminPixelragResponse(
        status=_dependency_status(lib_result["status"]),
        detail=lib_result.get("detail", ""),
        visual_vectors=stats.get("visual_vectors"),
        error=stats.get("error"),
        render_count=render_count,
        embed_count=embed_count,
    )


@admin_router.get("/knowhere", response_model=AdminKnowhereResponse)
async def admin_knowhere() -> AdminKnowhereResponse:
    """Knowhere parser service config and probe."""
    cfg = get_settings().knowhere
    probe = await _probe_knowhere()
    # parsed: total document count in the documents table (best-effort; None if
    # the table is missing or the query fails).
    parsed: int | None = None
    try:
        row = await async_fetchrow("SELECT COUNT(*)::int AS cnt FROM documents")
        if row is not None:
            parsed = row["cnt"]
    except Exception:  # noqa: BLE001
        parsed = None
    # partitions: per-KB document count (best-effort; empty if the table is
    # missing).
    kb_doc_counts: list[tuple[str, int]] = []
    try:
        rows = await async_fetch(
            "SELECT kb_name, COUNT(*)::int AS doc_count FROM documents GROUP BY kb_name"
        )
        for r in rows:
            kb_doc_counts.append((r["kb_name"], int(r["doc_count"])))
    except Exception:  # noqa: BLE001
        kb_doc_counts = []
    # chunks (total + per-kb): from Milvus eagle_text (best-effort; None on
    # failure).
    chunks: int | None = None
    per_kb_chunks: dict[str, int | None] = {}
    try:
        from eagle_rag.index.milvus_text_store import count_text

        def _count_sync() -> tuple[int | None, dict[str, int | None]]:
            total: int | None = None
            per_kb: dict[str, int | None] = {}
            try:
                total = count_text()
            except Exception:  # noqa: BLE001
                total = None
            for kb_name, _ in kb_doc_counts:
                try:
                    per_kb[kb_name] = count_text(kb_name=kb_name)
                except Exception:  # noqa: BLE001
                    per_kb[kb_name] = None
            return total, per_kb

        chunks, per_kb_chunks = await asyncio.to_thread(_count_sync)
    except Exception:  # noqa: BLE001
        chunks = None
        per_kb_chunks = {}
    # Assemble partitions.
    partitions: list[KbPartitionOut] = [
        KbPartitionOut(
            kb_name=kb_name,
            document_count=doc_count,
            chunk_count=per_kb_chunks.get(kb_name),
        )
        for kb_name, doc_count in kb_doc_counts
    ]
    return AdminKnowhereResponse(
        base_url=cfg.base_url,
        status=_dependency_status(probe["status"]),
        detail=probe.get("detail", ""),
        parsed=parsed,
        chunks=chunks,
        partitions=partitions,
    )


def _knowhere_action_sync(action: str) -> dict[str, Any]:
    """Run flush / compact on the eagle_text Milvus collection.

    The Knowhere HTTP service (:5005) has no flush/clean API; the Knowhere
    Dashboard shows partition data of the eagle_text Collection, so maintenance
    operations target that Collection. Returns empty details when the Collection
    does not exist.
    """
    from pymilvus import MilvusClient

    cfg = get_settings().milvus
    client = MilvusClient(uri=f"http://{cfg.host}:{cfg.port}")
    coll_name = cfg.text_collection
    details: list[dict[str, Any]] = []
    try:
        if not client.has_collection(coll_name):
            return {"details": details}
        try:
            if action == "flush":
                client.flush(coll_name)
            else:
                try:
                    client.compact(coll_name)
                except AttributeError:
                    from pymilvus import Collection, connections

                    if not connections.has_connection("default"):
                        connections.connect(uri=f"http://{cfg.host}:{cfg.port}")
                    Collection(coll_name).compact()
            details.append({"collection": coll_name, "action": action, "success": True})
        except Exception as exc:  # noqa: BLE001
            details.append(
                {
                    "collection": coll_name,
                    "action": action,
                    "success": False,
                    "detail": f"{type(exc).__name__}: {exc}",
                }
            )
        return {"details": details}
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass


@admin_router.post("/knowhere/flush", response_model=AdminActionResult)
async def admin_knowhere_flush() -> AdminActionResult:
    """Force-flush the eagle_text collection (the text vector store written by Knowhere)."""
    payload = await asyncio.to_thread(_knowhere_action_sync, "flush")
    return _build_action_result("flush", payload)


@admin_router.post("/knowhere/clean", response_model=AdminActionResult)
async def admin_knowhere_clean() -> AdminActionResult:
    """Clean stale indexes: compact the eagle_text collection.

    Merges segments and removes deleted entities.
    """
    payload = await asyncio.to_thread(_knowhere_action_sync, "compact")
    return _build_action_result("compact", payload)


@admin_router.get("/vlm", response_model=AdminVlmResponse)
async def admin_vlm() -> AdminVlmResponse:
    """VLM config (api_key is not leaked)."""
    cfg = get_settings().vlm
    # latency / tokens / error_rate: 24h metric aggregates (best-effort; None on
    # failure).
    latency: float | None = None
    tokens: int | None = None
    error_rate: float | None = None
    try:
        latency = await get_metric_aggregate("vlm_latency_ms", "avg", 24)
    except Exception:  # noqa: BLE001
        latency = None
    try:
        tokens_val = await get_metric_aggregate("vlm_tokens", "sum", 24)
        tokens = int(tokens_val) if tokens_val is not None else None
    except Exception:  # noqa: BLE001
        tokens = None
    try:
        error_rate = await get_metric_aggregate("vlm_error", "avg", 24)
    except Exception:  # noqa: BLE001
        error_rate = None
    # model_router: read override values from system_setting (best-effort;
    # fallback all-True).
    router_overrides: dict[str, Any] = {}
    try:
        router_overrides = (await get_setting("model_router")) or {}
    except Exception:  # noqa: BLE001
        router_overrides = {}
    model_router = [
        ModelRouterOut(
            key="vlm",
            name="Vision LLM (VLM)",
            enabled=router_overrides.get("vlm", True),
        ),
        ModelRouterOut(
            key="text_llm",
            name="Text LLM (LLM)",
            enabled=router_overrides.get("text_llm", True),
        ),
        ModelRouterOut(
            key="embedding",
            name="Embedding encoder (Embedding)",
            enabled=router_overrides.get("embedding", True),
        ),
    ]
    return AdminVlmResponse(
        provider=cfg.provider,
        model=cfg.model,
        api_key_set=bool(cfg.api_key),
        base_url=cfg.base_url,
        latency=latency,
        tokens=tokens,
        error_rate=error_rate,
        model_router=model_router,
    )


@admin_router.patch("/model-router", response_model=list[ModelRouterOut])
async def admin_update_model_router(payload: ModelRouterUpdate) -> list[ModelRouterOut]:
    """Update model router toggles (upsert into the system_setting table)."""
    current: dict[str, Any] = {}
    try:
        current = (await get_setting("model_router")) or {}
    except Exception:  # noqa: BLE001
        current = {}
    if payload.vlm is not None:
        current["vlm"] = payload.vlm
    if payload.text_llm is not None:
        current["text_llm"] = payload.text_llm
    if payload.embedding is not None:
        current["embedding"] = payload.embedding
    await set_setting("model_router", current)
    return [
        ModelRouterOut(key="vlm", name="Vision LLM (VLM)", enabled=current.get("vlm", True)),
        ModelRouterOut(
            key="text_llm", name="Text LLM (LLM)", enabled=current.get("text_llm", True)
        ),
        ModelRouterOut(
            key="embedding",
            name="Embedding encoder (Embedding)",
            enabled=current.get("embedding", True),
        ),
    ]


@admin_router.get("/mcp", response_model=AdminMcpResponse)
async def admin_mcp() -> AdminMcpResponse:
    """MCP registration status and tool list."""
    registered = False
    tools: list[McpToolDefinition] = []
    try:
        from eagle_rag.api.mcp_server import TOOL_DEFINITIONS

        tools = [McpToolDefinition.model_validate(t) for t in TOOL_DEFINITIONS]
        registered = True
    except Exception:  # noqa: BLE001
        registered = False
        tools = []
    # sse_connections: current in-memory subscriber count (reads the module-level
    # variable directly).
    sse_connections = len(_log_subscribers)
    # console_logs: last 50 MCP call logs (best-effort; empty list on failure).
    console_logs: list[McpCallLogOut] = []
    try:
        calls = await list_recent_mcp_calls(limit=50)
        console_logs = [
            McpCallLogOut(
                time=c.get("called_at", ""),
                level="INFO",
                message=(
                    f"{c.get('tool_name', '?')} → {c.get('result_summary', '')} "
                    f"({c.get('latency_ms', 0)}ms)"
                ),
            )
            for c in calls
        ]
    except Exception:  # noqa: BLE001
        console_logs = []
    # Runtime transport metadata from McpSettings + mcp library.
    mcp_cfg = get_settings().mcp
    app_cfg = get_settings().app
    protocol_version: str | None = None
    try:
        from mcp.types import LATEST_PROTOCOL_VERSION

        protocol_version = LATEST_PROTOCOL_VERSION
    except Exception:  # noqa: BLE001
        protocol_version = None
    # In standalone mode the MCP server runs on mcp.port; when mounted under
    # the API app (standalone=false) the endpoint is served on app.port.
    effective_port = mcp_cfg.port if mcp_cfg.standalone else app_cfg.port
    return AdminMcpResponse(
        registered=registered,
        tools=tools,
        sse_connections=sse_connections,
        console_logs=console_logs,
        transport=mcp_cfg.transport,
        protocol_version=protocol_version,
        stateless_http=mcp_cfg.stateless_http,
        json_response=mcp_cfg.json_response,
        endpoint_path=mcp_cfg.streamable_http_path,
        port=effective_port,
    )


def _mask_value(key: str, value: Any) -> Any:
    """Recursively mask sensitive values with "***" when non-empty.

    Matches keys containing key/secret/password (case-insensitive).
    """
    sensitive = ("key", "secret", "password")
    if isinstance(value, dict):
        return {k: _mask_value(k, v) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask_value(key, v) for v in value]
    if isinstance(value, str) and any(s in key.lower() for s in sensitive):
        return "***" if value else ""
    return value


@admin_router.get("/config", response_model=AdminConfigOut)
async def admin_config() -> AdminConfigOut:
    """Return masked settings (fields with key/secret/password are replaced with "***")."""
    settings = get_settings()
    raw = settings.model_dump()
    masked = _mask_value("", raw)
    return AdminConfigOut.model_validate(masked)


@admin_router.get("/probes", response_model=AdminProbesResponse)
async def admin_probes() -> AdminProbesResponse:
    """Like /health but more detailed: returns each probe's raw result (including latency_ms)."""
    deps = await _probe_all()
    uptime_map = _update_uptime(deps)
    # resource_limits: psutil CPU / memory (best-effort; None when psutil is
    # unavailable).
    resource_limits: ResourceLimitsOut | None = None
    try:
        import psutil

        cpu_percent = float(psutil.cpu_percent(interval=0.1))
        cpu_count = psutil.cpu_count() or 0
        mem = psutil.virtual_memory()
        total_mb = float(mem.total) / 1024.0 / 1024.0
        used_mb = float(mem.used) / 1024.0 / 1024.0
        resource_limits = ResourceLimitsOut(
            cpu=ResourceLimitOut(
                used=cpu_percent,
                limit=float(cpu_count),
                unit="cores",
                percent=cpu_percent,
            ),
            memory=ResourceLimitOut(
                used=used_mb,
                limit=total_mb,
                unit="MB",
                percent=float(mem.percent),
            ),
        )
    except ImportError:  # noqa: BLE001
        resource_limits = None
    except Exception:  # noqa: BLE001
        resource_limits = None
    # probe_config: defaults (could be read from settings in the future).
    probe_config = ProbeConfigOut()
    return AdminProbesResponse(
        status=_aggregate_status(deps),
        dependencies={
            name: ProbeDetail(
                status=_dependency_status(v["status"]),
                detail=v.get("detail", ""),
                latency_ms=int(v.get("latency_ms", 0)),
                uptime=uptime_map.get(name, ""),
            )
            for name, v in deps.items()
        },
        resource_limits=resource_limits,
        probe_config=probe_config,
    )


# ---------------------------------------------------------------------------
# /admin/logs: SSE live log stream
# ---------------------------------------------------------------------------

# In-memory subscriber queue list: one asyncio.Queue per SSE client, supports
# multi-client broadcast.
_log_subscribers: list[asyncio.Queue[str]] = []


def _register_subscriber() -> asyncio.Queue[str]:
    q: asyncio.Queue[str] = asyncio.Queue(maxsize=1000)
    _log_subscribers.append(q)
    return q


def _unregister_subscriber(q: asyncio.Queue[str]) -> None:
    try:
        _log_subscribers.remove(q)
    except ValueError:
        pass


async def publish_log(line: str) -> None:
    """Broadcast a log line to all in-memory subscribers (drop on queue full, non-blocking).

    Called by the internal log handler; Phase 6.4 only provides the transport
    channel, the producer is wired up in a later phase.
    """
    for q in list(_log_subscribers):
        try:
            q.put_nowait(line)
        except asyncio.QueueFull:
            pass


def register_log_handler() -> None:
    """Compatibility entry.

    Telemetry is now configured by lifespan calling configure_telemetry directly.
    Kept as an empty function so external callers do not break.
    """
    return None


async def _log_event_generator():
    """SSE event generator.

    Prefers reading log lines from the Redis pub/sub ``logs`` channel; if Redis
    is unavailable, reads from the in-memory ``asyncio.Queue`` and emits a
    heartbeat every 5 seconds to keep the connection alive. Cleans up the
    subscription when the client disconnects.
    """
    q = _register_subscriber()
    redis_client = None
    pubsub = None
    try:
        # Try to establish a Redis pub/sub subscription.
        try:
            import redis.asyncio as aioredis

            # Note: socket_timeout must be None (block indefinitely); otherwise
            # pubsub.listen() is interrupted by the socket read timeout when the
            # channel has no messages, crashing the SSE task group
            # (redis.exceptions.TimeoutError: Timeout reading from redis:6379).
            # Connection establishment is bounded by _PROBE_TIMEOUT.
            redis_client = aioredis.from_url(
                get_settings().celery.broker_url,
                socket_connect_timeout=_PROBE_TIMEOUT,
                socket_timeout=None,
            )
            await asyncio.wait_for(redis_client.ping(), timeout=_PROBE_TIMEOUT)
            pubsub = redis_client.pubsub()
            await pubsub.subscribe("logs")
        except Exception:  # noqa: BLE001
            redis_client = None
            pubsub = None

        if redis_client is not None and pubsub is not None:
            # Redis available: forward channel messages.
            async for msg in pubsub.listen():
                if msg["type"] == "message":
                    data = msg["data"]
                    if isinstance(data, bytes):
                        data = data.decode("utf-8", errors="replace")
                    yield {"event": "log", "data": data}
        else:
            # Redis unavailable: in-memory queue + heartbeat every 5s.
            while True:
                try:
                    line = await asyncio.wait_for(q.get(), timeout=5.0)
                    yield {"event": "log", "data": line}
                except TimeoutError:
                    yield {"event": "heartbeat", "data": f"heartbeat {int(time.time())}"}
    finally:
        _unregister_subscriber(q)
        if pubsub is not None:
            try:
                await pubsub.unsubscribe("logs")
                await pubsub.close()
            except Exception:  # noqa: BLE001
                pass
        if redis_client is not None:
            try:
                await redis_client.close()
            except Exception:  # noqa: BLE001
                pass


@admin_router.get(
    "/logs",
    response_class=EventSourceResponse,
    responses={
        200: {
            "description": "SSE live log stream (event: log | heartbeat)",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        }
    },
)
async def admin_logs():
    """SSE live log stream.

    Subscribes to the ``logs`` channel when Redis is available; otherwise uses
    an in-memory queue + heartbeat.
    """
    return EventSourceResponse(_log_event_generator())
