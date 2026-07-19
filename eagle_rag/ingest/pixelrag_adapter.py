"""PixelRAG ingest adapter (Celery task ``pixelrag_build``).

In the Eagle-RAG redesign, PixelRAG is reduced to a "visual encoder + slicer"
library call:

- ``pixelrag_render`` (hard dependency) handles render + slice:
  ``render_url``/``render_pdf``/``render_file`` write a
  ``{outdir}/{stem}.png.tiles/`` directory (containing a ``tiles.json`` manifest
  + JPEG tiles) and return a list of tile-directory ``Path``s.
- Visual encoding is delegated to :mod:`eagle_rag.ingest.visual_encoder`
  (``get_visual_encoder``). Images and text queries share one vector space.
  Backends:
  - ``embedding.visual.provider == "pixelrag"`` — local Hugging Face
    Qwen3-VL-Embedding (last-token pooling + L2, matching ``pixelrag_embed``)
  - ``embedding.visual.provider == "dashscope"`` — Bailian
    ``qwen3-vl-embedding`` via DashScope ``MultiModalEmbedding`` (same model
    family; no local GPU/CPU weights)
- Each ``(tile, embedding, metadata)`` is written to the Milvus
  ``eagle_visual`` collection via ``upsert_visual``; tile image bytes go to
  MinIO via ``store_tile``.
- ``pixelrag serve`` is **no longer started**, and ``pixelrag.build()``/FAISS
  are **no longer called**.

Cutover rule: ingest and query must use the **same** visual provider. Switching
``pixelrag`` ↔ ``dashscope`` requires rebuilding ``eagle_visual`` (do not mix
vectors from different backends in one collection). Keep ``dim: 2048`` unless
you also recreate the Milvus schema.

Key design:
- ``pixelrag_render`` is a top-level import (hard dependency); local
  torch/transformers load lazily inside ``LocalQwen3VLEncoder``. No mock
  fallback, no random-vector shimming.
- ``render_to_tiles`` / ``embed_tiles`` / ``embed_query`` are mutually
  independent; ``embed_query`` can be called directly by the retriever.
"""

from __future__ import annotations

import io
import json
import tempfile
import time
from pathlib import Path
from typing import Any

import pixelrag_render

from eagle_rag.config import get_settings
from eagle_rag.images.store import store_tile
from eagle_rag.index.registry import update_chunk_count, update_status
from eagle_rag.ingest.visual_encoder import get_visual_encoder
from eagle_rag.plugins.pipeline import ParseContext, ParseResult
from eagle_rag.storage.minio_client import download_file
from eagle_rag.tasks.celery_app import app  # noqa: F401  -- ensure the Celery app is loaded
from eagle_rag.tasks.dead_letter import retry_on_failure, with_retry
from eagle_rag.tasks.state import TaskState, update_state
from eagle_rag.telemetry import get_ai_logger, get_logger, trace_span, truncate

__all__ = [
    "pixelrag_build",
    "knowhere_visual_chunks",
    "PixelragPipeline",
    "render_to_tiles",
    "embed_tiles",
    "embed_query",
    "embed_image_bytes",
    "upsert_visual",
]

logger = get_logger(__name__)
ai_logger = get_ai_logger(__name__)


def upsert_visual(
    *,
    image_id: str,
    vector: list[float],
    image_path: str,
    document_id: str,
    page: int = 0,
    position: str = "",
    kb_name: str | None = None,
    year: int | None = None,
    source_type: str | None = None,
    chunk_type: str = "tile",
    parent_section: str | None = None,
    content_summary: str | None = None,
    source_chunk_id: str | None = None,
    plugin_namespace: str | None = None,
) -> str:
    """Write one visual vector via IngestOrchestrator (test-compatible entry point)."""
    from eagle_rag.plugins.ingest_helpers import ingest_visual_record

    settings = get_settings()
    resolved_kb = kb_name if kb_name is not None else settings.kb_name
    return ingest_visual_record(
        {
            "image_id": image_id,
            "vector": vector,
            "image_path": image_path,
            "document_id": document_id,
            "page": page,
            "position": position,
            "kb_name": resolved_kb,
            "year": year,
            "source_type": source_type,
            "chunk_type": chunk_type,
            "parent_section": parent_section,
            "content_summary": content_summary,
            "source_chunk_id": source_chunk_id,
        },
        plugin_namespace=plugin_namespace or settings.plugins.default_namespace,
        kb_name=resolved_kb,
        document_id=document_id,
    )


