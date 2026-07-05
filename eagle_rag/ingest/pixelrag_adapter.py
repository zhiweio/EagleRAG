"""PixelRAG ingest adapter (Celery task ``pixelrag_build``).

In the Eagle-RAG redesign, PixelRAG is reduced to a "visual encoder + slicer"
library call:

- ``pixelrag_render`` (hard dependency) handles render + slice:
  ``render_url``/``render_pdf``/``render_file`` write a
  ``{outdir}/{stem}.png.tiles/`` directory (containing a ``tiles.json`` manifest
  + JPEG tiles) and return a list of tile-directory ``Path``s.
- Visual encoding is done by a **local Qwen3-VL-Embedding singleton**
  (``_Qwen3VLVisualEncoder``) mirroring ``pixelrag_embed.embed_cpu``'s
  last-token pooling + L2 normalization; images and text queries share the same
  vector space. ``pixelrag_embed`` only ships an offline sharded batch pipeline
  and exposes no per-item ``embed_image``/``embed_text`` API, so we implement
  the singleton encoder here.
- Each ``(tile, embedding, metadata)`` is written to the Milvus
  ``eagle_visual`` collection via ``upsert_visual``; tile image bytes go to
  MinIO via ``store_tile``.
- ``pixelrag serve`` is **no longer started**, and ``pixelrag.build()``/FAISS
  are **no longer called**.

Visual-encoder provider constraints (per context7 research on the PixelRAG
official docs):
- PixelRAG officially supports only the ``Qwen3-VL-Embedding`` family — the
  model is **fine-tuned on document screenshots** (pixelrag README: "fine-tuned
  on screenshot data"), which is the foundation of tile retrieval quality.
  ``pixelrag_embed`` provides only local backends (hf/vllm/sglang) with
  **no HTTP/MaaS backend**.
- This encoder therefore **accepts only** ``embedding.visual.provider == "pixelrag"``;
  ``_ensure_loaded`` validates on first load and fail-fasts with a
  ``ValueError`` explaining why if it does not match. Third-party MaaS visual
  embeddings are not fine-tuned on screenshots (degrading retrieval quality)
  and their vector dimension is hard-bound to the Milvus collection, so they
  are unsupported.
- The **only extensibility axis** is ``embedding.visual.model``: any
  Qwen3-VL-Embedding checkpoint/size is allowed (including ``pixelrag-train``
  self-fine-tuned BiQwen3 variants), but the model class
  (``Qwen3VLForConditionalGeneration``) and pooling recipe are fixed and cannot
  be swapped for another architecture.

Key design:
- ``pixelrag_render`` is a top-level import (hard dependency); torch/transformers
  are imported lazily inside the encoder and the model is loaded on first
  encoding, then cached as a process-local singleton. No mock fallback, no
  API-inconsistency shimming.
- ``render_to_tiles`` / ``embed_tiles`` / ``embed_query`` are mutually
  independent; ``embed_query`` can be called directly by the retriever.
"""

from __future__ import annotations

import io
import json
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import pixelrag_render

from eagle_rag.config import get_settings
from eagle_rag.images.store import store_tile
from eagle_rag.index.milvus_visual_store import upsert_visual
from eagle_rag.index.registry import update_chunk_count, update_status
from eagle_rag.storage.minio_client import download_file
from eagle_rag.tasks.celery_app import app  # noqa: F401  -- ensure the Celery app is loaded
from eagle_rag.tasks.dead_letter import retry_on_failure, with_retry
from eagle_rag.tasks.state import TaskState, update_state
from eagle_rag.telemetry import get_ai_logger, get_logger, trace_span, truncate

__all__ = [
    "pixelrag_build",
    "knowhere_visual_chunks",
    "render_to_tiles",
    "embed_tiles",
    "embed_query",
]

logger = get_logger(__name__)
ai_logger = get_ai_logger(__name__)

