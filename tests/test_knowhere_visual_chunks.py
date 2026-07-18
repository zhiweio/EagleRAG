"""Visual chunk extraction, dispatch, and ensure_collection migration tests.

Covers:
- ``extract_visual_chunks``: extracts image/table visual chunks from ``ParseResult.chunks``;
  ``parent_section`` follows the most recent text chunk's ``path``.
- ``dispatch_visual_chunks``: uploads to MinIO + dispatches via ``app.send_task`` to
``pixelrag_queue``;
  failures do not raise.
- ``ensure_collection``: when an old Collection is missing fields like ``chunk_type``, it adds them
  incrementally via ``add_collection_field`` instead of drop-and-rebuild.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from eagle_rag.ingest.knowhere_adapter import (
    dispatch_visual_chunks,
    extract_visual_chunks,
)

# ---------------------------------------------------------------------------
# Helpers: build chunk / parse_result
# ---------------------------------------------------------------------------


def _make_chunk(
    chunk_id: str,
    *,
    type: str = "text",
    content: str = "",
    path: str = "",
    data: bytes | None = None,
    html: str | None = None,
    summary: str = "",
    file_path: str = "",
) -> SimpleNamespace:
    """Build a Knowhere SDK chunk duck-typed object (with nested metadata)."""
    return SimpleNamespace(
        chunk_id=chunk_id,
        type=type,
        content=content,
        path=path,
        data=data,
        html=html,
        metadata=SimpleNamespace(
            summary=summary,
            keywords=[],
            page_nums=[1],
            connect_to=[],
            file_path=file_path,
            original_name=None,
            table_type=None,
        ),
    )


def _make_parse_result(chunks: list[SimpleNamespace]) -> SimpleNamespace:
    return SimpleNamespace(
        chunks=chunks,
        text_chunks=[c for c in chunks if c.type == "text"],
        image_chunks=[c for c in chunks if c.type == "image"],
        table_chunks=[c for c in chunks if c.type == "table"],
        manifest=SimpleNamespace(source_file_name="mock.pdf", job_id=None),
        full_markdown="",
        document_id=None,
        namespace=None,
    )


# ---------------------------------------------------------------------------
# Part 1: extract_visual_chunks
# ---------------------------------------------------------------------------


def test_extract_visual_chunks_mixed():
    """Mixed text/image/table: chunks extracted; parent_section follows latest text chunk."""
    chunks = [
        _make_chunk("t1", type="text", content="第一节", path="doc/1 Intro"),
        _make_chunk("t2", type="text", content="架构", path="doc/3 Model Architecture"),
        _make_chunk(
            "img1",
            type="image",
            data=b"\x89PNG fake",
            path="",
            summary="Transformer 架构图",
            file_path="images/image-1-Transformer.jpg",
        ),
        _make_chunk("t3", type="text", content="复杂度", path="doc/3.2 Complexity"),
        _make_chunk(
            "tbl1",
            type="table",
            html="<table><tr><td>Layer</td></tr></table>",
            path="",
            summary="层复杂度对比表",
            file_path="tables/table-0 Layer Complexity.html",
        ),
        _make_chunk(
            "img2",
            type="image",
            data=b"\x89PNG fake2",
            path="",
            summary="Attention 示意图",
            file_path="images/image-2.png",
        ),
    ]
    parse_result = _make_parse_result(chunks)

    visual = extract_visual_chunks(parse_result)

    # 3 visual chunks (2 image + 1 table).
    assert len(visual) == 3

    # parent_section follows the most recent text chunk's path.
    assert visual[0]["parent_section"] == "doc/3 Model Architecture"
    assert visual[1]["parent_section"] == "doc/3.2 Complexity"
    assert visual[2]["parent_section"] == "doc/3.2 Complexity"

    # Type and data.
    assert visual[0]["type"] == "image"
    assert visual[0]["data"] == b"\x89PNG fake"
    assert visual[0]["html"] is None

    assert visual[1]["type"] == "table"
    assert visual[1]["html"] == "<table><tr><td>Layer</td></tr></table>"
    assert visual[1]["data"] is None

    assert visual[2]["type"] == "image"
    assert visual[2]["data"] == b"\x89PNG fake2"
    assert visual[2]["html"] is None

    # Each item contains chunk_id/summary/file_path.
    for v in visual:
        assert "chunk_id" in v
        assert "summary" in v
        assert "file_path" in v

    assert visual[0]["chunk_id"] == "img1"
    assert visual[0]["summary"] == "Transformer 架构图"
    assert visual[0]["file_path"] == "images/image-1-Transformer.jpg"


def test_extract_visual_chunks_no_visual():
    """A pure-text chunk list returns an empty list."""
    chunks = [
        _make_chunk("t1", type="text", content="文本1", path="sec1"),
        _make_chunk("t2", type="text", content="文本2", path="sec2"),
    ]
    parse_result = _make_parse_result(chunks)

    assert extract_visual_chunks(parse_result) == []


def test_extract_visual_chunks_leading_visual():
    """A visual chunk appearing before any text chunk -> parent_section is an empty string."""
    chunks = [
        _make_chunk("img0", type="image", data=b"fake", path=""),
        _make_chunk("t1", type="text", content="文本", path="sec1"),
    ]
    parse_result = _make_parse_result(chunks)

    visual = extract_visual_chunks(parse_result)
    assert len(visual) == 1
    assert visual[0]["parent_section"] == ""


# ---------------------------------------------------------------------------
# Part 2: dispatch_visual_chunks
# ---------------------------------------------------------------------------


def test_dispatch_visual_chunks_image_and_table():
    """Image + table chunks: upload to MinIO + dispatch Celery subtask with correct kwargs."""
    visual_chunks = [
        {
            "chunk_id": "img1",
            "type": "image",
            "data": b"\x89PNG fake",
            "html": None,
            "summary": "架构图",
            "parent_section": "doc/3 Model Architecture",
            "file_path": "images/image-1-Transformer.jpg",
        },
        {
            "chunk_id": "tbl1",
            "type": "table",
            "data": None,
            "html": "<table>...</table>",
            "summary": "复杂度表",
            "parent_section": "doc/3.2 Complexity",
            "file_path": "tables/table-0.html",
        },
    ]

    with (
        patch("eagle_rag.storage.minio_client.ensure_bucket") as mock_ensure,
        patch("eagle_rag.storage.minio_client.upload_bytes") as mock_upload,
        patch("eagle_rag.tasks.celery_app.app.send_task") as mock_send,
    ):
        dispatch_visual_chunks(
            "job-123",
            "doc-abc",
            visual_chunks,
            kb_name="finance",
            source_type="policy",
        )

    # ensure_bucket called once.
    mock_ensure.assert_called_once()

    # upload_bytes called twice.
    assert mock_upload.call_count == 2

    # Image object_key ends with .jpg (inferred from the file_path extension).
    image_call = mock_upload.call_args_list[0]
    assert image_call.args[0] == "doc-abc/visual_chunks/img1.jpg"
    assert image_call.args[1] == b"\x89PNG fake"
    assert image_call.kwargs.get("content_type") == "image/jpeg"

    # Table object_key ends with .html.
    table_call = mock_upload.call_args_list[1]
    assert table_call.args[0] == "doc-abc/visual_chunks/tbl1.html"
    assert table_call.args[1] == b"<table>...</table>"
    assert table_call.kwargs.get("content_type") == "text/html"

    # app.send_task dispatched once.
    mock_send.assert_called_once()
    call_kwargs = mock_send.call_args
    assert call_kwargs.args[0] == "eagle_rag.tasks.knowhere_visual_chunks"
    assert call_kwargs.kwargs.get("queue") == "pixelrag_queue"
    assert call_kwargs.kwargs.get("routing_key") == "pixelrag_queue"

    kwargs = call_kwargs.kwargs["kwargs"]
    assert kwargs["job_id"] == "job-123:visual"
    assert kwargs["document_id"] == "doc-abc"
    assert kwargs["kb_name"] == "finance"
    assert kwargs["source_type"] == "policy"

    # chunks list: contains chunk_id/type/object_key/summary/parent_section/file_path,
    # and does NOT contain data/html (binary data has been stripped).
    dispatched_chunks = kwargs["chunks"]
    assert len(dispatched_chunks) == 2
    for desc in dispatched_chunks:
        assert "chunk_id" in desc
        assert "type" in desc
        assert "object_key" in desc
        assert "summary" in desc
        assert "parent_section" in desc
        assert "file_path" in desc
        assert "data" not in desc
        assert "html" not in desc

    assert dispatched_chunks[0]["object_key"] == "doc-abc/visual_chunks/img1.jpg"
    assert dispatched_chunks[1]["object_key"] == "doc-abc/visual_chunks/tbl1.html"
    assert dispatched_chunks[0]["parent_section"] == "doc/3 Model Architecture"


def test_dispatch_visual_chunks_failure_no_raise():
    """When upload_bytes raises, dispatch_visual_chunks returns None (does not re-raise)."""
    visual_chunks = [
        {
            "chunk_id": "img1",
            "type": "image",
            "data": b"fake",
            "html": None,
            "summary": "",
            "parent_section": "sec",
            "file_path": "img.png",
        },
    ]

    with (
        patch("eagle_rag.storage.minio_client.ensure_bucket"),
        patch(
            "eagle_rag.storage.minio_client.upload_bytes",
            side_effect=RuntimeError("minio down"),
        ),
        patch("eagle_rag.tasks.celery_app.app.send_task") as mock_send,
    ):
        result = dispatch_visual_chunks(
            "job-1", "doc-1", visual_chunks, kb_name=None, source_type="policy"
        )

    # Does not raise; returns None.
    assert result is None
    # Dispatch failed -> send_task not called.
    assert not mock_send.called


# ---------------------------------------------------------------------------
# Part 3: ensure_collection migration (add_collection_field instead of drop-and-rebuild)
# ---------------------------------------------------------------------------


@pytest.fixture
def _reset_visual_client():
    """Reset milvus_visual_store._client singleton before and after each ensure_collection test."""
    import eagle_rag.index.milvus_visual_store as store

    old = store._client_db
    store._client_db = None
    yield
    store._client_db = old


def test_ensure_collection_add_field_for_existing(_reset_visual_client):
    """An old Collection missing fields like chunk_type goes through add_collection_field, not
    drop-and-rebuild."""
    from eagle_rag.index import milvus_visual_store as store

    mock_client = MagicMock()

    # describe_collection returns the old schema (has kb_name, missing 4 new fields).
    old_fields = [
        {"name": "id"},
        {"name": "vector"},
        {"name": "image_path"},
        {"name": "image_id"},
        {"name": "document_id"},
        {"name": "page"},
        {"name": "position"},
        {"name": "kb_name"},
        {"name": "year"},
        {"name": "source_type"},
    ]

    call_count = {"has_collection": 0}

    def _has_collection(name):
        call_count["has_collection"] += 1
        # First call (migration compat check) returns True; second call (freshly_created check)
        # returns True.
        return True

    mock_client.has_collection = MagicMock(side_effect=_has_collection)
    mock_client.describe_collection = MagicMock(return_value={"fields": old_fields})

    # prepare_index_params returns a mock supporting chained add_index.
    mock_index_params = MagicMock()
    mock_client.prepare_index_params = MagicMock(return_value=mock_index_params)

    # Build mock settings.
    mock_settings = MagicMock()
    mock_settings.milvus.visual_collection = "eagle_visual"
    mock_settings.milvus.dim_visual = 2048
    mock_settings.milvus.visual_index_type = "hnsw"
    mock_settings.milvus.host = "localhost"
    mock_settings.milvus.port = "19530"

    mock_pool = MagicMock()
    mock_pool.get = MagicMock(return_value=mock_client)

    with (
        patch("eagle_rag.index.milvus_visual_store.get_milvus_pool", return_value=mock_pool),
        patch("eagle_rag.index.milvus_visual_store.get_settings", return_value=mock_settings),
    ):
        store.ensure_collection()

    # drop_collection should not be called (has kb_name, no drop-and-rebuild triggered).
    assert not mock_client.drop_collection.called, "旧 Collection 有 kb_name 字段时不应 drop 重建"

    # add_collection_field should be called 4 times
    # (chunk_type/parent_section/content_summary/source_chunk_id).
    assert mock_client.add_collection_field.call_count == 4

    # Verify the field names called.
    called_fields = {
        call.kwargs.get("field_name") for call in mock_client.add_collection_field.call_args_list
    }
    assert called_fields == {"chunk_type", "parent_section", "content_summary", "source_chunk_id"}

    # The chunk_type call should include default_value="tile".
    chunk_type_calls = [
        c
        for c in mock_client.add_collection_field.call_args_list
        if c.kwargs.get("field_name") == "chunk_type"
    ]
    assert len(chunk_type_calls) == 1
    assert chunk_type_calls[0].kwargs.get("default_value") == "tile"

    # The other fields should include nullable=True.
    for call in mock_client.add_collection_field.call_args_list:
        fname = call.kwargs.get("field_name")
        if fname == "chunk_type":
            continue
        assert call.kwargs.get("nullable") is True, f"{fname} 应为 nullable=True"

    # load_collection was called.
    assert mock_client.load_collection.called
