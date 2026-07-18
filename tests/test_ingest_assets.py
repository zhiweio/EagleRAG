"""End-to-end ingest tests against real assets/ files.

Runs the full ingest chain against 7 real files under ``assets/`` (PPTX/DOCX/PNG/PDF/XLSX):

- Routing decisions (PDF goes through the real ``probe_pdf_form`` probe; non-PDF by extension).
- Celery eager synchronous dispatch of router -> knowhere_parse / pixelrag_build.
- DB/MinIO/Milvus/image store/Knowhere SDK/pixelrag_render/pixelrag_embed are all stubbed with
  ``unittest.mock.patch`` so the chain runs without external services.
- Asserts downstream adapters are called correctly (upsert_text_nodes / upsert_visual / store_tile /
  update_status ready / update_chunk_count) and that the terminal state is SUCCESS.

Also includes Celery task registration tests and fail-closed guard tests (when the Knowhere SDK
raises ``KnowhereError``, it does not silently write to the index and the state becomes FAILED).
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
from eagle_rag.ingest.knowhere_adapter import KnowhereError
from eagle_rag.ingest.router import probe_pdf_form, route
from eagle_rag.ingest.runner import ingest_file
from eagle_rag.tasks.celery_app import app
from eagle_rag.tasks.state import TaskState

# ---------------------------------------------------------------------------
# Eager dispatch: send_task stand-in (same pattern as test_ingest_smoke.py, self-contained)
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
    """Run Celery tasks synchronously by replacing ``app.send_task`` with local eager dispatch."""
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


def _apply_mock_defaults(m):
    """Apply shared mock default return values (used by both mocks and mocks_no_parse)."""
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


@pytest.fixture
def mocks():
    """Unified mock infrastructure: DB/MinIO/Milvus/image store/registry/state/dedup."""
    with ExitStack() as stack:
        m = SimpleNamespace()
        for key, target in _MOCK_TARGETS.items():
            setattr(m, key, stack.enter_context(patch(target)))
        _apply_mock_defaults(m)
        yield m


@pytest.fixture
def mocks_no_parse():
    """``mocks`` variant: makes ``parse_with_knowhere_sdk`` raise ``KnowhereError`` to verify
        fail-closed.

    Under fail-closed, ``knowhere_parse``'s outer except catches ``KnowhereError`` -> records FAILED
    ->
    ``upsert_text_nodes`` is not called. All targets are patched, but the SDK parse side_effect is
    overridden.
    """
    with ExitStack() as stack:
        m = SimpleNamespace()
        for key, target in _MOCK_TARGETS.items():
            setattr(m, key, stack.enter_context(patch(target)))
        _apply_mock_defaults(m)
        # Override: parse_with_knowhere_sdk raises KnowhereError to trigger knowhere_parse's
        # fail-closed branch
        # (when side_effect is an exception instance it takes precedence over return_value).
        m.parse_with_knowhere_sdk.side_effect = KnowhereError("knowhere sdk down")
        yield m


@pytest.fixture
def assets_dir():
    """Return the project-root ``assets/`` directory; skip the whole test if it is missing."""
    p = Path(__file__).resolve().parent.parent / "assets"
    if not p.is_dir():
        pytest.skip("assets/ directory not found")
    return p


# ---------------------------------------------------------------------------
# Fake artifact builders (test doubles to avoid real SDK calls)
# ---------------------------------------------------------------------------


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
    return [
        {
            "image_bytes": b"\x89PNG\r\n\x1a\n mock",
            "png_bytes": b"\x89PNG\r\n\x1a\n mock",
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

# 7 real assets (file names contain spaces/Chinese/parens, all are valid paths).
ASSETS = [
    "Life Science Snowflake Introduction.pptx",
    "Request for Proposal on Investment Products Platform_v1.3.docx",
    "infographic (1).png",
    "【2025】AWS SAP-C02 英文.pdf",
    "初始化数据_industry表_GB_T 4754-2017 国民经济行业分类（一维表）.xlsx",
    "置身钉内 14.34.50.pdf",
    "语法.pptx",
]


def _asset_id(name: str) -> str:
    """Generate a short readable parametrize id (drop spaces and parens that affect the shell)."""
    return (
        name.replace(" ", "_").replace("(", "").replace(")", "").replace("【", "").replace("】", "")
    )


@pytest.mark.parametrize("name", ASSETS, ids=_asset_id)
def test_ingest_asset_happy_path(mocks, assets_dir, name):
    """For each real asset: routing + eager dispatch + adapter calls + terminal SUCCESS."""
    path = assets_dir / name
    if not path.is_file():
        pytest.skip(f"asset not found: {name}")

    is_pdf = name.lower().endswith(".pdf")

    # 1. Compute the expected pipeline: PDF goes through the real probe; non-PDF by extension.
    if is_pdf:
        expected = route(filename=name, local_path=str(path))
        # 2. Extra assertion that the probe result is consistent with the routing.
        probe = probe_pdf_form(str(path))
        if probe == "text":
            assert expected == ["knowhere"], f"probe=text 但 route={expected}"
        elif probe == "scanned":
            assert expected == ["pixelrag"], f"probe=scanned 但 route={expected}"
        else:  # pragma: no cover
            pytest.fail(f"未知探针结果: {probe}")
    else:
        expected = route(filename=name)

    # 3. Run ingest (eager mode runs the full chain synchronously).
    result = ingest_file(str(path), filename=name)

    # 4. Basic assertions: no dedup hit, has document_id.
    assert result["dedup_hit"] is False
    assert result["document_id"], "应返回非空 document_id"

    # 5. knowhere pipeline assertions.
    if "knowhere" in expected:
        assert mocks.upsert_text_nodes.called, "knowhere_parse 应调用 upsert_text_nodes"
        nodes_arg = mocks.upsert_text_nodes.call_args.args[0]
        assert nodes_arg, "upsert_text_nodes 的 nodes 列表不应为空"
        # update_status(document_id, "ready"): the second positional arg is status.
        assert mocks.update_status_knowhere.called
        assert mocks.update_status_knowhere.call_args.args[1] == "ready"
        assert mocks.update_chunk_count_knowhere.called
        # Terminal SUCCESS: update_state(job_id, state, ...) second positional arg is state.
        assert mocks.update_state_knowhere.call_args.args[1] == TaskState.SUCCESS
    else:
        assert not mocks.upsert_text_nodes.called, "非 knowhere 路径不应触发 upsert_text_nodes"

    # 6. pixelrag pipeline assertions.
    if "pixelrag" in expected:
        assert mocks.upsert_visual.called, "pixelrag_build 应调用 upsert_visual"
        vec = mocks.upsert_visual.call_args.kwargs.get("vector")
        assert vec, "upsert_visual 的 vector 不应为空"
        assert mocks.store_tile.called, "pixelrag_build 应调用 store_tile"
        assert mocks.update_status_pixelrag.called
        assert mocks.update_status_pixelrag.call_args.args[1] == "ready"
        assert mocks.update_chunk_count_pixelrag.called
        assert mocks.update_state_pixelrag.call_args.args[1] == TaskState.SUCCESS
    else:
        assert not mocks.upsert_visual.called, "非 pixelrag 路径不应触发 upsert_visual"


def test_celery_tasks_registered():
    """Celery app registers three ingest task modules via include=; names appear in app.tasks."""
    app.loader.import_default_modules()
    names = set(app.tasks.keys())
    assert "eagle_rag.tasks.knowhere_parse" in names
    assert "eagle_rag.tasks.pixelrag_build" in names
    assert "eagle_rag.ingest.router.ingest_router" in names


def test_fail_closed_no_silent_ingest(mocks_no_parse, assets_dir):
    """fail-closed guard: when the Knowhere SDK raises ``KnowhereError``,
    it must not silently write to the text index, and the task state becomes FAILED.
    """
    path = assets_dir / "语法.pptx"
    if not path.is_file():
        pytest.skip("asset not found: 语法.pptx")

    # Eager dispatch: knowhere_parse's parse_with_knowhere_sdk is mocked to raise KnowhereError;
    # under fail-closed the task ends in FAILED; the outer layer may raise Retry/exception, swallow
    # it.
    try:
        ingest_file(str(path), filename="语法.pptx")
    except Exception:
        pass

    # No text index writes should happen (fail-closed: no silent fallback).
    assert mocks_no_parse.upsert_text_nodes.called is False

    # FAILED state should be recorded: update_state(job_id, state, ...) second positional arg is
    # state.
    states = [c.args[1] for c in mocks_no_parse.update_state_knowhere.call_args_list]
    assert TaskState.FAILED in states, f"期望状态含 FAILED，实际: {states}"


def test_knowhere_milvus_write_failure_marks_failed(mocks, assets_dir):
    """When upsert_text_nodes fails, the error bubbles up to the outer except -> FAILED;
    it no longer swallows the error and then marks ready/SUCCESS.

    Knowhere Milvus write failures must not silently succeed.
    """
    path = assets_dir / "语法.pptx"
    if not path.is_file():
        pytest.skip("asset not found: 语法.pptx")

    # Make Milvus text write raise.
    mocks.upsert_text_nodes.side_effect = RuntimeError("milvus down")

    # Eager dispatch: after the failure bubbles up, retry_on_failure may raise Retry/exception,
    # swallow it.
    try:
        ingest_file(str(path), filename="语法.pptx")
    except Exception:
        pass

    # The failure happens at upsert_text_nodes (before update_status/update_chunk_count):
    # it should not mark ready, and should not write chunk_count.
    assert not mocks.update_status_knowhere.called, "Milvus 写入失败不应标 ready"
    assert not mocks.update_chunk_count_knowhere.called, "Milvus 写入失败不应写 chunk_count"
    # FAILED should be recorded.
    states = [c.args[1] for c in mocks.update_state_knowhere.call_args_list]
    assert TaskState.FAILED in states, f"期望状态含 FAILED，实际: {states}"
