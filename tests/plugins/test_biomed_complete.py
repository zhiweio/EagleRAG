"""Tests for biomed UMLS index and encoder no-Qwen medical fallback."""

from __future__ import annotations

import os

import pytest

from plugins.biomed.encoders import EncoderLoadError, LazyDomainEncoder
from plugins.biomed.umls import expand_query_with_entities, match_entities, resolve_entity


def test_umls_match_her2_aliases() -> None:
    hits = match_entities("Patient overexpresses ERBB2 / HER-2")
    assert "HER2" in hits


def test_resolve_entity_pathways() -> None:
    meta = resolve_entity("HER2")
    assert meta["found"] is True
    assert "trastuzumab" in meta["related_drugs"]
    assert meta["cui"]


def test_expand_query_returns_suffix() -> None:
    suffix = expand_query_with_entities("EGFR mutation in NSCLC")
    assert suffix is not None
    assert "biomed entities" in suffix


def test_medical_encoder_never_uses_qwen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EAGLE_BIOMED_ENCODER_MODE", "deterministic")
    enc = LazyDomainEncoder("medimageinsight", 1024, modality="visual")
    vec = enc.encode_image(b"\x89PNG\r\nfake")
    assert len(vec) == 1024


def test_require_native_fails_without_weights(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EAGLE_BIOMED_ENCODER_MODE", "require_native")
    monkeypatch.delenv("EAGLE_BIOMED_ALLOW_DETERMINISTIC", raising=False)
    enc = LazyDomainEncoder(
        "medimageinsight",
        1024,
        modality="visual",
        hf_model_id="definitely-not-a-real-model/xxx",
    )

    def _boom() -> None:
        raise RuntimeError("no weights")

    monkeypatch.setattr(enc, "_load_vision_backend", _boom)
    with pytest.raises(EncoderLoadError):
        enc.encode_image(b"abc")


def test_profile_env_merges_biomed(monkeypatch: pytest.MonkeyPatch) -> None:
    from eagle_rag import config as config_mod

    monkeypatch.setenv("EAGLE_RAG_PROFILE", "biomed")
    monkeypatch.setenv("EAGLE_BIOMED_ENCODER_MODE", "deterministic")
    config_mod.get_settings.cache_clear()
    try:
        settings = config_mod.get_settings()
        assert settings.active_profile == "biomed"
        assert settings.plugins.default_namespace == "biomed"
        assert "plugins.biomed" in settings.plugins.enabled
        assert settings.milvus.db_name == "biomed"
    finally:
        monkeypatch.delenv("EAGLE_RAG_PROFILE", raising=False)
        config_mod.get_settings.cache_clear()
