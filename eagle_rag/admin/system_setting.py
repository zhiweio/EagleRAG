"""System runtime configuration override storage."""

from __future__ import annotations

import json
from typing import Any

from eagle_rag.db import async_execute, async_fetchrow

__all__ = [
    "get_setting",
    "set_setting",
]


async def get_setting(key: str) -> dict[str, Any] | None:
    """Read one system_setting row.

    Used by ``/admin/vlm`` to read the ``model_router`` override. Returns the
    ``value`` (dict) or ``None``. Uses ``async_fetchrow`` with ``$1``.
    """
    row = await async_fetchrow(
        """
        SELECT value FROM system_setting WHERE key = $1
        """,
        key,
    )
    if row is None:
        return None
    value = row["value"]
    if isinstance(value, str):
        # asyncpg normally parses JSONB into a dict automatically; guard against the string case.
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return None
    return value


async def set_setting(key: str, value: dict[str, Any]) -> None:
    """Upsert one system_setting row.

    Called by PATCH ``/admin/model-router``. Uses ``async_execute`` with
    ``$1/$2`` placeholders and ``ON CONFLICT (key) DO UPDATE SET value = $2,
    updated_at = NOW()``. ``value`` is serialized via ``json.dumps`` and passed
    to asyncpg (JSONB column; asyncpg accepts a JSON string).
    """
    await async_execute(
        """
        INSERT INTO system_setting (key, value, updated_at)
        VALUES ($1, $2, NOW())
        ON CONFLICT (key) DO UPDATE SET value = $2, updated_at = NOW()
        """,
        key,
        json.dumps(value, ensure_ascii=False),
    )
