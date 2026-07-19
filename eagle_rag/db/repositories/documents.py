"""Documents registry repository (G9)."""

from __future__ import annotations

from typing import Any

from eagle_rag.index import registry as document_registry

__all__ = [
    "register_document",
    "get_document",
    "get_document_sync",
    "list_documents",
    "count_documents",
    "delete_document",
    "update_status",
    "update_chunk_count",
    "update_extra",
]


def register_document(
    document_id: str,
    *,
    name: str,
    source_type: str,
    pipeline: str,
    kb_name: str | None = None,
    plugin_namespace: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    return document_registry.register_document(
        document_id,
        name=name,
        source_type=source_type,
        pipeline=pipeline,
        kb_name=kb_name,
        plugin_namespace=plugin_namespace,
        **kwargs,
    )


def get_document_sync(
    document_id: str,
    *,
    plugin_namespace: str | None = None,
) -> dict[str, Any] | None:
    return document_registry.get_document_sync(document_id, plugin_namespace=plugin_namespace)


async def get_document(
    document_id: str,
    *,
    plugin_namespace: str | None = None,
) -> dict[str, Any] | None:
    return await document_registry.get_document(document_id, plugin_namespace=plugin_namespace)


async def list_documents(
    *,
    plugin_namespace: str | None = None,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    return await document_registry.list_documents(plugin_namespace=plugin_namespace, **kwargs)


async def count_documents(
    *,
    plugin_namespace: str | None = None,
    **kwargs: Any,
) -> int:
    return await document_registry.count_documents(plugin_namespace=plugin_namespace, **kwargs)


async def delete_document(
    document_id: str,
    *,
    plugin_namespace: str | None = None,
) -> bool:
    return await document_registry.delete_document(
        document_id,
        plugin_namespace=plugin_namespace,
    )


def update_status(document_id: str, status: str, **kwargs: Any) -> bool:
    return document_registry.update_status(document_id, status, **kwargs)


def update_chunk_count(document_id: str, chunk_count: int) -> bool:
    return document_registry.update_chunk_count(document_id, chunk_count)


def update_extra(document_id: str, patch: dict[str, Any]) -> bool:
    return document_registry.update_extra(document_id, patch)
