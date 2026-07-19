"""MCP tool registry: namespaced registration and REST discovery metadata."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

__all__ = [
    "FORBIDDEN_MCP_TOOL_FRAGMENTS",
    "TOOL_DEFINITIONS",
    "_mcp_tool_name",
    "assert_rag_only_tool_name",
    "register_mcp_tool",
]

F = TypeVar("F", bound=Callable[..., Any])

TOOL_DEFINITIONS: list[dict[str, Any]] = []
_registered_names: set[str] = set()

# EagleRAG is a RAG data layer — MCP tools must retrieve/assemble context, never
# execute side effects (SQL, email, orders, DB writes).
FORBIDDEN_MCP_TOOL_FRAGMENTS: tuple[str, ...] = (
    "execute_sql",
    "run_sql",
    "text2sql_exec",
    "send_email",
    "place_order",
    "mutate_",
    "write_db",
    "delete_rows",
)


def _mcp_tool_name(namespace: str, name: str) -> str:
    """Build a namespaced MCP tool name (G2: underscore separator)."""
    ns = namespace.replace("-", "_")
    return f"{ns}_{name}"


def assert_rag_only_tool_name(tool_name: str) -> None:
    """Raise if ``tool_name`` looks like an execution / side-effect tool."""
    lowered = tool_name.lower()
    for fragment in FORBIDDEN_MCP_TOOL_FRAGMENTS:
        if fragment in lowered:
            raise ValueError(
                f"MCP tool {tool_name!r} is not RAG-only (forbidden fragment {fragment!r})"
            )


def register_mcp_tool(
    *,
    namespace: str,
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str] | None = None,
) -> Callable[[F], F]:
    """Register an MCP tool on the shared FastMCP instance and mirror metadata."""

    tool_name = _mcp_tool_name(namespace, name)
    assert_rag_only_tool_name(tool_name)
    parameters = {
        "type": "object",
        "properties": properties,
        "required": required or [],
    }

    def decorator(fn: F) -> F:
        if tool_name in _registered_names:
            msg = f"MCP tool already registered: {tool_name}"
            raise ValueError(msg)
        from eagle_rag.api.mcp_server import mcp

        mcp.tool(name=tool_name, description=description)(fn)
        TOOL_DEFINITIONS.append(
            {
                "name": tool_name,
                "description": description,
                "parameters": parameters,
            }
        )
        _registered_names.add(tool_name)
        return fn

    return decorator
