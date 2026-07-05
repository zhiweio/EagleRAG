"""Lazy parsing of session attachments (no Milvus writes)."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from llama_index.core.schema import ImageDocument, TextNode

from eagle_rag.attachments.store import get_attachment_bytes_sync, get_attachment_sync
from eagle_rag.config import get_settings
from eagle_rag.ingest.knowhere_adapter import chunks_to_text_nodes, parse_with_knowhere_sdk
from eagle_rag.ingest.pixelrag_adapter import render_to_tiles
from eagle_rag.ingest.router import probe_pdf_form
from eagle_rag.telemetry import get_logger

__all__ = ["ParsedAttachments", "parse_attachments"]

logger = get_logger(__name__)

_EPHEMERAL_KB = "_ephemeral_"
_INLINE_EXTS = {".txt", ".md", ".markdown", ".json", ".csv"}


def _routing_exts() -> tuple[set[str], set[str], set[str]]:
    """Return (knowhere_exts, pdf_exts, pixelrag_exts) from ``settings.ingest.routing``."""
    cfg = get_settings().ingest.routing
    return set(cfg.knowhere_exts), set(cfg.pdf_exts), set(cfg.pixelrag_exts)


@dataclass
class ParsedAttachments:
    """Aggregated result of parsing all attachments for a single query."""

    text_nodes: list[TextNode] = field(default_factory=list)
    image_docs: list[ImageDocument] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    parsed_count: int = 0
    cached_count: int = 0
    has_doc_attachments: bool = False

    def step_payload(self) -> dict[str, Any]:
        return {
            "name": "attach_parse",
            "parsed": self.parsed_count,
            "text_chunks": len(self.text_nodes),
            "image_count": len(self.image_docs),
            "cached": self.cached_count,
            "errors": self.errors,
        }


def _parse_cfg() -> Any:
    return get_settings().attachments.parse


def _sidecar_path(storage_path: str) -> Path:
    return Path(f"{storage_path}.parsed.json")


def _load_cache(storage_path: str) -> dict[str, Any] | None:
    if not _parse_cfg().cache_enabled:
        return None
    path = _sidecar_path(storage_path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("failed to read attachment parse cache %s: %s", path, exc)
        return None


def _save_cache(storage_path: str, payload: dict[str, Any]) -> None:
    if not _parse_cfg().cache_enabled:
        return
    try:
        _sidecar_path(storage_path).write_text(
            json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as exc:
        logger.debug("failed to write attachment parse cache: %s", exc)


def _ext(file_name: str) -> str:
    dot = file_name.rfind(".")
    return file_name[dot:].lower() if dot >= 0 else ""


# Top-level serializable fields of a Knowhere chunk.
# Aligns with SDK BaseChunk/TextChunk plus TableChunk.html and ImageChunk.data;
# both inline and SDK chunks are flattened via these fields for cache JSON round-trip.
_CHUNK_FIELDS = ("chunk_id", "type", "content", "path", "html", "data")

# ChunkMetadata fields nested under chunk.metadata (summary/keywords/page_nums/connect_to etc.).
# The SDK stores summary, keywords, page numbers, and cross-chunk links on a nested metadata object;
# inline chunks mirror this with SimpleNamespace(metadata=...) so _meta() can read uniformly.
_META_FIELDS = (
    "summary",
    "keywords",
    "page_nums",
    "connect_to",
    "file_path",
    "original_name",
    "table_type",
)


def _chunk_to_dict(chunk: SimpleNamespace) -> dict[str, Any]:
    """Convert a chunk object (SimpleNamespace/SDK TextChunk) to a JSON-serializable dict.

    Used when persisting the attachment parse cache: SimpleNamespace is not directly
    ``json.dumps``-able, so it must be flattened first. The nested ``metadata``
    object is flattened into a sub-dict and rebuilt by ``_dict_to_chunk``.
    """
    meta = getattr(chunk, "metadata", None)
    return {
        **{f: getattr(chunk, f, None) for f in _CHUNK_FIELDS},
        "metadata": {f: getattr(meta, f, None) for f in _META_FIELDS},
    }


def _dict_to_chunk(d: dict[str, Any]) -> SimpleNamespace:
    """Rebuild a SimpleNamespace chunk from a cache dict (duck-typed to SDK TextChunk).

    The nested ``metadata`` sub-dict is restored as a SimpleNamespace so the
    ``chunk.metadata.<name>`` access path matches a real SDK chunk
    (``chunks_to_text_nodes`` reads it via ``_meta``).
    """
    meta_dict = d.get("metadata") or {}
    return SimpleNamespace(
        **{f: d.get(f) for f in _CHUNK_FIELDS},
        metadata=SimpleNamespace(**{f: meta_dict.get(f) for f in _META_FIELDS}),
    )


def _inline_chunks(text: str, *, attachment_id: str, file_name: str) -> list[SimpleNamespace]:
    """Slice text by ``chunk_size`` and return a list of SimpleNamespace chunk objects.

    Behavior unchanged: at most ``max_chunks`` segments with chunk_id ``{attachment_id}_{N}``.
    The returned objects are duck-typed to match SDK ``TextChunk``: top-level
    ``chunk_id/type/content/path`` and a nested ``metadata`` SimpleNamespace carrying
    summary/keywords/page_nums/connect_to/file_path, so ``chunks_to_text_nodes``
    can read them uniformly via ``_meta(chunk, ...)``.
    """
    size = _parse_cfg().chunk_size
    max_chunks = _parse_cfg().max_chunks
    chunks: list[SimpleNamespace] = []
    for i in range(0, len(text), size):
        if len(chunks) >= max_chunks:
            break
        part = text[i : i + size]
        chunks.append(
            SimpleNamespace(
                chunk_id=f"{attachment_id}_{len(chunks)}",
                type="text",
                content=part,
                path=file_name,
                metadata=SimpleNamespace(
                    summary="",
                    keywords=[],
                    page_nums=[],
                    connect_to=[],
                    file_path=file_name,
                    original_name=None,
                    table_type=None,
                ),
                html=None,
                data=None,
            )
        )
    return chunks


def _chunks_from_knowhere(
    file_path: str, *, attachment_id: str, file_name: str
) -> list[SimpleNamespace]:
    """Parse an attachment via the Knowhere SDK and return a list of text chunk objects.

    Only ``result.text_chunks`` is consumed (attachments need text only), truncated
    to ``max_chunks``. ``attachment_id`` is kept for caller signature compatibility
    (SDK chunks carry their own chunk_id, so it is not passed in). On failure a
    ``KnowhereError`` propagates to the caller, which decides the fallback strategy.
    """
    result = parse_with_knowhere_sdk(
        file_path,
        kb_name=_EPHEMERAL_KB,
        file_name=file_name,
    )
    return list(result.text_chunks)[: _parse_cfg().max_chunks]


def _pdf_inline_fallback(file_path: str, *, attachment_id: str) -> list[SimpleNamespace]:
    try:
        from pypdf import PdfReader

        reader = PdfReader(file_path)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        return _inline_chunks(text, attachment_id=attachment_id, file_name=Path(file_path).name)
    except Exception as exc:  # noqa: BLE001
        logger.debug("PDF inline fallback failed: %s", exc)
        return []


def _parse_one(meta: dict[str, Any], data: bytes) -> tuple[dict[str, Any], bool]:
    """Parse a single attachment, returning (cache_payload, from_cache)."""
    storage_path = str(meta["storage_path"])
    cached = _load_cache(storage_path)
    if cached is not None:
        return cached, True

    attachment_id = str(meta["attachment_id"])
    file_name = str(meta.get("file_name") or "upload")
    mime = (meta.get("mime") or "").lower()
    ext = _ext(file_name)
    knowhere_exts, pdf_exts, pixelrag_exts = _routing_exts()

    payload: dict[str, Any] = {
        "attachment_id": attachment_id,
        "file_name": file_name,
        "pipeline": "inline",
        "chunks": [],
        "tiles": [],
    }

    if mime.startswith("image/") or ext in pixelrag_exts:
        payload["pipeline"] = "image"
        payload["image_b64"] = base64.b64encode(data).decode("ascii")
        _save_cache(storage_path, payload)
        return payload, False

    path_obj = Path(storage_path)
    if not path_obj.exists():
        path_obj.write_bytes(data)

    inline_mimes = ("text/plain", "text/markdown", "application/json", "text/csv")
    if ext in _INLINE_EXTS or mime in inline_mimes:
        try:
            text = data.decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            text = ""
        payload["pipeline"] = "inline"
        payload["chunks"] = _inline_chunks(text, attachment_id=attachment_id, file_name=file_name)
    elif ext in pdf_exts:
        form = probe_pdf_form(str(path_obj))
        if form == "scanned":
            payload["pipeline"] = "pixelrag"
            tiles = render_to_tiles(str(path_obj))[: _parse_cfg().max_chunks]
            payload["tiles"] = [
                {
                    "page": t.get("page", i),
                    "position": t.get("position", f"strip_{i}"),
                    "png_b64": base64.b64encode(t["png_bytes"]).decode("ascii"),
                }
                for i, t in enumerate(tiles)
                if t.get("png_bytes")
            ]
        else:
            payload["pipeline"] = "knowhere"
            try:
                payload["chunks"] = _chunks_from_knowhere(
                    str(path_obj),
                    attachment_id=attachment_id,
                    file_name=file_name,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Knowhere attachment parse failed; falling back to pypdf: %s", exc)
                payload["pipeline"] = "inline"
                payload["chunks"] = _pdf_inline_fallback(
                    str(path_obj),
                    attachment_id=attachment_id,
                )
    elif ext in knowhere_exts:
        payload["pipeline"] = "knowhere"
        try:
            payload["chunks"] = _chunks_from_knowhere(
                str(path_obj),
                attachment_id=attachment_id,
                file_name=file_name,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Knowhere attachment parse failed: %s", exc)
            payload["chunks"] = []
    else:
        payload["pipeline"] = "knowhere"
        try:
            payload["chunks"] = _chunks_from_knowhere(
                str(path_obj),
                attachment_id=attachment_id,
                file_name=file_name,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("unknown extension attachment parse failed: %s", exc)
            payload["chunks"] = []

    # Flatten chunks to dicts for JSON cache (SimpleNamespace isn't json-serializable);
    # _materialize rebuilds them as SimpleNamespace on read.
    if payload.get("chunks"):
        payload["chunks"] = [_chunk_to_dict(c) for c in payload["chunks"]]

    _save_cache(storage_path, payload)
    return payload, False


def _materialize(payload: dict[str, Any]) -> tuple[list[TextNode], list[ImageDocument]]:
    attachment_id = str(payload.get("attachment_id", ""))
    file_name = str(payload.get("file_name", ""))
    text_nodes: list[TextNode] = []
    image_docs: list[ImageDocument] = []

    if payload.get("image_b64"):
        try:
            raw = base64.b64decode(payload["image_b64"])
            image_docs.append(ImageDocument(image=raw))
        except Exception as exc:  # noqa: BLE001
            logger.debug("attachment image restore failed: %s", exc)

    chunks = payload.get("chunks") or []
    if chunks:
        # Rebuild cached chunk dicts as SimpleNamespace wrapped in an object with .chunks,
        # matching the ParseResult duck type chunks_to_text_nodes expects (needs .chunks).
        chunk_objs = [_dict_to_chunk(c) for c in chunks]
        parse_result = SimpleNamespace(chunks=chunk_objs)
        nodes = chunks_to_text_nodes(
            parse_result,
            document_id=attachment_id,
            source_type="attachment",
            kb_name=_EPHEMERAL_KB,
        )
        for node in nodes:
            node.metadata["source"] = "attachment"
            node.metadata["attachment_id"] = attachment_id
            node.metadata["file_name"] = file_name
        text_nodes.extend(nodes)

    for tile in payload.get("tiles") or []:
        try:
            png = base64.b64decode(tile["png_b64"])
            image_docs.append(ImageDocument(image=png))
        except Exception as exc:  # noqa: BLE001
            logger.debug("attachment tile restore failed: %s", exc)

    return text_nodes, image_docs


def parse_attachments(attachment_ids: list[str] | None) -> ParsedAttachments:
    """Lazily parse a list of attachments, merging sidecar cache results."""
    result = ParsedAttachments()
    if not attachment_ids:
        return result

    max_bytes = _parse_cfg().max_bytes
    _, _, pixelrag_exts = _routing_exts()
    for aid in attachment_ids:
        meta = get_attachment_sync(aid)
        if meta is None:
            result.errors.append(f"attachment not found: {aid}")
            continue
        size = int(meta.get("size_bytes") or 0)
        if size > max_bytes:
            result.errors.append(
                f"attachment too large, skipped: {meta.get('file_name')} ({size} bytes)"
            )
            continue
        data = get_attachment_bytes_sync(aid)
        if data is None:
            result.errors.append(f"attachment content unreadable: {aid}")
            continue

        mime = (meta.get("mime") or "").lower()
        ext = _ext(str(meta.get("file_name") or ""))
        is_doc = not mime.startswith("image/") and ext not in pixelrag_exts
        if is_doc:
            result.has_doc_attachments = True

        try:
            payload, from_cache = _parse_one(meta, data)
            if from_cache:
                result.cached_count += 1
            else:
                result.parsed_count += 1
            nodes, imgs = _materialize(payload)
            result.text_nodes.extend(nodes)
            result.image_docs.extend(imgs)
            if not nodes and not imgs and payload.get("pipeline") != "image":
                result.errors.append(f"failed to parse attachment: {meta.get('file_name')}")
        except Exception as exc:  # noqa: BLE001
            logger.warning("failed to parse attachment %s: %s", aid, exc)
            result.errors.append(f"{meta.get('file_name')}: {exc}")

    return result
