"""Knowledge-base registry repository (G9)."""

from __future__ import annotations

from typing import Any

from eagle_rag.kb import registry as kb_registry

__all__ = [
    "create_kb",
    "get_kb",
    "get_kb_sync",
    "list_kbs",
    "update_kb",
    "delete_kb",
    "kb_exists",
    "kb_exists_sync",
    "get_pdf_ratio_sync",
]


async def create_kb(
    *,
    kb_name: str,
    display_name: str,
    description: str = "",
    theme: str = "blue",
    icon: str = "database",
    pdf_text_page_ratio: float = 0.2,
    plugin_namespace: str | None = None,
) -> dict[str, Any]:
    return await kb_registry.create_kb(
        kb_name=kb_name,
        display_name=display_name,
        description=description,
        theme=theme,
        icon=icon,
        pdf_text_page_ratio=pdf_text_page_ratio,
        plugin_namespace=plugin_namespace,
    )


async def get_kb(
    kb_name: str,
    *,
    plugin_namespace: str | None = None,
) -> dict[str, Any] | None:
    return await kb_registry.get_kb(kb_name, plugin_namespace=plugin_namespace)


def get_kb_sync(
    kb_name: str,
    *,
    plugin_namespace: str | None = None,
) -> dict[str, Any] | None:
    return kb_registry.get_kb_sync(kb_name, plugin_namespace=plugin_namespace)


async def list_kbs(
    *,
    query: str | None = None,
    sort: str = "recent",
    limit: int = 50,
    offset: int = 0,
    plugin_namespace: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    return await kb_registry.list_kbs(
        query=query,
        sort=sort,
        limit=limit,
        offset=offset,
        plugin_namespace=plugin_namespace,
    )


async def update_kb(
    kb_name: str,
    *,
    display_name: str | None = None,
    description: str | None = None,
    theme: str | None = None,
    icon: str | None = None,
    pdf_text_page_ratio: float | None = None,
    plugin_namespace: str | None = None,
) -> dict[str, Any] | None:
    return await kb_registry.update_kb(
        kb_name,
        display_name=display_name,
        description=description,
        theme=theme,
        icon=icon,
        pdf_text_page_ratio=pdf_text_page_ratio,
        plugin_namespace=plugin_namespace,
    )


async def delete_kb(
    kb_name: str,
    *,
    plugin_namespace: str | None = None,
) -> bool:
    return await kb_registry.delete_kb(kb_name, plugin_namespace=plugin_namespace)


async def kb_exists(
    kb_name: str,
    *,
    plugin_namespace: str | None = None,
) -> bool:
    return await kb_registry.kb_exists(kb_name, plugin_namespace=plugin_namespace)


def kb_exists_sync(
    kb_name: str,
    *,
    plugin_namespace: str | None = None,
) -> bool:
    return kb_registry.kb_exists_sync(kb_name, plugin_namespace=plugin_namespace)


def get_pdf_ratio_sync(
    kb_name: str | None,
    *,
    plugin_namespace: str | None = None,
) -> float | None:
    if not kb_name:
        return None
    row = get_kb_sync(kb_name, plugin_namespace=plugin_namespace)
    if row is None:
        return None
    return float(row.get("pdf_text_page_ratio", 0.2))
