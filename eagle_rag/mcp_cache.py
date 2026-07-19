"""Redis cache for MCP tool invocation results.

Caches the results of ``retrieve_text`` / ``retrieve_visual`` to avoid redundant
vector search and rerank work. ``query`` / ``ingest`` are not cached (answer
generation is stateful; ingest writes are not idempotent).

Design notes:

- **Synchronous API**: MCP tool functions (``mcp_server.py``) have sync signatures
  and FastMCP runs them in a thread pool, so we use ``redis.Redis`` (sync) rather
  than ``redis.asyncio``. The ``ConnectionPool`` is thread-safe and shared across
  workers.
- **Connection reuse**: ``redis_url`` defaults to ``settings.mcp.redis_url`` and
  falls back to ``settings.celery.broker_url`` (reusing the Celery broker avoids a
  separate Redis instance). When both are empty, ``_get_redis()`` returns ``None``
  and the cache degrades silently to all-miss.
- **Silent degradation**: when Redis is unreachable, ``get_cached`` returns
  ``None`` (treated as a miss) and ``set_cached`` is a no-op; the tool's main flow
  is unaffected.
- **Cache key**: ``mcp:{tool}:{sha256(json(query, scope, top_k, kb_name))}``;
  ``scope`` is sorted before hashing for determinism.
- **TTL**: defaults to ``settings.mcp.cache_ttl`` (300s), overridable per call.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from eagle_rag.config import get_settings
from eagle_rag.telemetry import get_logger

logger = get_logger(__name__)

__all__ = [
    "get_cached",
    "set_cached",
    "cache_key",
    "reset_redis_pool",
]

# Module-level connection pool (lazy init; thread-safety provided by the redis-py ConnectionPool).
_redis_pool: Any = None
_redis_pool_initialized: bool = False


def reset_redis_pool() -> None:
    """Reset the connection pool (test-only)."""
    global _redis_pool, _redis_pool_initialized
    _redis_pool = None
    _redis_pool_initialized = False


def _get_redis() -> Any:
    """Return the Redis client (lazily initializing the connection pool).

    Returns:
        A ``redis.Redis`` instance, or ``None`` when no redis_url is configured.
    """
    global _redis_pool, _redis_pool_initialized
    if _redis_pool_initialized:
        return _redis_pool  # May be None once we have confirmed there is no Redis config.

    settings = get_settings()
    url = settings.mcp.redis_url or settings.celery.broker_url
    if not url:
        _redis_pool_initialized = True
        _redis_pool = None
        return None

    try:
        import redis

        _redis_pool = redis.ConnectionPool.from_url(url, decode_responses=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis pool init failed; cache degraded to all-miss: %s", exc)
        _redis_pool = None
    _redis_pool_initialized = True
    return _redis_pool


def cache_key(
    tool: str,
    query: str,
    scope: list[str] | None = None,
    top_k: int | None = None,
    kb_name: str | None = None,
    *,
    image_token: str = "",
    plugin_namespace: str | None = None,
) -> str:
    """Compute the cache key.

    Args:
        tool: Tool name (``retrieve_text`` / ``retrieve_visual``).
        query: Retrieval query string.
        scope: List of document_ids (sorted before hashing for determinism).
        top_k: Number of results to return.
        kb_name: Knowledge-base identifier.
        image_token: Optional hash token when retrieval uses an inline image query.

    Returns:
        Cache key in the form ``mcp:{tool}:{sha256_hex}``.
    """
    from eagle_rag.db.repositories.base import instance_namespace

    scope_sorted = sorted(scope) if scope else []
    raw = json.dumps(
        {
            "tool": tool,
            "query": query,
            "scope": scope_sorted,
            "top_k": top_k,
            "kb_name": kb_name or "",
            "image_token": image_token,
            "plugin_namespace": instance_namespace(plugin_namespace),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"mcp:{tool}:{digest}"


def get_cached(key: str) -> Any:
    """Read a cached value from Redis.

    Args:
        key: Cache key returned by ``cache_key()``.

    Returns:
        The deserialized cached value (typically ``list[dict]``), or ``None`` on
        miss / Redis unreachable / deserialization failure.
    """
    pool = _get_redis()
    if pool is None:
        return None
    try:
        import redis

        client = redis.Redis(connection_pool=pool)
        data = client.get(key)
        if data is None:
            return None
        return json.loads(data)
    except (redis.RedisError, OSError, json.JSONDecodeError) as exc:
        logger.warning("Redis cache get failed (key=%s); degraded to miss: %s", key, exc)
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis cache get unknown error (key=%s): %s", key, exc)
        return None


def set_cached(key: str, value: Any, ttl: int | None = None) -> None:
    """Write a cached value to Redis.

    Args:
        key: Cache key.
        value: JSON-serializable value.
        ttl: TTL in seconds. ``None`` uses ``settings.mcp.cache_ttl``.
    """
    pool = _get_redis()
    if pool is None:
        return
    if ttl is None:
        ttl = get_settings().mcp.cache_ttl
    try:
        import redis

        client = redis.Redis(connection_pool=pool)
        client.setex(key, ttl, json.dumps(value, ensure_ascii=False))
    except (redis.RedisError, OSError, TypeError) as exc:
        logger.warning("Redis cache set failed (key=%s); skipping write-back: %s", key, exc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis cache set unknown error (key=%s): %s", key, exc)