# Qwen3-VL patch alignment and render viewport width (aligned with pixelrag_embed / pixelrag_render)
_RESIZE_FACTOR = 28
_MAX_CHUNK_WIDTH = 875


# ---------------------------------------------------------------------------
# Local Qwen3-VL-Embedding-2B singleton encoder
# ---------------------------------------------------------------------------


def _resolve_device(device: str) -> str:
    """Resolve a device string; ``auto`` probes cuda → mps → cpu (in that order)."""
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
        and platform.machine()
        in (
            "aarch64",
            "arm64",
        )
    ):
        logger.info(
            "ARM Linux container has no MPS/CUDA; visual encoding uses CPU. "
            "On Apple Silicon, run API/worker-pixelrag natively with `uv run` for MPS."
        )
    return resolved


def _clamp_width(img: Any, max_width: int = _MAX_CHUNK_WIDTH) -> Any:
    """Downscale proportionally when width > ``max_width`` (28px-aligned), like ``embed_cpu``."""
    from PIL import Image

    w, h = img.size
    if w <= max_width:
        return img
    scale = max_width / w
    new_w = max(round(w * scale / _RESIZE_FACTOR) * _RESIZE_FACTOR, _RESIZE_FACTOR)
    new_h = max(round(h * scale / _RESIZE_FACTOR) * _RESIZE_FACTOR, _RESIZE_FACTOR)
    return img.resize((new_w, new_h), Image.LANCZOS)


class _Qwen3VLVisualEncoder:
    """Qwen3-VL-Embedding-2B singleton encoder (image and text share one space).

    The model is loaded lazily on the first ``embed_image`` / ``embed_text`` call
    and cached as a process-local singleton. Uses last-token pooling + L2
    normalization (matching ``pixelrag_embed.embed_cpu``) so ingest-side (image)
    and retrieval-side (text query) vectors are aligned.
    """

    _instance: _Qwen3VLVisualEncoder | None = None
    _load_lock = threading.Lock()

    def __init__(self) -> None:
        self._model: Any = None
        self._processor: Any = None
        self._device: str | None = None
        self._torch: Any = None

    @classmethod
    def get(cls) -> _Qwen3VLVisualEncoder:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        with self._load_lock:
            if self._model is not None:
                return
            settings = get_settings()
            provider = settings.embedding.visual.provider
            if provider != "pixelrag":
                raise ValueError(
                    f"embedding.visual.provider={provider!r} is not supported. "
                    "PixelRAG visual encoding requires provider='pixelrag' "
                    "(local Qwen3-VL-Embedding, fine-tuned for document screenshots). "
                    "Third-party MaaS visual embeddings are not screenshot-tuned and would "
                    "degrade retrieval quality; vector dimension is bound to the Milvus "
                    "eagle_visual collection (changing provider requires a collection rebuild). "
                    "For custom embeddings, train a Qwen3-VL-Embedding variant with "
                    "pixelrag-train and set embedding.visual.model to its checkpoint."
                )
            import torch
            from transformers import AutoProcessor, Qwen3VLForConditionalGeneration

            model_name = settings.embedding.visual.model
            device = _resolve_device(settings.pixelrag.embed_device)
            dtype = torch.float32 if device == "cpu" else torch.float16
            logger.info("loading visual encoder model %s on %s (%s)", model_name, device, dtype)
            import os

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
        """Encode image bytes into a visual vector."""
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
        """Encode a text query into a visual vector (same space as images; for the retriever)."""
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


def _encoder() -> _Qwen3VLVisualEncoder:
    return _Qwen3VLVisualEncoder.get()


# ---------------------------------------------------------------------------
# render → tiles (real disk API)
# ---------------------------------------------------------------------------


def _image_size(data: bytes) -> tuple[int, int]:
    """Read (width, height) from the image header without decoding pixels."""
    from PIL import Image

    with Image.open(io.BytesIO(data)) as img:
        return img.size


