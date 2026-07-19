"""Image metadata repository (G9)."""

from __future__ import annotations

from typing import Any

from eagle_rag.images import store as image_store

__all__ = [
    "ensure_image_dir",
    "store_tile",
    "get_image_meta",
    "get_image_bytes",
    "list_images_by_document",
    "get_image_url",
]


def ensure_image_dir():
    return image_store.ensure_image_dir()


def store_tile(
    image_id: str,
    document_id: str,
    *,
    data: bytes,
    kb_name: str | None = None,
    page: int | None = None,
    position: str | None = None,
    width: int | None = None,
    height: int | None = None,
    object_key: str | None = None,
    plugin_namespace: str | None = None,
) -> dict[str, Any]:
    return image_store.store_tile(
        image_id,
        document_id,
        data=data,
        kb_name=kb_name,
        page=page,
        position=position,
        width=width,
        height=height,
        object_key=object_key,
        plugin_namespace=plugin_namespace,
    )


async def get_image_meta(
    image_id: str,
    *,
    plugin_namespace: str | None = None,
) -> dict[str, Any] | None:
    return await image_store.get_image_meta(image_id, plugin_namespace=plugin_namespace)


def get_image_bytes(
    image_id: str,
    *,
    plugin_namespace: str | None = None,
) -> bytes:
    return image_store.get_image_bytes(image_id, plugin_namespace=plugin_namespace)


async def list_images_by_document(
    document_id: str,
    *,
    page: int | None = None,
    plugin_namespace: str | None = None,
) -> list[dict[str, Any]]:
    return await image_store.list_images_by_document(
        document_id,
        page=page,
        plugin_namespace=plugin_namespace,
    )


async def get_image_url(
    image_id: str,
    *,
    plugin_namespace: str | None = None,
) -> str | None:
    return await image_store.get_image_url(image_id, plugin_namespace=plugin_namespace)
