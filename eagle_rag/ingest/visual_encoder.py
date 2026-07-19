"""Core visual embedding backends (local HF Qwen3-VL ↔ Bailian DashScope).

Callers should use :func:`get_visual_encoder` (or the thin wrappers in
``pixelrag_adapter``). Ingest and query must share the same
``embedding.visual.provider``; switching backends requires rebuilding
``eagle_visual`` so vectors stay in one space.
"""

from __future__ import annotations

import base64
import io
import math
import os
import threading
import time
from http import HTTPStatus
from typing import Any, Protocol, runtime_checkable

from eagle_rag.config import get_settings
from eagle_rag.telemetry import get_logger

__all__ = [
    "VisualEncoder",
    "LocalQwen3VLEncoder",
    "DashScopeQwen3VLEncoder",
    "get_visual_encoder",
    "reset_visual_encoder_for_tests",
]

logger = get_logger(__name__)

_SUPPORTED_PROVIDERS = frozenset({"pixelrag", "dashscope"})
_DASHSCOPE_DIMS = frozenset({256, 512, 768, 1024, 1536, 2048, 2560})

# Qwen3-VL patch alignment and render viewport width (aligned with pixelrag_embed)
_RESIZE_FACTOR = 28
_MAX_CHUNK_WIDTH = 875

_factory_lock = threading.Lock()
_cached: tuple[str, str, VisualEncoder] | None = None


@runtime_checkable
class VisualEncoder(Protocol):
    """Shared image/text embedding space for Core ``eagle_visual``."""

    def embed_image(self, image_bytes: bytes) -> list[float]: ...

    def embed_text(self, text: str) -> list[float]: ...

    def embed_images(self, images: list[bytes]) -> list[list[float]]: ...


def _l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm <= 0.0:
        return vec
    return [x / norm for x in vec]


def _image_mime(image_bytes: bytes) -> str:
    if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if len(image_bytes) >= 12 and image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
        return "webp"
    if image_bytes[:2] == b"\xff\xd8":
        return "jpeg"
    if image_bytes[:3] == b"GIF":
        return "gif"
    if image_bytes[:2] in (b"BM",):
        return "bmp"
    return "jpeg"


def _image_data_uri(image_bytes: bytes) -> str:
    fmt = _image_mime(image_bytes)
    b64 = base64.b64encode(image_bytes).decode("ascii")
    return f"data:image/{fmt};base64,{b64}"


def _resolve_device(device: str) -> str:
    """Resolve a device string; ``auto`` probes cuda → mps → cpu."""
    import platform

    import torch

    if device != "auto":
        return device
    if torch.cuda.is_available():
        resolved = "cuda"
    elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        resolved = "mps"
    else:
        resolved = "cpu"
    logger.info(
        "PIXELRAG embed_device auto → %s (platform=%s/%s, torch=%s)",
        resolved,
        platform.system(),
        platform.machine(),
        torch.__version__,
    )
    if (
        resolved == "cpu"
        and platform.system() == "Linux"
        and platform.machine() in ("aarch64", "arm64")
    ):
        logger.info(
            "ARM Linux container has no MPS/CUDA; visual encoding uses CPU. "
            "On Apple Silicon, run API/worker-pixelrag natively with `uv run` for MPS."
        )
    return resolved


def _clamp_width(img: Any, max_width: int = _MAX_CHUNK_WIDTH) -> Any:
    """Downscale proportionally when width > ``max_width`` (28px-aligned)."""
    from PIL import Image

    w, h = img.size
    if w <= max_width:
        return img
    scale = max_width / w
    new_w = max(round(w * scale / _RESIZE_FACTOR) * _RESIZE_FACTOR, _RESIZE_FACTOR)
    new_h = max(round(h * scale / _RESIZE_FACTOR) * _RESIZE_FACTOR, _RESIZE_FACTOR)
    return img.resize((new_w, new_h), Image.LANCZOS)


