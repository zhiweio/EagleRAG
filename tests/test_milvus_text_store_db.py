"""Tests for ``get_text_vector_store`` db_name propagation (G17 binding).

Verifies that ``MilvusVectorStore`` is constructed with ``db_name`` matching the
plugin namespace, so a biomed deployment binds to the ``biomed`` Milvus database
instead of the ``default`` one.
"""

from __future__ import annotations

from typing import Any

import pytest

from eagle_rag.index import milvus_text_store


@pytest.fixture(autouse=True)
def _reset_text_store_cache() -> Any:
    """Clear module-level store/index caches between tests."""
    milvus_text_store._text_vector_store = None
    milvus_text_store._text_index = None
    milvus_text_store._text_stores_by_db.clear()
    milvus_text_store._text_indices_by_db.clear()
    yield
    milvus_text_store._text_vector_store = None
    milvus_text_store._text_index = None
    milvus_text_store._text_stores_by_db.clear()
    milvus_text_store._text_indices_by_db.clear()


def _patch_milvus_vector_store(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Patch ``MilvusVectorStore`` to capture construction kwargs."""
    captured: dict[str, Any] = {}

    class _FakeStore:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    # The import path used by get_text_vector_store (try/except fallback).
    import llama_index.vector_stores.milvus as _milvus_pkg

    monkeypatch.setattr(_milvus_pkg, "MilvusVectorStore", _FakeStore, raising=True)
    return captured


def _patch_namespace_passthrough(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bypass instance_namespace validation so non-core namespaces resolve directly.

    ``instance_namespace`` enforces G3 (single-namespace) at runtime; in unit
    tests the default profile is ``core`` and rejects ``biomed``. We only need
    ``_db_name`` -> ``milvus_db_name`` to compute the right db_name, so patch
    ``instance_namespace`` to be an identity function.
    """

    def _identity(ns: str | None) -> str:
        return ns or "core"

    monkeypatch.setattr(
        "eagle_rag.db.repositories.base.instance_namespace", _identity, raising=True
    )


def test_biomed_namespace_binds_biomed_db(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_namespace_passthrough(monkeypatch)
    captured = _patch_milvus_vector_store(monkeypatch)
    milvus_text_store.get_text_vector_store(plugin_namespace="biomed")
    assert captured.get("db_name") == "biomed"


def test_core_namespace_binds_default_db(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _patch_milvus_vector_store(monkeypatch)
    milvus_text_store.get_text_vector_store(plugin_namespace="core")
    assert captured.get("db_name") == "default"


def test_none_namespace_binds_default_db(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _patch_milvus_vector_store(monkeypatch)
    milvus_text_store.get_text_vector_store(plugin_namespace=None)
    assert captured.get("db_name") == "default"
