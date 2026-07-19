"""Collection store registry (wired in M2 with MilvusClientPool)."""

from __future__ import annotations

from typing import Any

__all__ = ["CollectionStoreRegistry"]


class CollectionStoreRegistry:
    """Maps (db_name, collection) to vector store or retriever handles."""

    def __init__(self) -> None:
        self._stores: dict[tuple[str, str], Any] = {}

    def register(self, db_name: str, collection: str, store: Any) -> None:
        self._stores[(db_name, collection)] = store

    def get(self, db_name: str, collection: str) -> Any:
        key = (db_name, collection)
        if key not in self._stores:
            raise KeyError(f"no store for db={db_name} collection={collection}")
        return self._stores[key]

    def has(self, db_name: str, collection: str) -> bool:
        return (db_name, collection) in self._stores

    def keys(self) -> list[tuple[str, str]]:
        return list(self._stores.keys())