class LocalQwen3VLEncoder:
    """Local Hugging Face Qwen3-VL-Embedding singleton (last-token pool + L2)."""

    def __init__(self) -> None:
        self._model: Any = None
        self._processor: Any = None
        self._device: str | None = None
        self._torch: Any = None
        self._load_lock = threading.Lock()

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        with self._load_lock:
            if self._model is not None:
                return
            import torch
            from transformers import AutoProcessor, Qwen3VLForConditionalGeneration

            settings = get_settings()
            model_name = settings.embedding.visual.model
            device = _resolve_device(settings.pixelrag.embed_device)
            dtype = torch.float32 if device == "cpu" else torch.float16
            logger.info("loading visual encoder model %s on %s (%s)", model_name, device, dtype)
            os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "120")
            self._processor = AutoProcessor.from_pretrained(model_name, trust_remote_code=True)
            self._model = Qwen3VLForConditionalGeneration.from_pretrained(
                model_name,
                trust_remote_code=True,
                dtype=dtype,
                attn_implementation="sdpa",
            ).eval()
            if device != "cpu":
                self._model = self._model.to(device)
            self._device = device
            self._torch = torch

    def _to_device(self, inputs: dict) -> dict:
        if self._device == "cpu":
            return inputs
        return {k: v.to(self._device) if hasattr(v, "to") else v for k, v in inputs.items()}

    def _pool(self, outputs: Any, inputs: dict) -> list[float]:
        torch = self._torch
        last_hidden = outputs.hidden_states[-1]
        seq_lens = inputs["attention_mask"].sum(dim=1)
        last_idx = seq_lens - 1
        pooled = last_hidden[0, last_idx[0]]
        pooled = torch.nn.functional.normalize(pooled, p=2, dim=-1)
        return pooled.cpu().float().numpy().tolist()

    def embed_image(self, image_bytes: bytes) -> list[float]:
        from PIL import Image

        self._ensure_loaded()
        torch = self._torch
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img = _clamp_width(img)
        instruction = get_settings().pixelrag.embed_instruction
        messages = [
            {"role": "system", "content": [{"type": "text", "text": instruction}]},
            {"role": "user", "content": [{"type": "image", "image": img}]},
        ]
        text = self._processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self._processor(text=[text], images=[img], return_tensors="pt", padding=True)
        inputs = self._to_device(inputs)
        with torch.no_grad():
            outputs = self._model(**inputs, output_hidden_states=True)
        return self._pool(outputs, inputs)

    def embed_text(self, text: str) -> list[float]:
        self._ensure_loaded()
        torch = self._torch
        instruction = get_settings().pixelrag.embed_instruction
        messages = [
            {"role": "system", "content": [{"type": "text", "text": instruction}]},
            {"role": "user", "content": [{"type": "text", "text": text}]},
        ]
        prompt = self._processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        inputs = self._processor(text=[prompt], return_tensors="pt", padding=True)
        inputs = self._to_device(inputs)
        with torch.no_grad():
            outputs = self._model(**inputs, output_hidden_states=True)
        return self._pool(outputs, inputs)

    def embed_images(self, images: list[bytes]) -> list[list[float]]:
        return [self.embed_image(img) for img in images]


