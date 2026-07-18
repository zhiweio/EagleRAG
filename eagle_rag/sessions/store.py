"""Session and message persistence (PostgreSQL, fully async).

Consumed by FastAPI routes via the ``asyncpg`` connection pool with ``$1``
style placeholders. JSONB fields (``sources`` / ``steps`` / ``attachments``)
are written as ``json.dumps`` text with an explicit ``::jsonb`` cast and
read back tolerating either ``str`` or already-parsed ``list``/``dict``.

Sessions and messages are scoped per ``kb_name`` for multi-tenant isolation;
callers may pass ``kb_name`` explicitly, otherwise the global
``settings.kb_name`` is used.

Table schema is managed by Alembic + SQLModel; see ``eagle_rag.db.models``.
"""

from __future__ import annotations

import json
from typing import Any

from eagle_rag.config import get_settings
from eagle_rag.db import acquire_async, async_execute, async_fetch, async_fetchrow
from eagle_rag.db.repositories.base import instance_namespace

__all__ = [
    "create_session",
    "get_session",
    "list_sessions",
    "update_session",
    "set_session_scope_filter",
    "delete_session",
    "add_message",
    "list_messages",
    "get_message",
]


def _resolve_kb(kb_name: str | None) -> str:
    """Fall back to global ``settings.kb_name`` when ``kb_name`` is None."""
    return kb_name if kb_name is not None else get_settings().kb_name


# ---------------------------------------------------------------------------
# JSONB helpers
# ---------------------------------------------------------------------------


