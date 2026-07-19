"""Namespace propagation unit tests (A1-A4 wiring closures).

Verifies that ``plugin_namespace`` threads through the core retrieval path
(retriever constructors, orchestrator core-text/visual dispatch, visual store
read functions) so a non-core instance binds to its own Milvus Database (G17).
These are unit-level: no Milvus/PG connection required.
"""

from __future__ import annotations

import pytest

from eagle_rag.retrievers.knowhere_graph_retriever import KnowhereGraphRetriever
from eagle_rag.retrievers.pixelrag_visual_retriever import PixelRAGVisualRetriever


def test_knowhere_graph_retriever_stores_plugin_namespace() -> None:
    retriever = KnowhereGraphRetriever(top_k=3, plugin_namespace="biomed")
    assert retriever.plugin_namespace == "biomed"


def test_knowhere_graph_retriever_defaults_to_none() -> None:
    retriever = KnowhereGraphRetriever(top_k=3)
    assert retriever.plugin_namespace is None


def test_pixelrag_visual_retriever_stores_plugin_namespace() -> None:
    retriever = PixelRAGVisualRetriever(top_k=3, plugin_namespace="biomed")
    assert retriever.plugin_namespace == "biomed"
    # _search_params must propagate the namespace to search_visual.
    assert retriever._search_params()["plugin_namespace"] == "biomed"


def test_pixelrag_visual_retriever_defaults_to_none_in_params() -> None:
    retriever = PixelRAGVisualRetriever(top_k=3)
    assert retriever.plugin_namespace is None
    assert retriever._search_params()["plugin_namespace"] is None


def test_knowhere_retriever_passes_namespace_to_text_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_retrieve`` must call ``get_text_index(plugin_namespace=...)`` (G17 binding)."""
    captured: dict[str, object] = {}

    class _FakeIndex:
        def as_retriever(self, **_kwargs: object) -> object:
            class _R:
                def retrieve(self, _query: object) -> list[object]:
                    return []

            return _R()

    def _fake_get_text_index(plugin_namespace: str | None = None, **_k: object) -> object:
        captured["plugin_namespace"] = plugin_namespace
        return _FakeIndex()

    # parent_doc_retrieval must be off so we hit the plain retrieve branch.
    monkeypatch.setattr(
        "eagle_rag.config.get_settings",
        lambda: (
            pytest.MonkeyPatch().setattr(type(None), "router", None)
            if False
            else _settings_with(parent_doc_retrieval=False)
        ),
    )
    monkeypatch.setattr(
        "eagle_rag.retrievers.knowhere_graph_retriever.get_text_index",
        _fake_get_text_index,
    )

    retriever = KnowhereGraphRetriever(top_k=3, plugin_namespace="biomed")
    from llama_index.core.schema import QueryBundle

    retriever.retrieve(QueryBundle(query_str="HER2 pathway"))
    assert captured["plugin_namespace"] == "biomed"


def test_visual_store_search_forwards_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``search_visual`` must resolve a client bound to the namespace's DB."""
    from eagle_rag.index import milvus_visual_store

    captured: dict[str, object] = {}

    class _FakeClient:
        def search(self, **kwargs: object) -> list[list[dict[str, object]]]:
            return [[]]

    def _fake_get_visual_client(plugin_namespace: str | None = None, **_k: object) -> _FakeClient:
        captured["plugin_namespace"] = plugin_namespace
        return _FakeClient()

    monkeypatch.setattr(milvus_visual_store, "get_visual_client", _fake_get_visual_client)
    monkeypatch.setattr(milvus_visual_store, "_collection_name", lambda: "eagle_visual")
    monkeypatch.setattr(
        milvus_visual_store,
        "_search_params",
        lambda _it: {"params": {}},
    )
    monkeypatch.setattr(
        milvus_visual_store,
        "get_settings",
        lambda: _settings_with(visual_index_type="HNSW"),
    )

    milvus_visual_store.search_visual([0.1] * 8, top_k=2, plugin_namespace="biomed")
    assert captured["plugin_namespace"] == "biomed"


