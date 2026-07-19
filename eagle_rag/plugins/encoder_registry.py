"""Encoder registry for multi-collection ingest and retrieve."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

__all__ = ["EncoderInfo", "EncoderRegistry"]


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


class EncoderRegistry:
    """Maps encoder name to instance; validates dim against collections."""

    def __init__(self) -> None:
        self._encoders: dict[str, EncoderInfo] = {}
        self._collection_dims: dict[str, int] = {}

    def register(
        self,
        name: str,
        encoder: Any,
        *,
        dim: int,
        modality: str = "text",
    ) -> None:
        self._encoders[name] = EncoderInfo(name=name, dim=dim, encoder=encoder, modality=modality)

    def register_collection_dim(self, collection: str, dim: int) -> None:
        self._collection_dims[collection] = dim

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
