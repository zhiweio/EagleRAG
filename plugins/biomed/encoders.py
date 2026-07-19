"""Biomed domain encoders with lazy model loading (no Qwen3-VL medical fallback).

Medical imaging encoders (MedImageInsight / UNI 2) **never** call Core
``embed_image_bytes`` (Qwen3-VL). Modes:

- ``deterministic`` — CI / unit tests only (hash embedding).
- ``require_native`` — fail-fast if HF/local weights cannot load.
- ``auto`` (default) — try native weights; if unavailable and
  ``EAGLE_BIOMED_ALLOW_DETERMINISTIC=1``, fall back to deterministic;
  otherwise raise.

``medimageinsight`` prefers ``open_clip`` with HuggingFace Hub refs
(``hf-hub:microsoft/BiomedCLIP-...``) so both ``encode_image`` and the
CLIP text tower (``encode_text``) share one embedding space for
text→radiology retrieval. Core ``eagle_visual`` / Qwen is untouched.
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass
from typing import Any

from eagle_rag.plugins.context import PluginContext
from eagle_rag.plugins.encoder_runtime import deterministic_text_embedding, l2_normalize

__all__ = [
    "COLLECTION_DIMS",
    "ENCODER_DIMS",
    "LazyDomainEncoder",
    "register_encoders",
]

ENCODER_DIMS: dict[str, int] = {
    "pubmedbert": 768,
    "molformer": 768,
    "medcpt-query": 768,
    "medcpt-article": 768,
    "medimageinsight": 1024,
    "uni2": 1536,
}

_TEXT_EXTRA_OUTPUT_FIELDS = ("primary_drugs", "biomed_section")

_COLLECTION_ENCODERS: dict[str, str] = {
    "eagle_text_biomed": "pubmedbert",
    "eagle_text_medcpt": "medcpt-query",
    "eagle_chemical": "molformer",
    "eagle_medical_radiology": "medimageinsight",
    "eagle_medical_pathology": "uni2",
}

COLLECTION_DIMS: dict[str, int] = {
    "eagle_text_biomed": ENCODER_DIMS["pubmedbert"],
    "eagle_text_medcpt": ENCODER_DIMS["medcpt-article"],
    "eagle_chemical": ENCODER_DIMS["molformer"],
    "eagle_medical_radiology": ENCODER_DIMS["medimageinsight"],
    "eagle_medical_pathology": ENCODER_DIMS["uni2"],
}

_DEFAULT_HF_MODELS: dict[str, str] = {
    "pubmedbert": "microsoft/BiomedNLP-PubMedBERT-base-uncased-abstract-fulltext",
    "molformer": "seyonec/ChemBERTa-zinc-base-v1",
    "medcpt-rerank": "ncbi/MedCPT-Cross-Encoder",
    "medcpt-query": "ncbi/MedCPT-Query-Encoder",
    "medcpt-article": "ncbi/MedCPT-Article-Encoder",
    # Public HF stand-in for MedImageInsight; override via EAGLE_BIOMED_MEDIMAGE_MODEL.
    "medimageinsight": "microsoft/BiomedCLIP-PubMedBERT_256-vit_base_patch16_224",
    "uni2": "MahmoodLab/UNI2-h",
}


def _encoder_mode() -> str:
    env = os.environ.get("EAGLE_BIOMED_ENCODER_MODE", "").strip().lower()
    if env:
        return env
    try:
        from eagle_rag.config import get_settings, plugin_options

        opts = plugin_options("biomed", get_settings())
        return str(opts.get("encoder_mode") or "auto").strip().lower()
    except Exception:  # noqa: BLE001
        return "auto"


def _allow_deterministic() -> bool:
    return os.environ.get("EAGLE_BIOMED_ALLOW_DETERMINISTIC", "").strip() in {
        "1",
        "true",
        "TRUE",
        "yes",
    }


def _model_id_for(name: str) -> str:
    env_map = {
        "pubmedbert": "EAGLE_BIOMED_PUBMEDBERT_MODEL",
        "molformer": "EAGLE_BIOMED_MOLFORMER_MODEL",
        "medimageinsight": "EAGLE_BIOMED_MEDIMAGE_MODEL",
        "uni2": "EAGLE_BIOMED_UNI2_MODEL",
        "medcpt-rerank": "EAGLE_BIOMED_MEDCPT_RERANK_MODEL",
        "medcpt-query": "EAGLE_BIOMED_MEDCPT_QUERY_MODEL",
        "medcpt-article": "EAGLE_BIOMED_MEDCPT_ARTICLE_MODEL",
    }
    return os.environ.get(env_map[name], _DEFAULT_HF_MODELS.get(name, "")).strip()


def _open_clip_model_ref(model_id: str) -> str:
    """Normalize a model id for open_clip (HF hub or native name)."""
    ref = model_id.strip()
    if not ref:
        return ref
    if ref.startswith("hf-hub:"):
        return ref
    # Local open_clip checkpoint (.bin) or native name (ViT-B-32) — leave as-is.
    if ref.endswith(".bin") or "/" not in ref:
        return ref
    return f"hf-hub:{ref}"


def _prefer_open_clip(name: str, model_id: str) -> bool:
    """BiomedCLIP / CLIP-family checkpoints load via open_clip; UNI stays on HF."""
    if name == "medimageinsight":
        return True
    lowered = model_id.lower()
    return "biomedclip" in lowered or "clip" in lowered


class EncoderLoadError(RuntimeError):
    """Raised when a domain encoder cannot load native weights."""


@dataclass
class LazyDomainEncoder:
    """Lazy-load HuggingFace / open_clip encoders; never routes medical images through Qwen3-VL."""

    name: str
    dim: int
    modality: str = "text"
    hf_model_id: str | None = None
    _backend: Any = None
    _backend_kind: str | None = None

    def _fit_dim(self, pooled: list[float]) -> list[float]:
        if len(pooled) > self.dim:
            pooled = pooled[: self.dim]
        elif len(pooled) < self.dim:
            pooled = pooled + [0.0] * (self.dim - len(pooled))
        return l2_normalize([float(x) for x in pooled])

    def _resolve_mode_vector(self, seed: str) -> list[float]:
        mode = _encoder_mode()
        if mode == "deterministic":
            return deterministic_text_embedding(seed, self.dim)
        if mode == "require_native":
            raise EncoderLoadError(
                f"encoder {self.name!r} require_native but native encode failed "
                f"(model_id={self.hf_model_id or _model_id_for(self.name)!r})"
            )
        # auto
        if _allow_deterministic():
            return deterministic_text_embedding(seed, self.dim)
        raise EncoderLoadError(
            f"encoder {self.name!r} native weights unavailable; set "
            "EAGLE_BIOMED_ALLOW_DETERMINISTIC=1 for CI, or configure model path / "
            "EAGLE_BIOMED_ENCODER_MODE=deterministic"
        )

    def _load_hf_text(self) -> Any:
        import torch
        from transformers import AutoModel, AutoTokenizer

        model_id = self.hf_model_id or _model_id_for(self.name)
        if not model_id:
            raise EncoderLoadError(f"no HF model configured for encoder {self.name!r}")
        tokenizer = AutoTokenizer.from_pretrained(model_id)
        model = AutoModel.from_pretrained(model_id)
        model.eval()
        return tokenizer, model, torch

    def _encode_hf_text(self, text: str) -> list[float]:
        tokenizer, model, torch = self._backend
        inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
        with torch.no_grad():
            outputs = model(**inputs)
        hidden = outputs.last_hidden_state
        mask = inputs["attention_mask"].unsqueeze(-1).float()
        summed = (hidden * mask).sum(dim=1)
        counts = mask.sum(dim=1).clamp(min=1e-9)
        pooled = (summed / counts).squeeze(0).tolist()
        return self._fit_dim(pooled)

    def encode_text(self, text: str) -> list[float]:
        """Encode text.

        For ``modality="text"`` this is a text-only encoder (PubMedBERT / MolFormer).
        For ``modality="visual"`` this is the CLIP **text tower** used for
        text→image ANN against specialized medical collections (not Qwen).
        """
        if self.modality == "visual":
            return self._encode_clip_text_query(text)
        if self.modality != "text":
            msg = f"encoder {self.name!r} does not support encode_text"
            raise ValueError(msg)
        if _encoder_mode() == "deterministic":
            return deterministic_text_embedding(text, self.dim)
        try:
            if self._backend is None:
                self._backend = self._load_hf_text()
                self._backend_kind = "hf_text"
            return self._encode_hf_text(text)
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, EncoderLoadError):
                raise
            try:
                return self._resolve_mode_vector(text)
            except EncoderLoadError:
                raise EncoderLoadError(
                    f"encoder {self.name!r} failed to load/encode: {exc}"
                ) from exc

    def encode_texts(self, texts: list[str]) -> list[list[float]]:
        return [self.encode_text(t) for t in texts]

    def _load_open_clip_backend(self, model_id: str) -> dict[str, Any]:
        """Load BiomedCLIP-style weights via open_clip (image + text towers)."""
        import open_clip
        import torch
        from PIL import Image

        ref = _open_clip_model_ref(model_id)
        if not ref:
            raise EncoderLoadError(f"empty open_clip model ref for {self.name!r}")

        if ref.startswith("hf-hub:"):
            model, preprocess = open_clip.create_model_from_pretrained(ref)
            tokenizer = open_clip.get_tokenizer(ref)
        elif ref.endswith(".bin"):
            # Local checkpoint: model architecture name via env, weights from path.
            arch = os.environ.get(
                "EAGLE_BIOMED_OPENCLIP_ARCH",
                "ViT-B-16",
            ).strip()
            model, _, preprocess = open_clip.create_model_and_transforms(
                arch,
                pretrained=ref,
            )
            tokenizer = open_clip.get_tokenizer(arch)
        else:
            pretrained = os.environ.get(
                "EAGLE_BIOMED_OPENCLIP_PRETRAINED",
                "openai",
            ).strip()
            model, _, preprocess = open_clip.create_model_and_transforms(
                ref,
                pretrained=pretrained,
            )
            tokenizer = open_clip.get_tokenizer(ref)

        model.eval()
        return {
            "kind": "open_clip",
            "model": model,
            "preprocess": preprocess,
            "tokenizer": tokenizer,
            "torch": torch,
            "Image": Image,
        }

    def _load_hf_vision_backend(self, model_id: str) -> dict[str, Any]:
        import torch
        from PIL import Image
        from transformers import AutoModel, AutoProcessor

        processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)
        model = AutoModel.from_pretrained(model_id, trust_remote_code=True)
        model.eval()
        return {
            "kind": "hf_vision",
            "model": model,
            "processor": processor,
            "torch": torch,
            "Image": Image,
        }

    def _load_vision_backend(self) -> Any:
        """Load a vision encoder via open_clip / transformers (not Qwen3-VL)."""
        model_id = self.hf_model_id or _model_id_for(self.name)
        if not model_id:
            raise EncoderLoadError(f"no vision model configured for {self.name!r}")

        errors: list[str] = []
        if _prefer_open_clip(self.name, model_id):
            try:
                return self._load_open_clip_backend(model_id)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"open_clip: {exc}")

        try:
            return self._load_hf_vision_backend(model_id)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"hf_vision: {exc}")
            detail = "; ".join(errors) if errors else str(exc)
            raise EncoderLoadError(
                f"visual encoder {self.name!r} failed to load (model_id={model_id!r}): {detail}"
            ) from exc

    def _encode_open_clip_text(self, text: str) -> list[float]:
        backend = self._backend
        torch = backend["torch"]
        tokens = backend["tokenizer"]([text])
        with torch.no_grad():
            feats = backend["model"].encode_text(tokens)
            feats = feats / feats.norm(dim=-1, keepdim=True)
        return self._fit_dim(feats.squeeze(0).tolist())

    def _encode_clip_text_query(self, text: str) -> list[float]:
        """Text tower for specialized visual collections (text→image retrieval)."""
        if _encoder_mode() == "deterministic":
            return deterministic_text_embedding(text, self.dim)
        try:
            if self._backend is None or self._backend_kind not in {
                "open_clip",
                "hf_vision",
            }:
                self._backend = self._load_vision_backend()
                self._backend_kind = self._backend["kind"]
            if self._backend_kind != "open_clip":
                raise EncoderLoadError(
                    f"encoder {self.name!r} has no CLIP text tower "
                    f"(backend={self._backend_kind!r}); install open-clip-torch "
                    "(`uv sync --extra biomed`) for text→image radiology retrieval"
                )
            return self._encode_open_clip_text(text)
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, EncoderLoadError):
                raise
            try:
                return self._resolve_mode_vector(text)
            except EncoderLoadError:
                raise EncoderLoadError(
                    f"visual encoder {self.name!r} text tower failed (no Qwen fallback): {exc}"
                ) from exc

    def _encode_vision_bytes(self, image_bytes: bytes) -> list[float]:
        if self._backend is None or self._backend_kind not in {"open_clip", "hf_vision"}:
            self._backend = self._load_vision_backend()
            self._backend_kind = self._backend["kind"]

        backend = self._backend
        Image = backend["Image"]
        torch = backend["torch"]
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")

        if backend["kind"] == "open_clip":
            tensor = backend["preprocess"](image).unsqueeze(0)
            with torch.no_grad():
                feats = backend["model"].encode_image(tensor)
                feats = feats / feats.norm(dim=-1, keepdim=True)
            pooled = feats.squeeze(0).tolist()
        else:
            inputs = backend["processor"](images=image, return_tensors="pt")
            with torch.no_grad():
                outputs = backend["model"](**inputs)
            if hasattr(outputs, "image_embeds"):
                feats = outputs.image_embeds
            elif hasattr(outputs, "last_hidden_state"):
                feats = outputs.last_hidden_state.mean(dim=1)
            elif isinstance(outputs, torch.Tensor):
                feats = outputs
            else:
                feats = outputs[0]
                if feats.dim() == 3:
                    feats = feats.mean(dim=1)
            feats = feats / feats.norm(dim=-1, keepdim=True).clamp(min=1e-9)
            pooled = feats.squeeze(0).tolist()

        return self._fit_dim(pooled)

    def encode_image(self, image_bytes: bytes) -> list[float]:
        """Encode medical / domain images. Never uses Qwen3-VL."""
        if self.modality != "visual":
            msg = f"encoder {self.name!r} is not a visual encoder"
            raise ValueError(msg)
        if _encoder_mode() == "deterministic":
            return deterministic_text_embedding(image_bytes.hex(), self.dim)
        try:
            return self._encode_vision_bytes(image_bytes)
        except Exception as exc:  # noqa: BLE001
            if isinstance(exc, EncoderLoadError):
                raise
            try:
                return self._resolve_mode_vector(image_bytes.hex())
            except EncoderLoadError:
                raise EncoderLoadError(
                    f"visual encoder {self.name!r} failed (no Qwen fallback): {exc}"
                ) from exc


@dataclass
class LazyMedCPTReranker:
    """Lazy MedCPT cross-encoder for biomed post-RRF reranking."""

    name: str = "medcpt-rerank"
    hf_model_id: str = ""
    modality: str = "rerank"
    dim: int = 1

    _tokenizer: Any = None
    _model: Any = None

    def _deterministic_scores(self, query: str, texts: list[str]) -> list[float]:
        import hashlib

        scores: list[float] = []
        for text in texts:
            digest = hashlib.sha256(f"{query}\n{text}".encode()).digest()
            scores.append(digest[0] / 255.0)
        return scores

    def _load(self) -> None:
        if self._model is not None:
            return
        mode = _encoder_mode()
        if mode == "deterministic" or (_allow_deterministic() and mode == "auto"):
            return
        model_id = self.hf_model_id or _model_id_for("medcpt-rerank")
        if not model_id:
            raise EncoderLoadError("medcpt-rerank model id is not configured")
        try:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            self._tokenizer = AutoTokenizer.from_pretrained(model_id)
            self._model = AutoModelForSequenceClassification.from_pretrained(model_id)
            self._model.eval()
            if torch.cuda.is_available():
                self._model.to("cuda")
        except Exception as exc:  # noqa: BLE001
            if mode == "require_native":
                raise EncoderLoadError(f"medcpt-rerank failed to load: {exc}") from exc
            if _allow_deterministic():
                return
            raise EncoderLoadError(f"medcpt-rerank failed to load: {exc}") from exc

    def score_pairs(self, query: str, texts: list[str]) -> list[float]:
        if not texts:
            return []
        self._load()
        if self._model is None or self._tokenizer is None:
            return self._deterministic_scores(query, texts)
        try:
            import torch

            queries = [query] * len(texts)
            encoded = self._tokenizer(
                queries,
                texts,
                padding=True,
                truncation=True,
                max_length=512,
                return_tensors="pt",
            )
            device = next(self._model.parameters()).device
            encoded = {k: v.to(device) for k, v in encoded.items()}
            with torch.no_grad():
                logits = self._model(**encoded).logits
            if logits.ndim == 2 and logits.shape[1] == 1:
                raw = logits.squeeze(-1)
            elif logits.ndim == 2 and logits.shape[1] >= 2:
                raw = logits[:, -1]
            else:
                raw = logits.view(-1)
            return [float(x) for x in raw.detach().cpu().tolist()]
        except Exception as exc:  # noqa: BLE001
            if _encoder_mode() == "require_native":
                raise EncoderLoadError(f"medcpt-rerank inference failed: {exc}") from exc
            return self._deterministic_scores(query, texts)


def register_encoders(ctx: PluginContext) -> None:
    """Register biomed encoders and collection dimensions."""
    registry = ctx.encoder_registry
    registry.register(
        "pubmedbert",
        LazyDomainEncoder(
            "pubmedbert",
            ENCODER_DIMS["pubmedbert"],
            modality="text",
            hf_model_id=_model_id_for("pubmedbert"),
        ),
        dim=ENCODER_DIMS["pubmedbert"],
        modality="text",
    )
    registry.register(
        "molformer",
        LazyDomainEncoder(
            "molformer",
            ENCODER_DIMS["molformer"],
            modality="text",
            hf_model_id=_model_id_for("molformer"),
        ),
        dim=ENCODER_DIMS["molformer"],
        modality="text",
    )
    registry.register(
        "medimageinsight",
        LazyDomainEncoder(
            "medimageinsight",
            ENCODER_DIMS["medimageinsight"],
            modality="visual",
            hf_model_id=_model_id_for("medimageinsight"),
        ),
        dim=ENCODER_DIMS["medimageinsight"],
        modality="visual",
    )
    registry.register(
        "uni2",
        LazyDomainEncoder(
            "uni2",
            ENCODER_DIMS["uni2"],
            modality="visual",
            hf_model_id=_model_id_for("uni2"),
        ),
        dim=ENCODER_DIMS["uni2"],
        modality="visual",
    )
    registry.register(
        "medcpt-query",
        LazyDomainEncoder(
            "medcpt-query",
            ENCODER_DIMS["medcpt-query"],
            modality="text",
            hf_model_id=_model_id_for("medcpt-query"),
        ),
        dim=ENCODER_DIMS["medcpt-query"],
        modality="text",
    )
    registry.register(
        "medcpt-article",
        LazyDomainEncoder(
            "medcpt-article",
            ENCODER_DIMS["medcpt-article"],
            modality="text",
            hf_model_id=_model_id_for("medcpt-article"),
        ),
        dim=ENCODER_DIMS["medcpt-article"],
        modality="text",
    )
    registry.register(
        "medcpt-rerank",
        LazyMedCPTReranker(hf_model_id=_model_id_for("medcpt-rerank")),
        dim=1,
        modality="rerank",
    )
    for collection, dim in COLLECTION_DIMS.items():
        registry.register_collection(
            collection,
            dim=dim,
            default_encoder=_COLLECTION_ENCODERS.get(collection),
            hybrid_enabled=collection in ("eagle_text_biomed", "eagle_text_medcpt"),
            extra_output_fields=_TEXT_EXTRA_OUTPUT_FIELDS
            if collection in ("eagle_text_biomed", "eagle_text_medcpt")
            else (),
        )
