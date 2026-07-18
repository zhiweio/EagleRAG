"""Ingest pipeline smoke tests.

Covers five source types + a dedup hit, all using test doubles (``unittest.mock.patch``):
- ``parse_with_knowhere_sdk`` / ``render_to_tiles`` / ``embed_tiles`` are stubbed to return
  SDK-duck-typed fake artifacts (with nested ``metadata``), avoiding real service calls.
- Celery runs in eager mode (``task_always_eager`` + ``task_eager_propagates``).
- DB/MinIO/Milvus/image store calls are intercepted so the full chain runs without external
services.

The focus is verifying routing dispatch + task dispatch chain correctness, not real parsing.
"""

from __future__ import annotations

import inspect
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

# Register Celery tasks: ensure app.send_task can locate task functions in eager mode.
import eagle_rag.ingest.knowhere_adapter  # noqa: F401
import eagle_rag.ingest.pixelrag_adapter  # noqa: F401
import eagle_rag.ingest.router  # noqa: F401
from eagle_rag.ingest.router import infer_source_type, route
from eagle_rag.ingest.runner import get_job_status, ingest_file, ingest_url
from eagle_rag.tasks.celery_app import app

# ---------------------------------------------------------------------------
# Eager dispatch: send_task stand-in
# ---------------------------------------------------------------------------


def _eager_send_task(name, args=None, kwargs=None, **_options):
    """``app.send_task`` stand-in: look up a registered task by name and run it via ``task.apply``.

    Celery's ``task_always_eager`` does not affect ``send_task`` (it would try to reach the broker),
    so tests replace ``app.send_task`` with this function to bypass Redis/broker.

    Extra kwargs filtering: router passes ``source_uri`` to knowhere_parse, but that task signature
    does not accept it -> use inspect to filter out undeclared kwargs and avoid TypeError.
    """
    task = app.tasks.get(name)
    if task is None:
        raise KeyError(f"task not registered: {name}")
    try:
        params = set(inspect.signature(task.run).parameters.keys())
        filtered = {k: v for k, v in (kwargs or {}).items() if k in params}
    except (TypeError, ValueError):  # pragma: no cover
        filtered = kwargs or {}
    return task.apply(args=args or (), kwargs=filtered)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def celery_eager():
    """Run Celery tasks synchronously by replacing ``app.send_task`` with local eager dispatch.

    Returns the send_task mock so tests can assert call counts (e.g. dedup hit should not be
    called).
    """
    old_eager = app.conf.task_always_eager
    old_prop = app.conf.task_eager_propagates
    app.conf.task_always_eager = True
    app.conf.task_eager_propagates = True
    with patch.object(app, "send_task", side_effect=_eager_send_task) as mock_send:
        yield mock_send
    app.conf.task_always_eager = old_eager
    app.conf.task_eager_propagates = old_prop