def test_visual_store_read_funcs_accept_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """count/delete/fetch/distinct read funcs must thread plugin_namespace to the client."""
    from eagle_rag.index import milvus_visual_store

    captured: list[str | None] = []

    class _FakeClient:
        def query(self, coll_name: str = "", **_kwargs: object) -> list[dict[str, object]]:
            return []

        def get_collection_stats(self, _name: str) -> dict[str, object]:
            return {"row_count": 0}

        def delete(self, **_kwargs: object) -> None:
            return None

    def _fake_get_visual_client(plugin_namespace: str | None = None, **_k: object) -> _FakeClient:
        captured.append(plugin_namespace)
        return _FakeClient()

    monkeypatch.setattr(milvus_visual_store, "get_visual_client", _fake_get_visual_client)
    monkeypatch.setattr(milvus_visual_store, "_collection_name", lambda: "eagle_visual")

    milvus_visual_store.count_visual(plugin_namespace="biomed")
    milvus_visual_store.fetch_visual_by_document("doc-1", plugin_namespace="biomed")
    milvus_visual_store.delete_visual_by_document("doc-1", plugin_namespace="biomed")
    milvus_visual_store.delete_visual_by_kb("kb-1", plugin_namespace="biomed")
    milvus_visual_store.distinct_years(plugin_namespace="biomed")
    assert captured == ["biomed"] * 5


def test_retriever_orchestrator_core_text_forwards_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RetrieverOrchestrator._retrieve_core_text must construct the retriever with namespace."""
    from eagle_rag.plugins.retriever_orchestrator import RetrieverOrchestrator

    captured: dict[str, object] = {}

    class _FakeRetriever:
        def __init__(self, **kwargs: object) -> None:
            captured["plugin_namespace"] = kwargs.get("plugin_namespace")

        def retrieve(self, _query: str) -> list[object]:
            return []

    monkeypatch.setattr(
        "eagle_rag.plugins.retriever_orchestrator.KnowhereGraphRetriever",
        _FakeRetriever,
    )

    orch = RetrieverOrchestrator(plugin_manager=_stub_manager())
    orch._retrieve_core_text(
        "query",
        kb_name=None,
        source_type=None,
        year=None,
        scope_kb_names=None,
        scope_doc_ids=None,
        use_scope_filter=False,
        top_k=3,
        plugin_namespace="biomed",
    )
    assert captured["plugin_namespace"] == "biomed"


def test_retriever_orchestrator_core_visual_forwards_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RetrieverOrchestrator._retrieve_core_visual must construct the retriever with namespace."""
    from eagle_rag.plugins.retriever_orchestrator import RetrieverOrchestrator

    captured: dict[str, object] = {}

    class _FakeRetriever:
        def __init__(self, **kwargs: object) -> None:
            captured["plugin_namespace"] = kwargs.get("plugin_namespace")

        def retrieve(self, _query: str, **_kwargs: object) -> list[object]:
            return []

    monkeypatch.setattr(
        "eagle_rag.plugins.retriever_orchestrator.PixelRAGVisualRetriever",
        _FakeRetriever,
    )

    orch = RetrieverOrchestrator(plugin_manager=_stub_manager())
    orch._retrieve_core_visual(
        "query",
        kb_name=None,
        source_type=None,
        year=None,
        scope_kb_names=None,
        scope_doc_ids=None,
        use_scope_filter=False,
        query_image_bytes=None,
        top_k=3,
        plugin_namespace="biomed",
    )
    assert captured["plugin_namespace"] == "biomed"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


class _Settings:
    """Minimal settings stub for retriever/store branches under test."""

    class _Router:
        parent_doc_retrieval = False
        rrf_k = 60

    class _Milvus:
        text_collection = "eagle_text"
        visual_collection = "eagle_visual"
        visual_index_type = "HNSW"

    class _Plugins:
        default_namespace = "core"

    router = _Router()
    milvus = _Milvus()
    plugins = _Plugins()


def _settings_with(
    *,
    parent_doc_retrieval: bool | None = None,
    visual_index_type: str | None = None,
) -> _Settings:
    s = _Settings()
    if parent_doc_retrieval is not None:
        s.router.parent_doc_retrieval = parent_doc_retrieval  # type: ignore[misc]
    if visual_index_type is not None:
        s.milvus.visual_index_type = visual_index_type  # type: ignore[misc]
    return s


class _StubEncoderRegistry:
    def validate_plan(self, _collection: str, _encoder: str) -> None:
        return None


class _StubManager:
    default_namespace = "core"
    audit = None
    bus = None

    @property
    def encoder_registry(self) -> _StubEncoderRegistry:
        return _StubEncoderRegistry()


def _stub_manager() -> _StubManager:
    return _StubManager()
