"""Shared encoder dispatch via EncoderRegistry (G22)."""

from __future__ import annotations

import math

__all__ = [
    "encode_text_for_encoder",
    "encode_text_chunk",
    "encode_visual_bytes_for_encoder",
]


def encode_text_for_encoder(encoder_name: str, text: str) -> list[float]:
    """Encode query/document text with a registered encoder."""
    from eagle_rag.plugins import get_plugin_manager

    info = get_plugin_manager().encoder_registry.get(encoder_name)
    encoder = info.encoder
    if hasattr(encoder, "encode_text"):
        return list(encoder.encode_text(text))
    if encoder_name == "text-embedding-v4":
        from eagle_rag.index.milvus_text_store import _build_embed_model

        return _build_embed_model().get_text_embedding(text)
    msg = f"encoder {encoder_name!r} has no encode_text implementation"
    raise ValueError(msg)


def encode_text_chunk(chunk: object, encoder_name: str) -> object:
    """Return a TextNode (or chunk) with ``metadata['embedding']`` set."""
    from llama_index.core.schema import TextNode

    if isinstance(chunk, TextNode):
        node = chunk
        text = node.get_content()
    elif isinstance(chunk, dict):
        text = str(chunk.get("text") or chunk.get("content") or "")
        node = TextNode(text=text, metadata=dict(chunk.get("metadata") or {}))
    else:
        text = str(chunk)
        node = TextNode(text=text)

    vector = encode_text_for_encoder(encoder_name, text)
    meta = dict(node.metadata or {})
    meta["embedding"] = vector
    meta["target_encoder"] = encoder_name
    node.metadata = meta
    return node


def encode_visual_bytes_for_encoder(encoder_name: str, image_bytes: bytes) -> list[float]:
    from eagle_rag.plugins import get_plugin_manager

    info = get_plugin_manager().encoder_registry.get(encoder_name)
    encoder = info.encoder
    if hasattr(encoder, "encode_image"):
        return list(encoder.encode_image(image_bytes))
    if hasattr(encoder, "encode_visual"):
        return list(encoder.encode_visual(image_bytes))
    if encoder_name == "qwen3-vl":
        from eagle_rag.ingest.pixelrag_adapter import embed_image_bytes

        return embed_image_bytes(image_bytes)
    msg = f"encoder {encoder_name!r} has no visual encode implementation"
    raise ValueError(msg)


def l2_normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norm for x in vector]


def deterministic_text_embedding(text: str, dim: int) -> list[float]:
    """Deterministic fallback embedding for tests when domain models are absent."""
    import hashlib

    digest = hashlib.sha256(text.encode("utf-8")).digest()
    vec = [((digest[i % len(digest)] / 255.0) * 2.0 - 1.0) for i in range(dim)]
    return l2_normalize(vec)
