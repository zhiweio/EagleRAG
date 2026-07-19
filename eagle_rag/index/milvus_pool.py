"""Pooled Milvus clients bound per database (G17/G24)."""

from __future__ import annotations

import threading
from functools import lru_cache

from pymilvus import MilvusClient

from eagle_rag.config import get_settings
from eagle_rag.plugins.milvus_ns import milvus_db_name
from eagle_rag.telemetry import get_logger

__all__ = ["MilvusClientPool", "get_milvus_pool"]

logger = get_logger(__name__)


class MilvusClientPool:
    """Process-wide MilvusClient cache keyed by ``db_name``.

    Clients are constructed with ``db_name=`` at creation time. **Never** call
    ``close()`` on pooled clients.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._clients: dict[str, MilvusClient] = {}
        self._admin: MilvusClient | None = None

    def _uri(self) -> str:
        cfg = get_settings().milvus
        return f"http://{cfg.host}:{cfg.port}"

    def admin_client(self) -> MilvusClient:
        """Client on the default DB for database administration only."""
        if self._admin is None:
            with self._lock:
                if self._admin is None:
                    self._admin = MilvusClient(uri=self._uri(), db_name="default")
        return self._admin

    def ensure_database(self, db_name: str) -> None:
        """Create Milvus database when ``auto_create_db`` is enabled."""
        if db_name == "default":
            return
        settings = get_settings()
        if not settings.milvus.auto_create_db:
            return
        admin = self.admin_client()
        raw = admin.list_databases()
        existing: set[str] = set()
        for item in raw or []:
            if isinstance(item, str):
                existing.add(item)
            elif isinstance(item, dict):
                name = item.get("name") or item.get("db_name")
                if name:
                    existing.add(str(name))
            else:
                existing.add(str(item))
        if db_name not in existing:
            admin.create_database(db_name=db_name)
            logger.info("created milvus database", extra={"db_name": db_name})

    def get(
        self,
        db_name: str | None = None,
        *,
        plugin_namespace: str | None = None,
    ) -> MilvusClient:
        """Return a pooled client for ``db_name`` or mapped ``plugin_namespace``."""
        if db_name is None:
            db_name = milvus_db_name(plugin_namespace)
        self.ensure_database(db_name)
        client = self._clients.get(db_name)
        if client is None:
            with self._lock:
                client = self._clients.get(db_name)
                if client is None:
                    alias = f"eagle-{db_name}"
                    client = MilvusClient(uri=self._uri(), db_name=db_name, alias=alias)
                    self._clients[db_name] = client
        return client

    def get_for_namespace(self, plugin_namespace: str | None) -> MilvusClient:
        return self.get(plugin_namespace=plugin_namespace)


@lru_cache(maxsize=1)
def get_milvus_pool() -> MilvusClientPool:
    return MilvusClientPool()