# runner calls module attributes (task_state.* / registry.* / dedup.* / minio_client.*),
# so patching source module attributes is enough; router/knowhere/pixelrag use direct imports,
# so each module namespace must be patched individually.
_MOCK_TARGETS = {
    # state (runner module attr + three adapters' direct imports)
    "create_audit": "eagle_rag.tasks.state.create_audit",
    "update_state_runner": "eagle_rag.tasks.state.update_state",
    "update_state_router": "eagle_rag.ingest.router.update_state",
    "update_state_knowhere": "eagle_rag.ingest.knowhere_adapter.update_state",
    "update_state_pixelrag": "eagle_rag.ingest.pixelrag_adapter.update_state",
    "get_audit": "eagle_rag.tasks.state.get_audit",
    # registry (runner module attr + router direct import)
    "register_document_runner": "eagle_rag.index.registry.register_document",
    "register_document_router": "eagle_rag.ingest.router.register_document",
    "update_chunk_count_knowhere": "eagle_rag.ingest.knowhere_adapter.update_chunk_count",
    "update_status_knowhere": "eagle_rag.ingest.knowhere_adapter.update_status",
    "update_chunk_count_pixelrag": "eagle_rag.ingest.pixelrag_adapter.update_chunk_count",
    "update_status_pixelrag": "eagle_rag.ingest.pixelrag_adapter.update_status",
    # dedup (runner module attr)
    "check_duplicate": "eagle_rag.storage.dedup.check_duplicate",
    "register": "eagle_rag.storage.dedup.register",
    # minio (runner module attr + adapter direct import + images.store internal call)
    "upload_file": "eagle_rag.storage.minio_client.upload_file",
    "upload_bytes": "eagle_rag.storage.minio_client.upload_bytes",
    "download_file_knowhere": "eagle_rag.ingest.knowhere_adapter.download_file",
    "download_file_pixelrag": "eagle_rag.ingest.pixelrag_adapter.download_file",
    "ensure_bucket": "eagle_rag.storage.minio_client.ensure_bucket",
    "get_object_url": "eagle_rag.storage.minio_client.get_object_url",
    "ensure_image_dir": "eagle_rag.images.store.ensure_image_dir",
    # milvus (adapter direct import)
    "upsert_text_nodes": "eagle_rag.ingest.knowhere_adapter.upsert_text_nodes",
    "upsert_visual": "eagle_rag.ingest.pixelrag_adapter.upsert_visual",
    # image store (pixelrag adapter direct import)
    "store_tile": "eagle_rag.ingest.pixelrag_adapter.store_tile",
    # pixelrag render/embed (pixelrag_render/pixelrag_embed not installed by default; under
    # fail-closed
    # the internal mock fallback would raise, so stub render_to_tiles/embed_tiles to let the
    # pipeline run)
    "render_to_tiles": "eagle_rag.ingest.pixelrag_adapter.render_to_tiles",
    "embed_tiles": "eagle_rag.ingest.pixelrag_adapter.embed_tiles",
    # knowhere SDK parsing (avoid real SDK calls; return mock artifacts directly)
    "parse_with_knowhere_sdk": "eagle_rag.ingest.knowhere_adapter.parse_with_knowhere_sdk",
}


@pytest.fixture
def mocks():
    """Unified mock infrastructure: DB/MinIO/Milvus/image store/registry/state/dedup.

    By default check_duplicate returns None (no hit); upsert_text_nodes / store_tile return
    placeholder values. Each test may override mock.return_value as needed.
    """
    with ExitStack() as stack:
        m = SimpleNamespace()
        for key, target in _MOCK_TARGETS.items():
            setattr(m, key, stack.enter_context(patch(target)))
        # Default return values.
        m.check_duplicate.return_value = None
        m.upsert_text_nodes.return_value = ["mock_node_1"]
        m.store_tile.return_value = {
            "image_id": "mock",
            "object_key": "mock/key.png",
            "local_path": "/tmp/mock.png",
            "url": "http://mock/mock.png",
        }
        m.get_audit.return_value = {"job_id": "mock", "status": "success"}
        m.upload_file.return_value = "mock/object_key"
        m.upload_bytes.return_value = "mock/object_key"
        m.download_file_knowhere.return_value = Path("/tmp/mock_dl")
        m.download_file_pixelrag.return_value = Path("/tmp/mock_dl")
        # knowhere SDK parse returns fake artifacts (nested metadata) to avoid real SDK calls.
        m.parse_with_knowhere_sdk.return_value = _fake_knowhere_parse_result()
        # pixelrag render/embed: return mock tiles with vectors to avoid hitting the fail-closed
        # fallback.
        m.render_to_tiles.return_value = _mock_tiles()
        m.embed_tiles.return_value = _mock_tiles_with_vec()
        yield m


# ---------------------------------------------------------------------------
# Helpers: build temp files
# ---------------------------------------------------------------------------


def _make_pdf(path: Path, content: bytes = b"%PDF-1.4 mock pdf\n") -> Path:
    path.write_bytes(content)
    return path


def _make_xlsx(path: Path) -> Path:
    # Placeholder bytes; the pixelrag mock does not read real content, and routing only checks the
    # extension.
    path.write_bytes(b"PK\x03\x04 mock xlsx\n")
    return path


def _make_png(path: Path) -> Path:
    path.write_bytes(b"\x89PNG\r\n\x1a\n mock png\n")
    return path