# ---------------------------------------------------------------------------
# Local Qwen3-VL-Embedding-2B singleton encoder
# ---------------------------------------------------------------------------


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
            from eagle_rag.ingest.url_validator import assert_not_ssrf_target

            dns_timeout = get_settings().ingest.url_prefetch.dns_timeout_sec
            assert_not_ssrf_target(source, dns_timeout_sec=dns_timeout)
            paths = pixelrag_render.render_url(
                source,
                outdir,
                backend=_backend,
                tile_height=_tile_height,
                quality=_quality,
                viewport_width=_viewport_width,
            )
        elif src_lower.endswith(".pdf"):
            from eagle_rag.ingest.limits import validate_ingest_file

            validate_ingest_file(source, Path(source).name)
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
# embed tiles / query (provider-selected visual encoder)
# ---------------------------------------------------------------------------


def embed_tiles(
    tiles: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Encode visual vectors for a list of tiles.

    Uses :func:`get_visual_encoder` (local HF or Bailian DashScope). Returns the
    original tile dicts with an added ``"vector"`` field (``list[float]``).
    """
    if not tiles:
        return []
    enc = get_visual_encoder()
    vectors = enc.embed_images([t["image_bytes"] for t in tiles])
    return [{**t, "vector": vec} for t, vec in zip(tiles, vectors, strict=True)]


def embed_query(text: str) -> list[float]:
    """Encode a text query into a visual vector (same space as images; for the retriever)."""
    return get_visual_encoder().embed_text(text)


def embed_image_bytes(image_bytes: bytes) -> list[float]:
    """Encode image bytes into a visual vector (for image-query retrieval)."""
    return get_visual_encoder().embed_image(image_bytes)


# ---------------------------------------------------------------------------
# Ingest pipeline wrapper
# ---------------------------------------------------------------------------


class PixelragPipeline:
    """Registered pixelrag ingest pipeline (minimal Celery dispatch wrapper)."""

    name = "pixelrag"

    def celery_task_name(self) -> str:
        return "eagle_rag.tasks.pixelrag_build"

    def queue(self) -> str:
        return "pixelrag_queue"

    def parse(self, ctx: ParseContext) -> ParseResult:
        source = ctx.source_uri if ctx.source_uri else ctx.file_path
        tiles = render_to_tiles(source)
        return ParseResult(raw=tiles, pipeline=self.name, chunk_count=len(tiles))

    def to_nodes(self, parse_result: ParseResult, ctx: ParseContext) -> list[dict[str, Any]]:
        return embed_tiles(parse_result.raw)


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
    plugin_namespace: str | None = None,
    sha256: str | None = None,
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

    from eagle_rag.tasks.state import get_audit, prepare_rerun

    existing = get_audit(job_id)
    if existing is not None:
        if (existing.get("status") or "").lower() == TaskState.SUCCESS.value:
            return
        prepare_rerun(job_id)

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

            from eagle_rag.plugins.ingest_tracker import (
                clear_ingest_collections,
                snapshot_ingest_collections,
            )

            clear_ingest_collections()

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
                    chunk_type="tile",
                    plugin_namespace=settings.plugins.default_namespace,
                )

            # 5. INDEXING
            update_state(job_id, TaskState.INDEXING, log_entry="Writing Milvus visual index")

            # 6. chunk_count = number of tiles
            update_chunk_count(document_id, n)

            # 7. Document status -> ready
            update_status(document_id, "ready")

            from eagle_rag.plugins.ingest_catalog import commit_ingest_catalog

            collections = snapshot_ingest_collections()
            if not collections:
                collections = [settings.milvus.visual_collection]
            commit_ingest_catalog(
                document_id,
                resolved_kb,
                collections,
                plugin_namespace=settings.plugins.default_namespace,
            )

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
    from eagle_rag.tasks.state import create_audit, get_audit, prepare_rerun

    existing = get_audit(job_id)
    if existing is None:
        create_audit(job_id, document_id, "knowhere_visual", kb_name=resolved_kb)
    else:
        # Worker restart / acks_late redelivery leaves audits mid-pipeline
        # (embedding/indexing). prepare_rerun bridges to a legal RENDERING entry.
        if (existing.get("status") or "").lower() == TaskState.SUCCESS.value:
            return
        prepare_rerun(job_id)

    try:
        with trace_span("ingest.knowhere_visual"):
            t0 = time.monotonic()
            update_state(
                job_id,
                TaskState.RENDERING,
                log_entry=f"Processing {len(chunks)} Knowhere visual chunks",
            )

            from eagle_rag.plugins.ingest_tracker import (
                clear_ingest_collections,
                snapshot_ingest_collections,
            )

            clear_ingest_collections()

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
                        plugin_namespace=settings.plugins.default_namespace,
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

            from eagle_rag.plugins.ingest_catalog import commit_ingest_catalog

            collections = snapshot_ingest_collections()
            if not collections:
                collections = [settings.milvus.visual_collection]
            commit_ingest_catalog(
                document_id,
                resolved_kb,
                collections,
                plugin_namespace=settings.plugins.default_namespace,
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