def _make_tile(file_path: Path, *, page: int, position: str) -> dict[str, Any]:
    """Read a single tile file into ``{image_bytes, page, position, width, height}``."""
    data = file_path.read_bytes()
    width, height = _image_size(data)
    return {
        "image_bytes": data,
        "page": page,
        "position": position,
        "width": width,
        "height": height,
    }


def _read_tiles_from_paths(paths: list[Path]) -> list[dict[str, Any]]:
    """Normalize the list of ``Path``s returned by ``pixelrag_render`` into tile dicts.

    Each Path may be:
    - a tile directory (``*.png.tiles/``): read the ``tiles.json`` manifest for
      tile files, falling back to the ``chunks.json`` ``chunks`` list, then to
      any image file inside the directory;
    - a single image file (when ``render_file`` copies an image directly).
    """
    out: list[dict[str, Any]] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            tiles_json = p / "tiles.json"
            chunks_json = p / "chunks.json"
            if tiles_json.exists():
                meta = json.loads(tiles_json.read_text())
                names = meta.get("tiles", []) or []
                # PDF tiles.json uses list[str]; CDP may use list[dict] — accept both
                for idx, name in enumerate(names):
                    fname = name["file"] if isinstance(name, dict) else name
                    fp = p / fname
                    if fp.exists():
                        out.append(_make_tile(fp, page=idx, position=f"strip_{idx}"))
            elif chunks_json.exists():
                meta = json.loads(chunks_json.read_text())
                for idx, ch in enumerate(meta.get("chunks", []) or []):
                    fp = p / ch["file"]
                    if fp.exists():
                        out.append(
                            _make_tile(
                                fp,
                                page=ch.get("tile_index", idx),
                                position=f"chunk_{ch.get('chunk_index', idx)}",
                            )
                        )
            else:
                img_files = sorted(
                    f for f in p.iterdir() if f.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
                )
                for idx, fp in enumerate(img_files):
                    out.append(_make_tile(fp, page=idx, position=f"strip_{idx}"))
        elif p.is_file():
            out.append(_make_tile(p, page=0, position="strip_0"))
    return out


def render_to_tiles(
    source: str,
    *,
    backend: str | None = None,
    tile_height: int | None = None,
    quality: int | None = None,
    viewport_width: int | None = None,
    pdf_dpi: int | None = None,
) -> list[dict[str, Any]]:
    """Render + slice, returning a list of tiles.

    Each item is ``{"image_bytes": bytes, "page": int, "position": str,
    "width": int, "height": int}``.

    - URL (http/https prefix) → ``pixelrag_render.render_url``
    - ``.pdf`` suffix → ``pixelrag_render.render_pdf``
    - otherwise (local file) → ``pixelrag_render.render_file``

    Args:
        source: URL or local file path.
        backend: Override render backend; defaults to ``settings.pixelrag.backend``.
        tile_height: Override tile height; defaults to ``settings.pixelrag.tile_height``.
        quality: Override JPEG quality; defaults to ``settings.pixelrag.quality``.
        viewport_width: Override viewport width; defaults to ``settings.pixelrag.viewport_width``.
        pdf_dpi: Override PDF render DPI; defaults to ``settings.pixelrag.pdf_dpi``.

    Returns:
        Tile dicts (rendered into a temp dir that is auto-cleaned after reading).

    Raises:
        RuntimeError: If the renderer produced no tiles.
    """
    cfg = get_settings().pixelrag
    _backend = backend if backend is not None else cfg.backend
    _tile_height = tile_height if tile_height is not None else cfg.tile_height
    _quality = quality if quality is not None else cfg.quality
    _viewport_width = viewport_width if viewport_width is not None else cfg.viewport_width
    _pdf_dpi = pdf_dpi if pdf_dpi is not None else cfg.pdf_dpi

    src_lower = source.lower()
    with tempfile.TemporaryDirectory(prefix="pixelrag_render_") as outdir:
        if source.startswith(("http://", "https://")):
            paths = pixelrag_render.render_url(
                source,
                outdir,
                backend=_backend,
                tile_height=_tile_height,
                quality=_quality,
                viewport_width=_viewport_width,
            )
        elif src_lower.endswith(".pdf"):
            paths = pixelrag_render.render_pdf(
                source,
                outdir,
                dpi=_pdf_dpi,
                quality=_quality,
            )
        else:
            paths = pixelrag_render.render_file(source, outdir, backend=_backend)
        tiles = _read_tiles_from_paths(paths)

    if not tiles:
        raise RuntimeError("pixelrag_render produced no tiles")
    return tiles


