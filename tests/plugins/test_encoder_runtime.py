"""Encoder runtime unit tests."""

from __future__ import annotations

from eagle_rag.plugins.encoder_runtime import deterministic_text_embedding, l2_normalize


def test_deterministic_embedding_dim_and_normalized() -> None:
    vec = deterministic_text_embedding("BRCA1 mutation", 768)
    assert len(vec) == 768
    norm = sum(x * x for x in vec) ** 0.5
    assert abs(norm - 1.0) < 1e-6


def test_l2_normalize() -> None:
    assert l2_normalize([3.0, 4.0]) == [0.6, 0.8]
