"""Encoder registry for multi-collection ingest and retrieve."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

__all__ = ["CollectionProfile", "EncoderInfo", "EncoderRegistry"]


class VectorEncoder(Protocol):
    """Minimal encoder interface for dimension validation and encoding."""

    @property
    def dim(self) -> int: ...

    def encode_text(self, text: str) -> list[float]: ...

    def encode_texts(self, texts: list[str]) -> list[list[float]]: ...


@dataclass(frozen=True)
class EncoderInfo:
    """Registered encoder metadata."""

    name: str
    dim: int
    encoder: Any
    modality: str = "text"


@dataclass(frozen=True)
class CollectionProfile:
    """Per-collection metadata registered by plugins (Core or domain)."""

    dim: int
    default_encoder: str | None = None
    hybrid_enabled: bool = False
    extra_output_fields: tuple[str, ...] = ()


class EncoderRegistry:
    """Maps encoder name to instance; validates dim against collections."""

    def __init__(self) -> None:
        self._encoders: dict[str, EncoderInfo] = {}
        self._collection_dims: dict[str, int] = {}
        self._collection_profiles: dict[str, CollectionProfile] = {}

    def register(
        self,
        name: str,
        encoder: Any,
        *,
        dim: int,
        modality: str = "text",
    ) -> None:
        self._encoders[name] = EncoderInfo(name=name, dim=dim, encoder=encoder, modality=modality)

    def register_collection(
        self,
        collection: str,
        *,
        dim: int,
        default_encoder: str | None = None,
        hybrid_enabled: bool = False,
        extra_output_fields: tuple[str, ...] = (),
    ) -> None:
        """Register collection dim, default encoder, hybrid flag, and optional output fields."""
        self._collection_dims[collection] = dim
        self._collection_profiles[collection] = CollectionProfile(
            dim=dim,
            default_encoder=default_encoder,
            hybrid_enabled=hybrid_enabled,
            extra_output_fields=extra_output_fields,
        )

    def register_collection_dim(self, collection: str, dim: int) -> None:
        """Backward-compatible dim-only registration."""
        self.register_collection(collection, dim=dim)

    def collection_profile(self, collection: str) -> CollectionProfile | None:
        return self._collection_profiles.get(collection)

    def default_encoder_for_collection(self, collection: str) -> str | None:
        profile = self._collection_profiles.get(collection)
        return profile.default_encoder if profile else None

    def hybrid_enabled_for_collection(self, collection: str) -> bool:
        profile = self._collection_profiles.get(collection)
        return bool(profile and profile.hybrid_enabled)

    def extra_output_fields_for_collection(self, collection: str) -> tuple[str, ...]:
        profile = self._collection_profiles.get(collection)
        return profile.extra_output_fields if profile else ()

    def get(self, name: str) -> EncoderInfo:
        if name not in self._encoders:
            raise KeyError(f"encoder not registered: {name}")
        return self._encoders[name]

    def has(self, name: str) -> bool:
        return name in self._encoders

    def names(self) -> list[str]:
        return list(self._encoders.keys())

    def collection_dim(self, collection: str) -> int | None:
        return self._collection_dims.get(collection)

    def validate_plan(self, collection: str, encoder_name: str) -> None:
        enc = self.get(encoder_name)
        if enc.modality == "rerank":
            return
        col_dim = self._collection_dims.get(collection)
        if col_dim is not None and enc.dim != col_dim:
            msg = f"encoder {encoder_name} dim {enc.dim} != collection {collection} dim {col_dim}"
            raise ValueError(msg)
