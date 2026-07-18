"""MCP tool call log storage."""

from __future__ import annotations

import json
import threading
import uuid
from typing import Any

from eagle_rag.db import async_fetch, sync_execute
from eagle_rag.telemetry import get_ai_logger, truncate

__all__ = [
    "record_mcp_call",
    "list_recent_mcp_calls",
]

ai_logger = get_ai_logger(__name__)


def _record_mcp_call_sync(
    *,
    tool_name: str,
    arguments: dict,
    result_summary: str,
    caller: str = "",
    latency_ms: int = 0,
    plugin_namespace: str | None = None,
) -> None:
    """Synchronously write one MCP call log row (the actual DB write)."""
    from eagle_rag.db.repositories.base import instance_namespace

    ns = instance_namespace(plugin_namespace)
    log_id = str(uuid.uuid4())
    sync_execute(
        """
        INSERT INTO mcp_call_log
        (id, tool_name, arguments, result_summary, caller, latency_ms, plugin_namespace)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            log_id,
            tool_name,
            json.dumps(arguments, ensure_ascii=False),
            result_summary,
            caller,
            latency_ms,
            ns,
        ),
    )
    try:
        ai_logger.info(
            "mcp_call",
            tool=tool_name,
            arguments=truncate(json.dumps(arguments, ensure_ascii=False), 512),
            result_summary=truncate(result_summary, 256),
            caller=caller,
            latency_ms=latency_ms,
        )
    except Exception:  # noqa: BLE001
        pass


def record_mcp_call(
    *,
    tool_name: str,
    arguments: dict,
    result_summary: str,
    caller: str = "",
    latency_ms: int = 0,
) -> None:
    """Fire-and-forget write of one MCP call log (runs on a daemon thread).

    The actual DB write runs in a ``daemon=True`` thread so it does not block the
    tool return. If the DB is unreachable the exception is swallowed inside the
    thread (best-effort), leaving the main flow unaffected.

    Note:
        A daemon thread is used instead of ``asyncio.to_thread``: MCP tool
        functions are sync and run in a thread pool by FastMCP, so there is no
        running event loop for ``asyncio.to_thread`` to schedule on. Daemon
        threads are reclaimed automatically at process exit. Under heavy load, if
        DB writes become a bottleneck, switch to a bounded
        ``ThreadPoolExecutor`` queue.
    """
    thread = threading.Thread(
        target=_record_mcp_call_sync,
        kwargs={
            "tool_name": tool_name,
            "arguments": arguments,
            "result_summary": result_summary,
            "caller": caller,
            "latency_ms": latency_ms,
        },
        daemon=True,
        name=f"mcp-log-{tool_name}",
    )
    thread.start()


async def list_recent_mcp_calls(
    limit: int = 50,
    *,
    plugin_namespace: str | None = None,
) -> list[dict[str, Any]]:
    """Query the most recent MCP call log rows for this instance namespace."""
    from eagle_rag.db.repositories.base import instance_namespace

    ns = instance_namespace(plugin_namespace)
    rows = await async_fetch(
        """
        SELECT tool_name, arguments, result_summary, caller, latency_ms, called_at
        FROM mcp_call_log
        WHERE plugin_namespace = $1
        ORDER BY called_at DESC
        LIMIT $2
        """,
        ns,
        limit,
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        ca = d.get("called_at")
        if ca is not None and hasattr(ca, "isoformat"):
            d["called_at"] = ca.isoformat()
        out.append(d)
    return out