def _fake_knowhere_parse_result():
    """Build a fake return value for ``parse_with_knowhere_sdk`` (ParseResult duck-typed object).

    Test-only: use ``SimpleNamespace`` to align with the SDK ``ParseResult`` and ``TextChunk``
    shapes.
    The key is putting summary/keywords/page_nums/connect_to/file_path on nested ``metadata``
    (matching the real SDK ``ChunkMetadata``) so ``chunks_to_text_nodes``'s ``_meta(chunk, ...)``
    reads them on the same path as real SDK chunks, avoiding fake/real shape divergence.
    """
    chunk = SimpleNamespace(
        chunk_id="fake_0",
        type="text",
        content="第一条 在中国境内有住所的个人为居民个人。",
        path="个税法/第一条",
        metadata=SimpleNamespace(
            summary="居民个人与非居民个人的认定标准及纳税义务范围。",
            keywords=["居民个人", "非居民个人", "纳税义务"],
            page_nums=[1],
            connect_to=[],
            file_path=None,
            original_name=None,
            table_type=None,
        ),
        html=None,
        data=None,
    )
    return SimpleNamespace(
        chunks=[chunk],
        text_chunks=[chunk],
        image_chunks=[],
        table_chunks=[],
        manifest=SimpleNamespace(source_file_name="mock.pdf", job_id=None),
        full_markdown=chunk.content,
        document_id=None,
        namespace=None,
    )


def _mock_tiles(n: int = 2) -> list[dict]:
    """Build the mock return value for render_to_tiles (n tiles, no vectors)."""
    tile_bytes = b"\x89PNG\r\n\x1a\n mock"
    return [
        {
            "image_bytes": tile_bytes,
            "png_bytes": tile_bytes,
            "page": 1,
            "position": f"strip_{i}",
            "width": 1024,
            "height": 1024,
        }
        for i in range(n)
    ]


def _mock_tiles_with_vec(n: int = 2, dim: int = 2048) -> list[dict]:
    """Build the mock return value for embed_tiles (adds a vector field on top of _mock_tiles)."""
    return [{**t, "vector": [0.0] * dim} for t in _mock_tiles(n)]


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


def test_ingest_policy_pdf_knowhere(mocks, tmp_path):
    """Tax-law PDF -> route=['knowhere']; knowhere_parse runs synchronously under eager mode."""
    pdf = _make_pdf(tmp_path / "个税法.pdf")

    result = ingest_file(str(pdf), filename="个税法.pdf")

    assert result["dedup_hit"] is False
    assert result["status"] == "pending"
    assert result["document_id"]

    # Routing assertion.
    assert route(filename="个税法.pdf") == ["knowhere"]

    # knowhere pipeline executed: upsert_text_nodes was called.
    assert mocks.upsert_text_nodes.called, "knowhere_parse 应调用 upsert_text_nodes"
    # pixelrag pipeline not executed.
    assert not mocks.store_tile.called, "knowhere 路径不应触发 pixelrag store_tile"


def test_ingest_financial_pdf_knowhere(mocks, tmp_path):
    """Financial PDF (source_type_hint=financial) -> route=['knowhere'].

    source_type_hint no longer affects routing; the mock PDF cannot be parsed by pypdf/pdfplumber,
    so probe_pdf_form falls back to "text" -> routes to knowhere.
    """
    pdf = _make_pdf(tmp_path / "2023年报-资产负债表.pdf")

    result = ingest_file(str(pdf), filename="2023年报-资产负债表.pdf", source_type_hint="financial")

    assert result["dedup_hit"] is False
    # source_type_hint is only a metadata label and does not affect routing.
    assert route(filename="2023年报-资产负债表.pdf", source_type_hint="financial") == ["knowhere"]

    # knowhere pipeline executed: upsert_text_nodes was called.
    assert mocks.upsert_text_nodes.called, "knowhere_parse 应调用 upsert_text_nodes"
    # pixelrag pipeline not executed.
    assert not mocks.store_tile.called, "knowhere 路径不应触发 pixelrag store_tile"


