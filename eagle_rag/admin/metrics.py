"""Queue metric sampling tasks and aggregate queries."""

from __future__ import annotations

import json
import uuid
from typing import Any

from eagle_rag.db import async_fetch, async_fetchrow, sync_execute
from eagle_rag.tasks.celery_app import app as celery_app
from eagle_rag.telemetry import get_logger

logger = get_logger(__name__)

__all__ = [
    "sample_queue_metrics",
    "get_queue_backlog_series",
    "get_metric_aggregate",
]

# Celery pipeline queue names under monitoring (matches ``celery_app.task_queues``).
_QUEUE_NAMES = ("router_queue", "knowhere_queue", "pixelrag_queue")


@celery_app.task(name="eagle_rag.admin.metrics.sample_queue_metrics")
def sample_queue_metrics() -> None:
    """Sample queue lengths into the ``metric_sample`` table on a Celery schedule.

    Reads each queue length via Redis ``LLEN`` for ``router_queue`` /
    ``knowhere_queue`` / ``pixelrag_queue`` and writes one row per queue
    (``metric_name="queue_size"``, ``labels={"queue": qname}``, ``value=size``)
    using ``sync_execute`` (psycopg2). When Redis is unavailable the task is
    skipped via ``try/except`` + ``logging.warning``.

    ``id`` is a uuid4(); ``sampled_at`` defaults to DB ``NOW()``.
    """
    sizes: dict[str, int] = {}
    try:
        import redis

        from eagle_rag.config import get_settings

        client = redis.Redis.from_url(get_settings().celery.broker_url)
        try:
            for qname in _QUEUE_NAMES:
                sizes[qname] = int(client.llen(qname))
        finally:
            try:
                client.close()
            except Exception:  # noqa: BLE001
                pass
    except Exception as exc:  # noqa: BLE001
        logger.warning("queue length sampling skipped: Redis unavailable: %s", exc)
        return

    for qname, size in sizes.items():
        sample_id = str(uuid.uuid4())
        try:
            sync_execute(
                """
                INSERT INTO metric_sample (id, metric_name, labels, value)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    sample_id,
                    "queue_size",
                    json.dumps({"queue": qname}, ensure_ascii=False),
                    float(size),
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("metric_sample write failed (queue=%s): %s", qname, exc)


async def get_queue_backlog_series(limit: int = 20) -> list[dict[str, Any]]:
    """Query the most recent ``queue_size`` samples and reshape them into a time series.

    Returns ``list[{"sampled_at": iso_str, "knowhere": float, "pixelrag": float,
    "router": float}]`` sorted by ``sampled_at`` ASC.

    Implementation: ``SELECT ... WHERE metric_name='queue_size' ORDER BY
    sampled_at DESC LIMIT limit*3`` then group in Python by ``sampled_at``
    (merging rows that share a timestamp) and keep the most recent ``limit``
    timestamps. Returns an empty list when no data exists.
    """
    rows = await async_fetch(
        """
        SELECT labels, value, sampled_at
        FROM metric_sample
        WHERE metric_name = $1
        ORDER BY sampled_at DESC
        LIMIT $2
        """,
        "queue_size",
        limit * 3,
    )
    if not rows:
        return []

    # Group by sampled_at (DESC order), merging rows that share a timestamp into one row.
    grouped: dict[Any, dict[str, Any]] = {}
    order: list[Any] = []
    for r in rows:
        d = dict(r)
        sa = d["sampled_at"]
        labels = d.get("labels") or {}
        if isinstance(labels, str):
            try:
                labels = json.loads(labels)
            except (ValueError, TypeError):
                labels = {}
        qname = labels.get("queue") if isinstance(labels, dict) else None
        if sa not in grouped:
            grouped[sa] = {"sampled_at": sa}
            order.append(sa)
        if qname:
            grouped[sa][qname] = float(d.get("value") or 0.0)

    # ``order`` is DESC (newest first); take the first ``limit`` entries then reverse to ASC.
    latest = [grouped[sa] for sa in order[:limit]]
    latest.reverse()

    out: list[dict[str, Any]] = []
    for item in latest:
        sa = item["sampled_at"]
        out.append(
            {
                "sampled_at": sa.isoformat() if hasattr(sa, "isoformat") else str(sa),
                "knowhere": item.get("knowhere_queue", 0.0),
                "pixelrag": item.get("pixelrag_queue", 0.0),
                "router": item.get("router_queue", 0.0),
            }
        )
    return out


async def get_metric_aggregate(
    metric_name: str,
    agg: str = "avg",  # "avg" | "sum" | "count"
    window_hours: int = 24,
) -> float | None:
    """Aggregate a metric over a time window.

    Used by ``/admin/vlm`` to fetch latency / tokens / error_rate. SQL:
    ``SELECT {agg}(value) FROM metric_sample WHERE metric_name=$1 AND
    sampled_at >= NOW() - INTERVAL '$2 hours'``.

    ``INTERVAL`` cannot use a parameter placeholder, so the value is concatenated
    into the SQL string (``window_hours`` is an int, so this is injection-safe).
    Returns ``None`` when there is no data.
    """
    if agg not in ("avg", "sum", "count"):
        agg = "avg"
    # Force int cast on window_hours to prevent SQL injection.
    hours = int(window_hours)
    row = await async_fetchrow(
        f"""
        SELECT {agg}(value) AS agg_val
        FROM metric_sample
        WHERE metric_name = $1 AND sampled_at >= NOW() - INTERVAL '{hours} hours'
        """,
        metric_name,
    )
    if row is None:
        return None
    val = row["agg_val"]
    if val is None:
        return None
    return float(val)