class DashScopeQwen3VLEncoder:
    """Bailian ``qwen3-vl-embedding`` via ``dashscope.MultiModalEmbedding``."""

    def __init__(self) -> None:
        settings = get_settings().embedding.visual
        self._model = settings.model
        self._dim = settings.dim
        self._api_key = settings.api_key or os.environ.get("DASHSCOPE_API_KEY", "")
        self._base_url = settings.base_url.strip()
        self._batch_size = max(1, min(settings.batch_size, 10))
        self._max_retries = max(1, settings.max_retries)
        self._timeout_s = settings.timeout_s
        if not self._api_key:
            raise ValueError(
                "embedding.visual.provider='dashscope' requires DASHSCOPE_API_KEY "
                "(or embedding.visual.api_key)."
            )
        if self._dim not in _DASHSCOPE_DIMS:
            raise ValueError(
                f"embedding.visual.dim={self._dim} is not supported by qwen3-vl-embedding; "
                f"allowed: {sorted(_DASHSCOPE_DIMS)}"
            )

    def _call(self, contents: list[dict[str, str]]) -> list[list[float]]:
        import dashscope

        if self._base_url:
            dashscope.base_http_api_url = self._base_url.rstrip("/")

        instruct = get_settings().pixelrag.embed_instruction
        last_err: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                resp = dashscope.MultiModalEmbedding.call(
                    model=self._model,
                    input=contents,
                    api_key=self._api_key,
                    dimension=self._dim,
                    instruct=instruct,
                )
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                logger.warning(
                    "DashScope MultiModalEmbedding attempt %s/%s failed: %s",
                    attempt + 1,
                    self._max_retries,
                    exc,
                )
                if attempt + 1 < self._max_retries:
                    time.sleep(min(2**attempt, 8))
                continue

            status = getattr(resp, "status_code", None)
            if status == HTTPStatus.OK:
                return self._parse_embeddings(resp, expected=len(contents))

            # Retry transient rate-limit / server errors.
            retryable = {
                HTTPStatus.TOO_MANY_REQUESTS,
                HTTPStatus.INTERNAL_SERVER_ERROR,
                HTTPStatus.BAD_GATEWAY,
                HTTPStatus.SERVICE_UNAVAILABLE,
                HTTPStatus.GATEWAY_TIMEOUT,
            }
            if status in retryable:
                last_err = RuntimeError(f"DashScope MultiModalEmbedding status={status}: {resp}")
                logger.warning(
                    "DashScope MultiModalEmbedding attempt %s/%s status=%s",
                    attempt + 1,
                    self._max_retries,
                    status,
                )
                if attempt + 1 < self._max_retries:
                    time.sleep(min(2**attempt, 8))
                continue

            raise RuntimeError(f"DashScope MultiModalEmbedding failed status={status}: {resp}")

        raise RuntimeError(
            f"DashScope MultiModalEmbedding exhausted retries: {last_err}"
        ) from last_err

    def _parse_embeddings(self, resp: Any, *, expected: int) -> list[list[float]]:
        output = getattr(resp, "output", None) or {}
        if isinstance(output, dict):
            raw = output.get("embeddings") or []
        else:
            raw = getattr(output, "embeddings", None) or []

        by_index: dict[int, list[float]] = {}
        for item in raw:
            if isinstance(item, dict):
                idx = int(item.get("index", len(by_index)))
                emb = item.get("embedding")
            else:
                idx = int(getattr(item, "index", len(by_index)))
                emb = getattr(item, "embedding", None)
            if emb is None:
                raise RuntimeError(f"DashScope embedding missing at index={idx}")
            vec = list(emb)
            if len(vec) != self._dim:
                raise RuntimeError(
                    f"DashScope embedding dim={len(vec)} != configured dim={self._dim}"
                )
            by_index[idx] = _l2_normalize(vec)

        missing = [i for i in range(expected) if i not in by_index]
        if missing:
            raise RuntimeError(f"DashScope embedding response missing indices: {missing}")
        return [by_index[i] for i in range(expected)]

    def embed_image(self, image_bytes: bytes) -> list[float]:
        return self._call([{"image": _image_data_uri(image_bytes)}])[0]

    def embed_text(self, text: str) -> list[float]:
        return self._call([{"text": text}])[0]

    def embed_images(self, images: list[bytes]) -> list[list[float]]:
        if not images:
            return []
        out: list[list[float]] = []
        for start in range(0, len(images), self._batch_size):
            chunk = images[start : start + self._batch_size]
            contents = [{"image": _image_data_uri(img)} for img in chunk]
            out.extend(self._call(contents))
        return out


def get_visual_encoder() -> VisualEncoder:
    """Return the process-local visual encoder for ``embedding.visual.provider``."""
    global _cached
    settings = get_settings().embedding.visual
    provider = (settings.provider or "").strip().lower()
    model = settings.model
    if provider not in _SUPPORTED_PROVIDERS:
        raise ValueError(
            f"embedding.visual.provider={settings.provider!r} is not supported. "
            "Use 'pixelrag' (local Hugging Face Qwen3-VL-Embedding) or "
            "'dashscope' (Bailian qwen3-vl-embedding). "
            "Ingest and query must use the same provider; switching requires "
            "rebuilding the eagle_visual collection."
        )

    with _factory_lock:
        if _cached is not None and _cached[0] == provider and _cached[1] == model:
            return _cached[2]
        if provider == "dashscope":
            encoder: VisualEncoder = DashScopeQwen3VLEncoder()
        else:
            encoder = LocalQwen3VLEncoder()
        _cached = (provider, model, encoder)
        logger.info(
            "visual encoder ready provider=%s model=%s dim=%s",
            provider,
            model,
            settings.dim,
        )
        return encoder


def reset_visual_encoder_for_tests() -> None:
    """Clear the process-local encoder cache (tests only)."""
    global _cached
    with _factory_lock:
        _cached = None
