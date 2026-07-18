"""Unit tests for Core visual encoder backends (local / DashScope)."""

from __future__ import annotations

from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from eagle_rag.ingest import visual_encoder as ve


def _visual_settings(
    *,
    provider: str = "dashscope",
    model: str = "qwen3-vl-embedding",
    dim: int = 2048,
    api_key: str = "sk-test",
    base_url: str = "",
    batch_size: int = 2,
    timeout_s: float = 60.0,
    max_retries: int = 2,
) -> SimpleNamespace:
    return SimpleNamespace(
        embedding=SimpleNamespace(
            visual=SimpleNamespace(
                provider=provider,
                model=model,
                dim=dim,
                api_key=api_key,
                base_url=base_url,
                batch_size=batch_size,
                timeout_s=timeout_s,
                max_retries=max_retries,
            )
        ),
        pixelrag=SimpleNamespace(embed_instruction="Represent the user's input."),
    )


@pytest.fixture(autouse=True)
def _reset_encoder_cache() -> None:
    ve.reset_visual_encoder_for_tests()
    yield
    ve.reset_visual_encoder_for_tests()


def test_factory_rejects_unknown_provider() -> None:
    with patch.object(ve, "get_settings", return_value=_visual_settings(provider="openai")):
        with pytest.raises(ValueError, match="not supported"):
            ve.get_visual_encoder()


def test_factory_returns_local_for_pixelrag() -> None:
    with patch.object(ve, "get_settings", return_value=_visual_settings(provider="pixelrag")):
        enc = ve.get_visual_encoder()
        assert isinstance(enc, ve.LocalQwen3VLEncoder)


def test_factory_returns_dashscope() -> None:
    with patch.object(ve, "get_settings", return_value=_visual_settings()):
        enc = ve.get_visual_encoder()
        assert isinstance(enc, ve.DashScopeQwen3VLEncoder)


def test_dashscope_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    with patch.object(
        ve,
        "get_settings",
        return_value=_visual_settings(api_key=""),
    ):
        with pytest.raises(ValueError, match="DASHSCOPE_API_KEY"):
            ve.DashScopeQwen3VLEncoder()


def test_dashscope_embed_text_forwards_dimension_and_instruct() -> None:
    settings = _visual_settings()
    fake_emb = [0.0] * 2047 + [1.0]
    resp = SimpleNamespace(
        status_code=HTTPStatus.OK,
        output={"embeddings": [{"index": 0, "embedding": fake_emb, "type": "text"}]},
    )
    mock_call = MagicMock(return_value=resp)
    fake_ds = MagicMock()
    fake_ds.MultiModalEmbedding.call = mock_call

    with (
        patch.object(ve, "get_settings", return_value=settings),
        patch.dict("sys.modules", {"dashscope": fake_ds}),
    ):
        enc = ve.DashScopeQwen3VLEncoder()
        vec = enc.embed_text("tax rate chart")

    assert len(vec) == 2048
    assert abs(sum(x * x for x in vec) ** 0.5 - 1.0) < 1e-6
    kwargs = mock_call.call_args.kwargs
    assert kwargs["model"] == "qwen3-vl-embedding"
    assert kwargs["dimension"] == 2048
    assert kwargs["instruct"] == "Represent the user's input."
    assert kwargs["input"] == [{"text": "tax rate chart"}]
    assert kwargs["api_key"] == "sk-test"


def test_dashscope_embed_images_batches() -> None:
    settings = _visual_settings(batch_size=2)

    def _resp(n: int) -> SimpleNamespace:
        return SimpleNamespace(
            status_code=HTTPStatus.OK,
            output={
                "embeddings": [
                    {"index": i, "embedding": [float(i + 1)] + [0.0] * 2047, "type": "image"}
                    for i in range(n)
                ]
            },
        )

    mock_call = MagicMock(side_effect=[_resp(2), _resp(1)])

    with (
        patch.object(ve, "get_settings", return_value=settings),
        patch.dict("sys.modules", {"dashscope": MagicMock()}),
    ):
        import sys

        sys.modules["dashscope"].MultiModalEmbedding = MagicMock(call=mock_call)
        enc = ve.DashScopeQwen3VLEncoder()
        # Minimal JPEG SOI marker so MIME detects jpeg
        jpeg = b"\xff\xd8\xff" + b"\x00" * 16
        vectors = enc.embed_images([jpeg, jpeg, jpeg])

    assert len(vectors) == 3
    assert mock_call.call_count == 2
    first_batch = mock_call.call_args_list[0].kwargs["input"]
    second_batch = mock_call.call_args_list[1].kwargs["input"]
    assert len(first_batch) == 2
    assert len(second_batch) == 1
    assert first_batch[0]["image"].startswith("data:image/jpeg;base64,")


def test_dashscope_fail_fast_on_error_status() -> None:
    settings = _visual_settings(max_retries=1)
    resp = SimpleNamespace(status_code=400, message="bad request", code="InvalidParameter")
    mock_call = MagicMock(return_value=resp)

    with (
        patch.object(ve, "get_settings", return_value=settings),
        patch.dict("sys.modules", {"dashscope": MagicMock()}),
    ):
        import sys

        sys.modules["dashscope"].MultiModalEmbedding = MagicMock(call=mock_call)
        enc = ve.DashScopeQwen3VLEncoder()
        with pytest.raises(RuntimeError, match="failed status=400"):
            enc.embed_text("hello")


def test_image_data_uri_png() -> None:
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 8
    uri = ve._image_data_uri(png)
    assert uri.startswith("data:image/png;base64,")


def test_embed_tiles_uses_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    from eagle_rag.ingest import pixelrag_adapter as adapter

    class _FakeEnc:
        def embed_images(self, images: list[bytes]) -> list[list[float]]:
            return [[float(i), 1.0] for i, _ in enumerate(images)]

        def embed_text(self, text: str) -> list[float]:
            return [0.0]

        def embed_image(self, image_bytes: bytes) -> list[float]:
            return [1.0]

    monkeypatch.setattr(adapter, "get_visual_encoder", lambda: _FakeEnc())
    tiles = [
        {"image_bytes": b"a", "page": 0, "position": "strip_0"},
        {"image_bytes": b"b", "page": 1, "position": "strip_1"},
    ]
    out = adapter.embed_tiles(tiles)
    assert out[0]["vector"] == [0.0, 1.0]
    assert out[1]["vector"] == [1.0, 1.0]
    assert out[0]["page"] == 0
