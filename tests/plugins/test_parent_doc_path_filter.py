"""Parent-document path-prefix filter spike (P0-13 / G5)."""

from __future__ import annotations

from llama_index.core.vector_stores import FilterCondition, FilterOperator, MetadataFilter

from eagle_rag.retrievers.knowhere_graph_retriever import KnowhereGraphRetriever


def test_path_prefix_uses_text_match_operator() -> None:
    retriever = KnowhereGraphRetriever(
        similarity_top_k=3,
        kb_name="default",
    )
    filters = retriever._build_filters(path_prefix="1.2")
    assert filters is not None
    path_filter = next(f for f in filters.filters if getattr(f, "key", None) == "path")
    assert isinstance(path_filter, MetadataFilter)
    assert path_filter.operator == FilterOperator.TEXT_MATCH
    assert path_filter.value == "1.2"


def test_parent_doc_filters_include_section_summary_type() -> None:
    retriever = KnowhereGraphRetriever(similarity_top_k=2, kb_name="default")
    filters = retriever._build_filters(type_filter="section_summary")
    assert filters is not None
    type_filter = next(f for f in filters.filters if getattr(f, "key", None) == "type")
    assert type_filter.operator == FilterOperator.EQ
    assert type_filter.value == "section_summary"


def test_scope_filters_combine_with_and() -> None:
    retriever = KnowhereGraphRetriever(
        similarity_top_k=2,
        kb_name="default",
        document_ids=["doc-a"],
    )
    filters = retriever._build_filters(path_prefix="root")
    assert filters is not None
    assert filters.condition == FilterCondition.AND
