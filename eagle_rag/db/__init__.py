"""Eagle-RAG database access layer.

Provides two PostgreSQL access modes:
- ``asyncpg`` async connection pool (for FastAPI async routes, e.g. sessions/images queries).
- ``psycopg2`` sync connection (for Celery tasks, e.g. dedup/state audit writes).

Schema is managed by Alembic + SQLModel; see ``eagle_rag.db.models`` and ``alembic/versions/``.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import asyncpg


__all__ = [
    "get_async_pool",
    "close_async_pool",
    "acquire_async",
    "async_execute",
    "async_fetchrow",
    "async_fetch",
    "get_sync_conn",
    "sync_execute",
    "sync_fetchone",
    "sync_fetchall",
]

# ---------------------------------------------------------------------------
# Async pool (asyncpg)
# ---------------------------------------------------------------------------

_async_pool: asyncpg.Pool | None = None


async def get_async_pool() -> asyncpg.Pool:
    """Return the global asyncpg connection pool (lazy singleton)."""
    global _async_pool  # noqa: PLW0603
    if _async_pool is None:
        import asyncpg

        from eagle_rag.config import get_settings

        dsn = get_settings().postgres.dsn
        _async_pool = await asyncpg.create_pool(dsn=dsn, min_size=2, max_size=10)
    return _async_pool


async def close_async_pool() -> None:
    """Close and clear the global async pool (call on application shutdown)."""
    global _async_pool  # noqa: PLW0603
    if _async_pool is not None:
        await _async_pool.close()
        _async_pool = None


@contextlib.asynccontextmanager
async def acquire_async():
    """Context manager acquiring an async connection."""
    pool = await get_async_pool()
    async with pool.acquire() as conn:
        yield conn


async def async_execute(sql: str, *args: Any) -> str:
    """Execute a single statement and return its status string."""
    async with acquire_async() as conn:
        return await conn.execute(sql, *args)


async def async_fetchrow(sql: str, *args: Any) -> asyncpg.Record | None:
    """Fetch a single row."""
    async with acquire_async() as conn:
        return await conn.fetchrow(sql, *args)


async def async_fetch(sql: str, *args: Any) -> list[asyncpg.Record]:
    """Fetch multiple rows."""
    async with acquire_async() as conn:
        return await conn.fetch(sql, *args)


# ---------------------------------------------------------------------------
# Sync connection (psycopg2, for Celery tasks)
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def get_sync_conn():
    """Context manager acquiring a psycopg2 sync connection.

    Celery tasks run in a separate process; each task call acquires a fresh
    connection. On exit the connection is committed/rolled back and closed.
    """
    import psycopg2

    from eagle_rag.config import get_settings

    dsn = get_settings().postgres.dsn
    conn = psycopg2.connect(dsn)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def sync_execute(sql: str, params: tuple[Any, ...] | None = None) -> int:
    """Execute a single statement and return the affected row count."""
    with get_sync_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.rowcount


def sync_fetchone(sql: str, params: tuple[Any, ...] | None = None) -> tuple[Any, ...] | None:
    """Fetch a single row, returning a tuple or None."""
    with get_sync_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.fetchone()


def sync_fetchall(sql: str, params: tuple[Any, ...] | None = None) -> list[tuple[Any, ...]]:
    """Fetch multiple rows, returning a list of tuples."""
    with get_sync_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.fetchall()
