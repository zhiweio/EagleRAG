"""Dedup registry repository (G9)."""

from __future__ import annotations

from typing import Any

from eagle_rag.storage import dedup as dedup_store

__all__ = [
    "compute_sha256",
    "compute_sha256_bytes",
    "check_duplicate",
    "register",
    "check_and_register",
]


def compute_sha256(file_path: str) -> str:
    return dedup_store.compute_sha256(file_path)


def compute_sha256_bytes(data: bytes) -> str:
    return dedup_store.compute_sha256_bytes(data)


def check_duplicate(
    sha256: str,
    kb_name: str | None = None,
    *,
    plugin_namespace: str | None = None,
) -> dict[str, Any] | None:
    return dedup_store.check_duplicate(
        sha256,
        kb_name,
        plugin_namespace=plugin_namespace,
    )


def register(
    sha256: str,
    document_id: str,
    *,
    kb_name: str | None = None,
    plugin_namespace: str | None = None,
    object_key: str | None = None,
    source_name: str | None = None,
) -> None:
    dedup_store.register(
        sha256,
        document_id,
        kb_name=kb_name,
        plugin_namespace=plugin_namespace,
        object_key=object_key,
        source_name=source_name,
    )


def check_and_register(
    sha256: str,
    document_id: str,
    *,
    kb_name: str | None = None,
    plugin_namespace: str | None = None,
    object_key: str | None = None,
    source_name: str | None = None,
) -> dict[str, Any]:
    return dedup_store.check_and_register(
        sha256,
        document_id,
        kb_name=kb_name,
        plugin_namespace=plugin_namespace,
        object_key=object_key,
        source_name=source_name,
    )
