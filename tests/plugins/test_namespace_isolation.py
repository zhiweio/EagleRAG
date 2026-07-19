"""Namespace isolation unit tests (G9/G10/G19/G30)."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from eagle_rag.api.deps import validate_request_namespace
from eagle_rag.config import get_settings
from eagle_rag.db.namespace import resolve_namespace
from eagle_rag.plugins.ingest_catalog import commit_ingest_catalog


def test_resolve_namespace_defaults_to_instance() -> None:
    settings = get_settings()
    assert resolve_namespace(None) == settings.plugins.default_namespace


def test_resolve_namespace_mismatch_403() -> None:
    settings = get_settings()
    if settings.plugins.allow_namespace_override:
        pytest.skip("allow_namespace_override enabled")
    with pytest.raises(HTTPException) as exc:
        resolve_namespace("other-namespace")
    assert exc.value.status_code == 403


def test_validate_request_namespace_none_ok() -> None:
    validate_request_namespace(None)


def test_ingest_tracker_records_collections() -> None:
    from eagle_rag.plugins.ingest_tracker import (
        clear_ingest_collections,
        record_ingest_collection,
        snapshot_ingest_collections,
    )

    clear_ingest_collections()
    record_ingest_collection("eagle_text")
    record_ingest_collection("eagle_text_biomed")
    assert snapshot_ingest_collections() == ["eagle_text", "eagle_text_biomed"]


def test_commit_ingest_catalog_noop_on_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"n": 0}

    def _merge_doc(*_a: object, **_k: object) -> None:
        called["n"] += 1

    monkeypatch.setattr(
        "eagle_rag.plugins.ingest_catalog.merge_document_collections",
        _merge_doc,
    )
    commit_ingest_catalog("doc-1", "default", [])
    assert called["n"] == 0