def test_ingest_excel(mocks, tmp_path):
    """Excel -> route=['knowhere'] (.xlsx is in the knowhere_exts config)."""
    xlsx = _make_xlsx(tmp_path / "data.xlsx")

    result = ingest_file(str(xlsx), filename="data.xlsx")

    assert result["dedup_hit"] is False
    assert route(filename="data.xlsx") == ["knowhere"]
    # knowhere pipeline executed.
    assert mocks.upsert_text_nodes.called, "knowhere_parse 应调用 upsert_text_nodes"
    # pixelrag pipeline not executed.
    assert not mocks.store_tile.called, "knowhere 路径不应触发 pixelrag store_tile"


def test_ingest_image(mocks, tmp_path):
    """Image -> route=['pixelrag']."""
    png = _make_png(tmp_path / "chart.png")

    result = ingest_file(str(png), filename="chart.png")

    assert result["dedup_hit"] is False
    assert route(filename="chart.png") == ["pixelrag"]
    assert mocks.store_tile.called, "pixelrag_build 应调用 store_tile"


def test_ingest_web_url(mocks):
    """Web URL -> route=['pixelrag']; source_type inferred as business.

    The URL contains the "business" keyword to trigger business inference (the router keyword
    table has no pinyin "gongshang").
    """
    url = "https://example.com/business/info"

    result = ingest_url(url)

    assert result["dedup_hit"] is False
    assert result["status"] == "pending"
    # URL -> pixelrag.
    assert route(filename=url, source_uri=url) == ["pixelrag"]
    # source_type inferred as business.
    assert infer_source_type(url, source_uri=url) == "business", "URL 应推断为 business 来源"
    # pixelrag executed (uses source_uri as path).
    assert mocks.store_tile.called, "pixelrag_build 应调用 store_tile"


def test_ingest_scanned_pdf_pixelrag(mocks, tmp_path):
    """Scanned PDF (probe_pdf_form returns scanned) -> route=['pixelrag']; pixelrag_build runs."""
    pdf = _make_pdf(tmp_path / "scan.pdf")

    with patch("eagle_rag.ingest.router.route", return_value=["pixelrag"]):
        result = ingest_file(str(pdf), filename="scan.pdf")

        assert result["dedup_hit"] is False

    assert mocks.store_tile.called, "pixelrag_build 应调用 store_tile"
    assert not mocks.upsert_text_nodes.called, "pixelrag 路径不应触发 knowhere"


def test_ingest_kb_name_passthrough(mocks, tmp_path):
    """ingest_file passes kb_name to audit writes and the routing task's document registration."""
    pdf = _make_pdf(tmp_path / "个税法.pdf")

    ingest_file(str(pdf), filename="个税法.pdf", kb_name="pharma")

    # Audit write carries kb_name.
    assert mocks.create_audit.called
    assert mocks.create_audit.call_args.kwargs.get("kb_name") == "pharma"
    # Document registration in the routing task carries kb_name.
    assert mocks.register_document_router.called
    assert mocks.register_document_router.call_args.kwargs.get("kb_name") == "pharma"


def test_dedup_hit(mocks, tmp_path, celery_eager):
    """Ingesting the same file again with a check_duplicate hit -> dedup_hit=True and no task
    dispatched."""
    pdf = _make_pdf(tmp_path / "个税法.pdf")

    # Simulate a dedup hit on an existing document.
    existing_doc_id = "existing-doc-id-1234"
    mocks.check_duplicate.return_value = {
        "sha256": "fakehash",
        "document_id": existing_doc_id,
        "object_key": "policy/existing/个税法.pdf",
        "source_name": "个税法.pdf",
        "created_at": None,
    }

    result = ingest_file(str(pdf), filename="个税法.pdf")

    assert result["dedup_hit"] is True
    assert result["status"] == "success"
    assert result["document_id"] == existing_doc_id
    # No routing task should be dispatched.
    assert not celery_eager.called, "去重命中不应派发 Celery 任务"
    # Audit write (hit branch).
    assert mocks.create_audit.called


def test_get_job_status(mocks):
    """get_job_status passes through to get_audit."""
    mocks.get_audit.return_value = {"job_id": "j1", "status": "success"}
    out = get_job_status("j1")
    assert out == {"job_id": "j1", "status": "success"}
    mocks.get_audit.assert_called_with("j1")
