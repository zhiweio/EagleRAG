"""BiomedCLIP / open_clip loading and text-tower query encoding (no Qwen)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
import torch

from plugins.biomed.encoders import (
    LazyDomainEncoder,
    _open_clip_model_ref,
    _prefer_open_clip,
)


def test_open_clip_model_ref_prefixes_hf_hub() -> None:
    assert (
        _open_clip_model_ref("microsoft/BiomedCLIP-PubMedBERT_256-vit_base_patch16_224")
        == "hf-hub:microsoft/BiomedCLIP-PubMedBERT_256-vit_base_patch16_224"
    )
    assert _open_clip_model_ref("hf-hub:microsoft/BiomedCLIP-x") == "hf-hub:microsoft/BiomedCLIP-x"
    assert _open_clip_model_ref("ViT-B-32") == "ViT-B-32"
    assert _open_clip_model_ref("/tmp/weights.bin") == "/tmp/weights.bin"


def test_prefer_open_clip_for_medimageinsight() -> None:
    assert _prefer_open_clip("medimageinsight", "microsoft/BiomedCLIP-x")
    assert not _prefer_open_clip("uni2", "MahmoodLab/UNI2-h")


def test_visual_encode_text_uses_open_clip_text_tower(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EAGLE_BIOMED_ENCODER_MODE", "auto")
    monkeypatch.delenv("EAGLE_BIOMED_ALLOW_DETERMINISTIC", raising=False)

    enc = LazyDomainEncoder("medimageinsight", 1024, modality="visual")
    fake_feats = torch.ones(1, 512)

    class _Tok:
        def __call__(self, texts: list[str]) -> torch.Tensor:
            assert texts == ["right lower lobe ground-glass opacity"]
            return torch.zeros(1, 8, dtype=torch.long)

    class _Model:
        def encode_text(self, tokens: torch.Tensor) -> torch.Tensor:
            assert tokens.shape[0] == 1
            return fake_feats.clone()

        def encode_image(self, tensor: torch.Tensor) -> torch.Tensor:
            return fake_feats.clone()

        def eval(self) -> _Model:
            return self

    enc._backend = {
        "kind": "open_clip",
        "model": _Model(),
        "preprocess": lambda img: torch.zeros(3, 224, 224),
        "tokenizer": _Tok(),
        "torch": torch,
        "Image": MagicMock(),
    }
    enc._backend_kind = "open_clip"

    vec = enc.encode_text("right lower lobe ground-glass opacity")
    assert len(vec) == 1024
    # Leading dims come from the 512-d CLIP vector (padded to collection dim).
    assert all(abs(x - 1.0 / (512**0.5)) < 1e-5 for x in vec[:512])
    assert all(x == 0.0 for x in vec[512:])


def test_visual_encode_text_rejects_hf_vision_without_text_tower(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EAGLE_BIOMED_ENCODER_MODE", "require_native")
    monkeypatch.delenv("EAGLE_BIOMED_ALLOW_DETERMINISTIC", raising=False)

    enc = LazyDomainEncoder("uni2", 1536, modality="visual")
    enc._backend = {
        "kind": "hf_vision",
        "model": object(),
        "processor": object(),
        "torch": torch,
        "Image": MagicMock(),
    }
    enc._backend_kind = "hf_vision"

    from plugins.biomed.encoders import EncoderLoadError

    with pytest.raises(EncoderLoadError, match="no CLIP text tower"):
        enc.encode_text("HE stained slide")


def test_load_open_clip_uses_hf_hub_create_model_from_pretrained(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict[str, Any] = {}

    fake_model = MagicMock()
    fake_model.eval.return_value = fake_model
    fake_preprocess = object()
    fake_tokenizer = object()

    class _FakeOpenClip:
        @staticmethod
        def create_model_from_pretrained(ref: str) -> tuple[Any, Any]:
            calls["ref"] = ref
            return fake_model, fake_preprocess

        @staticmethod
        def get_tokenizer(ref: str) -> Any:
            calls["tokenizer_ref"] = ref
            return fake_tokenizer

    monkeypatch.setitem(__import__("sys").modules, "open_clip", _FakeOpenClip)
    monkeypatch.setitem(
        __import__("sys").modules,
        "PIL",
        SimpleNamespace(Image=MagicMock()),
    )
    monkeypatch.setitem(
        __import__("sys").modules,
        "PIL.Image",
        MagicMock(),
    )

    enc = LazyDomainEncoder(
        "medimageinsight",
        1024,
        modality="visual",
        hf_model_id="microsoft/BiomedCLIP-PubMedBERT_256-vit_base_patch16_224",
    )
    backend = enc._load_open_clip_backend(enc.hf_model_id or "")
    assert backend["kind"] == "open_clip"
    assert calls["ref"] == ("hf-hub:microsoft/BiomedCLIP-PubMedBERT_256-vit_base_patch16_224")
    assert calls["tokenizer_ref"] == calls["ref"]
    assert backend["tokenizer"] is fake_tokenizer


def test_orchestrator_encodes_visual_query_via_clip_text_tower(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from eagle_rag.plugins.encoder_registry import EncoderInfo, EncoderRegistry
    from eagle_rag.plugins.retriever_orchestrator import RetrieverOrchestrator

    enc = LazyDomainEncoder("medimageinsight", 1024, modality="visual")
    monkeypatch.setenv("EAGLE_BIOMED_ENCODER_MODE", "deterministic")
    registry = EncoderRegistry()
    registry.register(
        "medimageinsight",
        enc,
        dim=1024,
        modality="visual",
    )

    class _Mgr:
        encoder_registry = registry

    orch = RetrieverOrchestrator(plugin_manager=_Mgr())  # type: ignore[arg-type]
    vec = orch._encode_query(
        "medimageinsight",
        "pulmonary nodule on CT",
        query_image_bytes=None,
    )
    assert len(vec) == 1024
    # Registry metadata used by image-query branch.
    info = registry.get("medimageinsight")
    assert isinstance(info, EncoderInfo)
    assert info.modality == "visual"
