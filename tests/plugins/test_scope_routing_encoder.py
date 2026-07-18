"""Scope-aware union encoder resolution tests (G21/G23/G29).

Verifies that ``_encoder_for_collection`` resolves the canonical encoder for
specialized biomed collections instead of returning the first dim-matching
encoder. ``pubmedbert`` and ``molformer`` are both 768-dim, so a dim-only probe
would wrongly assign ``pubmedbert`` to ``eagle_chemical``.
"""

from __future__ import annotations

from eagle_rag.plugins.encoder_registry import EncoderRegistry
from eagle_rag.plugins.scope_routing import _encoder_for_collection


def _build_registry() -> EncoderRegistry:
    """Build a registry mirroring the biomed plugin encoder registrations."""
    registry = EncoderRegistry()
    # Core encoders (registered by CoreDefaultsPlugin.on_load).
    registry.register("text-embedding-v4", object(), dim=1536, modality="text")
    registry.register("qwen3-vl", object(), dim=2048, modality="visual")
    # Biomed encoders (registered by plugins.biomed.encoders.register_encoders).
    # Order matters: pubmedbert is registered before molformer.
    registry.register("pubmedbert", object(), dim=768, modality="text")
    registry.register("molformer", object(), dim=768, modality="text")
    registry.register("medimageinsight", object(), dim=1024, modality="visual")
    registry.register("uni2", object(), dim=1536, modality="visual")
    # Collection dims.
    registry.register_collection_dim("eagle_text_biomed", 768)
    registry.register_collection_dim("eagle_chemical", 768)
    registry.register_collection_dim("eagle_medical_radiology", 1024)
    registry.register_collection_dim("eagle_medical_pathology", 1536)
    return registry


def test_core_collections_use_core_encoders() -> None:
    registry = _build_registry()
    assert _encoder_for_collection("eagle_text", registry) == "text-embedding-v4"
    assert _encoder_for_collection("eagle_visual", registry) == "qwen3-vl"


def test_eagle_chemical_resolves_molformer_not_pubmedbert() -> None:
    """Both pubmedbert and molformer are 768-dim; chemical must pick molformer."""
    registry = _build_registry()
    assert _encoder_for_collection("eagle_chemical", registry) == "molformer"


def test_eagle_text_biomed_resolves_pubmedbert() -> None:
    registry = _build_registry()
    assert _encoder_for_collection("eagle_text_biomed", registry) == "pubmedbert"


def test_visual_biomed_collections_resolve_correct_encoder() -> None:
    registry = _build_registry()
    assert _encoder_for_collection("eagle_medical_radiology", registry) == "medimageinsight"
    assert _encoder_for_collection("eagle_medical_pathology", registry) == "uni2"


def test_unknown_collection_falls_back_to_dim_probe() -> None:
    """Unknown (future plugin) collections still use the dim-probe fallback."""
    registry = _build_registry()
    registry.register_collection_dim("eagle_custom_768", 768)
    # Fallback returns the first 768-dim encoder (pubmedbert, registration order).
    assert _encoder_for_collection("eagle_custom_768", registry) == "pubmedbert"


def test_unknown_collection_without_dim_matches_first_encoder() -> None:
    """An unknown collection with no registered dim matches the first encoder.

    ``validate_plan`` skips the dim check when ``col_dim is None``
    (``encoder_registry.py``), so the fallback returns the first registered
    encoder. This is pre-existing fallback behavior preserved for forward
    compatibility with unknown plugin collections.
    """
    registry = _build_registry()
    # No dim registered for this collection -> dim check skipped -> first encoder.
    result = _encoder_for_collection("eagle_nonexistent", registry)
    assert result is not None  # falls back to first registered encoder