def _dumps(value: list | dict | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def _loads(value: Any) -> Any:
    """asyncpg returns JSONB as ``str`` by default; pass through already-parsed values."""
    if value is None or isinstance(value, (list, dict)):
        return value
    if isinstance(value, str):
        return json.loads(value)
    return value


# ---------------------------------------------------------------------------
# sessions
# ---------------------------------------------------------------------------


_SESSION_COLUMNS = (
    "session_id, title, created_at, updated_at, kb_name, plugin_namespace, scope_filter"
)


def _session_from_row(row: Any) -> dict[str, Any]:
    return {
        "session_id": row["session_id"],
        "title": row["title"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "kb_name": row["kb_name"],
        "plugin_namespace": row.get("plugin_namespace", "core"),
        "scope_filter": _loads(row["scope_filter"]),
    }


async def create_session(
    session_id: str,
    title: str | None = None,
    *,
    kb_name: str | None = None,
    scope_filter: dict | None = None,
    plugin_namespace: str | None = None,
) -> dict[str, Any]:
    """Insert a new session and return it as a dict."""
    kb = _resolve_kb(kb_name)
    ns = instance_namespace(plugin_namespace)
    row = await async_fetchrow(
        "INSERT INTO sessions (session_id, title, kb_name, plugin_namespace, scope_filter) "
        "VALUES ($1, $2, $3, $4, $5::jsonb) "
        f"RETURNING {_SESSION_COLUMNS}",
        session_id,
        title,
        kb,
        ns,
        _dumps(scope_filter),
    )
    return _session_from_row(row)


async def get_session(
    session_id: str,
    *,
    plugin_namespace: str | None = None,
) -> dict[str, Any] | None:
    """Look up a session by ``session_id``; return ``None`` if not found."""
    ns = instance_namespace(plugin_namespace)
    row = await async_fetchrow(
        f"SELECT {_SESSION_COLUMNS} FROM sessions WHERE session_id = $1 AND plugin_namespace = $2",
        session_id,
        ns,
    )
    return _session_from_row(row) if row is not None else None


async def list_sessions(
    *,
    kb_name: str | None = None,
    plugin_namespace: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List sessions paginated, newest ``updated_at`` first; filter by namespace."""
    ns = instance_namespace(plugin_namespace)
    if kb_name is None:
        rows = await async_fetch(
            f"SELECT {_SESSION_COLUMNS} FROM sessions "
            "WHERE plugin_namespace = $1 ORDER BY updated_at DESC LIMIT $2 OFFSET $3",
            ns,
            limit,
            offset,
        )
    else:
        rows = await async_fetch(
            f"SELECT {_SESSION_COLUMNS} "
            "FROM sessions WHERE plugin_namespace = $1 AND kb_name = $2 "
            "ORDER BY updated_at DESC LIMIT $3 OFFSET $4",
            ns,
            kb_name,
            limit,
            offset,
        )
    return [_session_from_row(r) for r in rows]


async def update_session(
    session_id: str,
    *,
    title: str | None = None,
    plugin_namespace: str | None = None,
) -> dict[str, Any] | None:
    """Update the session title and refresh ``updated_at``; return the updated session dict."""
    ns = instance_namespace(plugin_namespace)
    row = await async_fetchrow(
        "UPDATE sessions SET title = COALESCE($1, title), updated_at = NOW() "
        "WHERE session_id = $2 AND plugin_namespace = $3 "
        f"RETURNING {_SESSION_COLUMNS}",
        title,
        session_id,
        ns,
    )
    return _session_from_row(row) if row is not None else None


async def set_session_scope_filter(
    session_id: str,
    scope_filter: dict | None,
    *,
    plugin_namespace: str | None = None,
) -> None:
    """Persist the last-used scope filter for a session (for cross-device restore)."""
    ns = instance_namespace(plugin_namespace)
    await async_execute(
        "UPDATE sessions SET scope_filter = $1::jsonb "
        "WHERE session_id = $2 AND plugin_namespace = $3",
        _dumps(scope_filter),
        session_id,
        ns,
    )


async def delete_session(
    session_id: str,
    *,
    plugin_namespace: str | None = None,
) -> bool:
    """Delete a session (cascades to its messages); return whether a row was actually deleted."""
    ns = instance_namespace(plugin_namespace)
    result = await async_execute(
        "DELETE FROM sessions WHERE session_id = $1 AND plugin_namespace = $2",
        session_id,
        ns,
    )
    # asyncpg execute returns a status string like 'DELETE 1' / 'DELETE 0'.
    if not result:
        return False
    return result.split()[-1] != "0"


# ---------------------------------------------------------------------------
# messages
# ---------------------------------------------------------------------------


def _message_from_row(row: Any) -> dict[str, Any]:
    return {
        "message_id": row["message_id"],
        "session_id": row["session_id"],
        "role": row["role"],
        "content": row["content"],
        "sources": _loads(row["sources"]),
        "steps": _loads(row["steps"]),
        "attachments": _loads(row["attachments"]),
        "created_at": row["created_at"],
        "kb_name": row["kb_name"],
    }


_MESSAGE_COLUMNS = (
    "message_id, session_id, role, content, sources, steps, attachments, created_at, kb_name"
)


async def add_message(
    session_id: str,
    *,
    message_id: str,
    role: str,
    content: str,
    sources: list | None = None,
    steps: list | None = None,
    attachments: list | None = None,
    kb_name: str | None = None,
    plugin_namespace: str | None = None,
) -> dict[str, Any]:
    """Insert a message and refresh the parent session's ``updated_at``; return the message dict.

    Both writes run on the same connection/transaction for atomicity.
    """
    kb = _resolve_kb(kb_name)
    ns = instance_namespace(plugin_namespace)
    async with acquire_async() as conn:
        row = await conn.fetchrow(
            "INSERT INTO messages "
            "(message_id, session_id, role, content, sources, steps, attachments, kb_name, "
            "plugin_namespace) "
            "VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7::jsonb, $8, $9) "
            f"RETURNING {_MESSAGE_COLUMNS}",
            message_id,
            session_id,
            role,
            content,
            _dumps(sources),
            _dumps(steps),
            _dumps(attachments),
            kb,
            ns,
        )
        await conn.execute(
            "UPDATE sessions SET updated_at = NOW() "
            "WHERE session_id = $1 AND plugin_namespace = $2",
            session_id,
            ns,
        )
    return _message_from_row(row)


async def list_messages(
    session_id: str,
    *,
    limit: int = 100,
    offset: int = 0,
    plugin_namespace: str | None = None,
) -> list[dict[str, Any]]:
    """List messages of a session, paginated, oldest ``created_at`` first."""
    ns = instance_namespace(plugin_namespace)
    rows = await async_fetch(
        f"SELECT {_MESSAGE_COLUMNS} FROM messages "
        "WHERE session_id = $1 AND plugin_namespace = $2 "
        f"ORDER BY created_at ASC LIMIT $3 OFFSET $4",
        session_id,
        ns,
        limit,
        offset,
    )
    return [_message_from_row(r) for r in rows]


async def get_message(
    message_id: str,
    *,
    plugin_namespace: str | None = None,
) -> dict[str, Any] | None:
    """Look up a message by ``message_id``; return ``None`` if not found."""
    ns = instance_namespace(plugin_namespace)
    row = await async_fetchrow(
        f"SELECT {_MESSAGE_COLUMNS} FROM messages WHERE message_id = $1 AND plugin_namespace = $2",
        message_id,
        ns,
    )
    return _message_from_row(row) if row is not None else None