# ---------------------------------------------------------------------------
# embed tiles / query (local Qwen3-VL singleton)
# ---------------------------------------------------------------------------


def embed_tiles(
    tiles: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Encode visual vectors for a list of tiles.

    Calls the local Qwen3-VL-Embedding-2B singleton to encode each tile's
    ``image_bytes``. Returns the original tile dicts with an added ``"vector"``
    field (``list[float]``).
    """
    enc = _encoder()
    out: list[dict[str, Any]] = []
    for t in tiles:
        vec = enc.embed_image(t["image_bytes"])
        out.append({**t, "vector": vec})
    return out


def embed_query(text: str) -> list[float]:
    """Encode a text query into a visual vector (same space as images; for the retriever)."""
    return _encoder().embed_text(text)


# ---------------------------------------------------------------------------
# Celery tasks
# ---------------------------------------------------------------------------


@with_retry(name="eagle_rag.tasks.pixelrag_build", queue="pixelrag_queue")
def pixelrag_build(
    self: Any,
    job_id: str,
    document_id: str,
    name: str,
    object_key: str | None = None,
    local_path: str | None = None,
    source_uri: str | None = None,
    source_type: str = "financial",
    kb_name: str | None = None,
    year: int | None = None,
) -> None:
    """PixelRAG pipeline: render → slice → embed → write the visual index.

    Exactly one of ``object_key`` (MinIO), ``local_path``, or ``source_uri``
    (URL) must be provided. Flow: RENDERING → ``render_to_tiles`` → per-tile
    EMBEDDING (``store_tile`` + ``upsert_visual`` with kb_name/year/source_type)
    → INDEXING → ``update_chunk_count`` → ``update_status`` ready → SUCCESS.
    On exception: ``update_state(FAILED)`` then ``retry_on_failure``.

    Args:
        kb_name: Knowledge base id; falls back to ``settings.kb_name`` when None.
    """
    settings = get_settings()
    chunk_size = settings.pixelrag.chunk_size
    resolved_kb = kb_name if kb_name is not None else settings.kb_name

    try:
        with trace_span("ingest.pixelrag"):
            t0 = time.monotonic()
            # 1. RENDERING: resolve local path or URL
            update_state(job_id, TaskState.RENDERING, log_entry="PixelRAG rendering")

            if local_path:
                source = local_path
            elif source_uri and source_uri.startswith(("http://", "https://")):
                source = source_uri
            elif object_key:
                suffix = Path(object_key).suffix or ".bin"
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                tmp.close()
                download_file(object_key, tmp.name)
                source = tmp.name
            else:
                raise ValueError(
                    "pixelrag_build requires at least one of "
                    "object_key, local_path, or source_uri (url)"
                )

            # 2. render + chunk
            tiles = render_to_tiles(source)
            n = len(tiles)

            # 3. Encode a visual vector per tile
            tiles_with_vec = embed_tiles(tiles)

            # 4. Per tile: write image store + write Milvus visual index
            for i, tile in enumerate(tiles_with_vec):
                update_state(
                    job_id,
                    TaskState.EMBEDDING,
                    current=i,
                    total=n,
                    log_entry=f"Tile {i + 1}/{n}",
                )
                image_id = f"{document_id}_{i}"
                stored = store_tile(
                    image_id,
                    document_id,
                    data=tile["image_bytes"],
                    kb_name=resolved_kb,
                    page=tile.get("page", i),
                    position=tile.get("position", f"strip_{i}"),
                    width=tile.get("width", chunk_size),
                    height=tile.get("height", chunk_size),
                )
                image_path = (
                    stored.get("url")
                    or stored.get("object_key")
                    or stored.get("local_path")
                    or image_id
                )
                upsert_visual(
                    image_id=image_id,
                    vector=tile["vector"],
                    image_path=image_path,
                    document_id=document_id,
                    page=tile.get("page", i),
                    position=tile.get("position", f"strip_{i}"),
                    kb_name=resolved_kb,
                    year=year,
                    source_type=source_type,
                )

            # 5. INDEXING
            update_state(job_id, TaskState.INDEXING, log_entry="Writing Milvus visual index")

            # 6. chunk_count = number of tiles
            update_chunk_count(document_id, n)

            # 7. Document status -> ready
            update_status(document_id, "ready")

            # 8. SUCCESS
            update_state(
                job_id,
                TaskState.SUCCESS,
                current=n,
                total=n,
                progress=100,
                log_entry="PixelRAG pipeline complete",
            )

            try:
                ai_logger.info(
                    "ingest",
                    job_id=job_id,
                    document_id=document_id,
                    pipeline="pixelrag",
                    kb_name=resolved_kb,
                    source_type=source_type,
                    name=truncate(name, 128),
                    chunks=n,
                    status="success",
                    duration_ms=int((time.monotonic() - t0) * 1000),
                )
            except Exception:  # noqa: BLE001
                logger.debug("telemetry emit failed", exc_info=True)

    except Exception as exc:  # noqa: BLE001
        try:
            ai_logger.info(
                "ingest",
                job_id=job_id,
                document_id=document_id,
                pipeline="pixelrag",
                kb_name=resolved_kb,
                status="failed",
                error=truncate(str(exc), 256),
                duration_ms=int((time.monotonic() - t0) * 1000),
            )
        except Exception:  # noqa: BLE001
            logger.debug("telemetry emit failed", exc_info=True)
        try:
            update_state(job_id, TaskState.FAILED, error=str(exc))
        except Exception:  # noqa: BLE001
            pass
        retry_on_failure(self, exc)


@with_retry(name="eagle_rag.tasks.knowhere_visual_chunks", queue="pixelrag_queue")
def knowhere_visual_chunks(
    self: Any,
    job_id: str,
    document_id: str,
    kb_name: str | None,
    source_type: str,
    chunks: list[dict[str, Any]],
    parent_job_id: str | None = None,
) -> None:
    """Knowhere visual-chunk pipeline (dispatched by ``dispatch_visual_chunks``).

    For each visual chunk (image/table): download ``object_key`` from MinIO →
    write a temp file (image uses the ``file_path`` extension; table writes
    ``.html``) → ``render_to_tiles`` → ``embed_tiles`` → per-tile ``store_tile``
    + ``upsert_visual`` (carrying ``chunk_type``/``parent_section``/
    ``content_summary``/``source_chunk_id``). Temp files are cleaned up after
    use. The document status has already been set to ready by ``knowhere_parse``;
    failure here only triggers ``update_state(FAILED)`` + ``retry_on_failure``
    and does not affect the document status.

    Uses a dedicated ``job_id`` (``{parent_job_id}:visual``) with its own
    ``task_audit`` record so the state machine doesn't conflict with
    ``knowhere_parse``'s terminal SUCCESS state.

    Args:
        job_id: Dedicated sub-job ID for this visual task.
        parent_job_id: The parent ``knowhere_parse`` job_id (for logging).
        kb_name: Knowledge base id; falls back to ``settings.kb_name`` when None.
    """
    settings = get_settings()
    resolved_kb = kb_name if kb_name is not None else settings.kb_name

    # Create an independent audit record for this visual sub-task.
    from eagle_rag.tasks.state import create_audit, get_audit

    if get_audit(job_id) is None:
        create_audit(job_id, document_id, "knowhere_visual", kb_name=resolved_kb)

    try:
        with trace_span("ingest.knowhere_visual"):
            t0 = time.monotonic()
            update_state(
                job_id,
                TaskState.RENDERING,
                log_entry=f"Processing {len(chunks)} Knowhere visual chunks",
            )

            for i, chunk in enumerate(chunks):
                # Download the chunk's raw bytes to a temp file
                if chunk["type"] == "table":
                    suffix = ".html"
                else:
                    suffix = Path(chunk.get("file_path", "")).suffix or ".png"
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
                tmp.close()
                tmp_path = tmp.name
                download_file(chunk["object_key"], tmp_path)

                # Render + slice + encode
                tiles = render_to_tiles(tmp_path)
                tiles_with_vec = embed_tiles(tiles)

                # Per tile: write image store + write Milvus visual index
                for j, tile in enumerate(tiles_with_vec):
                    update_state(
                        job_id,
                        TaskState.EMBEDDING,
                        current=i * len(tiles) + j,
                        total=len(chunks) * len(tiles),
                        log_entry=(f"Visual chunk {i + 1}/{len(chunks)} tile {j + 1}/{len(tiles)}"),
                    )
                    image_id = f"{document_id}_vc_{i}_{j}"
                    stored = store_tile(
                        image_id,
                        document_id,
                        data=tile["image_bytes"],
                        kb_name=resolved_kb,
                        page=tile.get("page", j),
                        position=tile.get("position", f"vc_{i}_{j}"),
                        width=tile.get("width"),
                        height=tile.get("height"),
                    )
                    image_path = (
                        stored.get("url")
                        or stored.get("object_key")
                        or stored.get("local_path")
                        or image_id
                    )
                    upsert_visual(
                        image_id=image_id,
                        vector=tile["vector"],
                        image_path=image_path,
                        document_id=document_id,
                        page=tile.get("page", j),
                        position=tile.get("position", f"vc_{i}_{j}"),
                        kb_name=resolved_kb,
                        source_type=source_type,
                        chunk_type=chunk["type"],
                        parent_section=chunk.get("parent_section"),
                        content_summary=chunk.get("summary"),
                        source_chunk_id=chunk.get("chunk_id"),
                    )

                # Clean up the temp file
                Path(tmp_path).unlink(missing_ok=True)

            update_state(job_id, TaskState.INDEXING, log_entry="Writing Milvus visual index")
            update_state(
                job_id,
                TaskState.SUCCESS,
                progress=100,
                log_entry=(f"Knowhere visual chunks complete, {len(chunks)} chunks"),
            )

            try:
                ai_logger.info(
                    "ingest",
                    job_id=job_id,
                    document_id=document_id,
                    pipeline="knowhere_visual",
                    kb_name=resolved_kb,
                    source_type=source_type,
                    chunks=len(chunks),
                    status="success",
                    duration_ms=int((time.monotonic() - t0) * 1000),
                )
            except Exception:  # noqa: BLE001
                logger.debug("telemetry emit failed", exc_info=True)

    except Exception as exc:  # noqa: BLE001
        try:
            ai_logger.info(
                "ingest",
                job_id=job_id,
                document_id=document_id,
                pipeline="knowhere_visual",
                kb_name=resolved_kb,
                status="failed",
                error=truncate(str(exc), 256),
                duration_ms=int((time.monotonic() - t0) * 1000),
            )
        except Exception:  # noqa: BLE001
            logger.debug("telemetry emit failed", exc_info=True)
        try:
            update_state(job_id, TaskState.FAILED, error=str(exc))
        except Exception:  # noqa: BLE001
            pass
        retry_on_failure(self, exc)
