"""Session/message repository (G9)."""

from __future__ import annotations

from typing import Any

from eagle_rag.sessions import store as session_store

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


async def create_session(
    *,
    session_id: str,
    kb_name: str,
    title: str | None = None,
    scope_filter: dict[str, Any] | None = None,
    plugin_namespace: str | None = None,
) -> dict[str, Any]:
    return await session_store.create_session(
        session_id=session_id,
        kb_name=kb_name,
        title=title,
        scope_filter=scope_filter,
        plugin_namespace=plugin_namespace,
    )


async def get_session(
    session_id: str,
    *,
    plugin_namespace: str | None = None,
) -> dict[str, Any] | None:
    return await session_store.get_session(session_id, plugin_namespace=plugin_namespace)


async def list_sessions(
    *,
    kb_name: str | None = None,
    limit: int = 50,
    offset: int = 0,
    plugin_namespace: str | None = None,
) -> list[dict[str, Any]]:
    return await session_store.list_sessions(
        kb_name=kb_name,
        limit=limit,
        offset=offset,
        plugin_namespace=plugin_namespace,
    )


async def update_session(
    session_id: str,
    *,
    title: str | None = None,
    plugin_namespace: str | None = None,
) -> dict[str, Any] | None:
    return await session_store.update_session(
        session_id,
        title=title,
        plugin_namespace=plugin_namespace,
    )


async def set_session_scope_filter(
    session_id: str,
    scope_filter: dict[str, Any] | None,
    *,
    plugin_namespace: str | None = None,
) -> dict[str, Any] | None:
    return await session_store.set_session_scope_filter(
        session_id,
        scope_filter,
        plugin_namespace=plugin_namespace,
    )


async def delete_session(
    session_id: str,
    *,
    plugin_namespace: str | None = None,
) -> bool:
    return await session_store.delete_session(session_id, plugin_namespace=plugin_namespace)


async def add_message(
    *,
    session_id: str,
    role: str,
    content: str,
    metadata: dict[str, Any] | None = None,
    plugin_namespace: str | None = None,
) -> dict[str, Any]:
    return await session_store.add_message(
        session_id=session_id,
        role=role,
        content=content,
        metadata=metadata,
        plugin_namespace=plugin_namespace,
    )


async def list_messages(
    session_id: str,
    *,
    limit: int = 200,
    plugin_namespace: str | None = None,
) -> list[dict[str, Any]]:
    return await session_store.list_messages(
        session_id,
        limit=limit,
        plugin_namespace=plugin_namespace,
    )


async def get_message(
    message_id: str,
    *,
    plugin_namespace: str | None = None,
) -> dict[str, Any] | None:
    return await session_store.get_message(message_id, plugin_namespace=plugin_namespace)
