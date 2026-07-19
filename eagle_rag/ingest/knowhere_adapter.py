"""Knowhere document parsing adapter (dual-mode SDK client + Celery task).

Knowhere supports two parse backends, selected by ``settings.knowhere.mode``:

- **api** — ``knowhere-python-sdk`` calls a self-hosted HTTP service (:5005) via
  ``Knowhere(api_key, base_url).parse(file=...)``, polling until completion.
- **parser** — ``knowhere-parse-sdk`` runs the worker pipeline in-process via
  ``KnowhereParser(config).parse(file_path)``; no :5005 service required.

Both return a type-compatible in-memory ``ParseResult`` (manifest + typed chunks +
full_markdown + raw_zip). Downstream ``chunks_to_text_nodes`` and the Celery task
``knowhere_parse`` (on ``knowhere_queue``) are backend-agnostic. SDK failures raise
``KnowhereError`` (fail-closed): the task transitions to FAILED without silent fallback.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from eagle_rag.config import get_settings
from eagle_rag.db.repositories import dedup
from eagle_rag.index.registry import update_chunk_count, update_extra, update_status
from eagle_rag.index.tag_catalog import upsert_document_keywords
from eagle_rag.plugins.pipeline import ParseContext, ParseResult
from eagle_rag.storage.minio_client import download_file
from eagle_rag.tasks.dead_letter import retry_on_failure, with_retry
from eagle_rag.tasks.state import TaskState, update_state
from eagle_rag.telemetry import get_ai_logger, get_logger, trace_span, truncate

if TYPE_CHECKING:
    from llama_index.core.schema import TextNode

__all__ = [
    "KnowhereError",
    "KnowherePipeline",
    "knowhere_parse",
    "parse_with_knowhere_sdk",
    "chunks_to_text_nodes",
    "sections_to_text_nodes",
    "build_doc_nav_tree",
    "extract_visual_chunks",
    "dispatch_visual_chunks",
    "aggregate_keyword_counts",
    "infer_level_from_path",
    "upsert_text_nodes",
]

logger = get_logger(__name__)
ai_logger = get_ai_logger(__name__)


class KnowhereError(Exception):
    """Raised when the Knowhere SDK call fails."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def infer_level_from_path(path: str) -> int:
    """Infer the nesting level from the number of ``/``-separated segments in ``path``.

    ``个税法`` → 0, ``个税法/第一章`` → 1, ``个税法/第一章/第一条`` → 2.
    Aligns with the nav-tree root node level=1 (``个税法/第一章``).
    """
    if not path:
        return 0
    return path.count("/")


def aggregate_keyword_counts(nodes: list[TextNode]) -> dict[str, int]:
    """Count keyword occurrences across a document's text nodes.

    Reads ``metadata["keywords"]`` (a list produced by Knowhere) from each node
    and returns ``{keyword: number_of_nodes_containing_it}``. Used to populate
    the ``document_keywords`` tag catalog. Blank / non-string keywords are
    ignored; a keyword is counted at most once per node.
    """
    counts: dict[str, int] = {}
    for node in nodes:
        keywords = (node.metadata or {}).get("keywords") or []
        if isinstance(keywords, str):
            keywords = [keywords]
        seen: set[str] = set()
        for kw in keywords:
            if not isinstance(kw, str):
                continue
            token = kw.strip()
            if not token or token in seen:
                continue
            seen.add(token)
            counts[token] = counts.get(token, 0) + 1
    return counts


def upsert_text_nodes(
    nodes: list[TextNode],
    *,
    plugin_namespace: str | None = None,
    kb_name: str | None = None,
    document_id: str | None = None,
) -> list[str]:
    """Write text nodes via IngestOrchestrator (test-compatible entry point)."""
    from eagle_rag.plugins.ingest_helpers import ingest_text_nodes

    settings = get_settings()
    resolved_kb = kb_name if kb_name is not None else settings.kb_name
    resolved_doc = document_id
    if not resolved_doc and nodes:
        resolved_doc = str((nodes[0].metadata or {}).get("document_id") or "")
    return ingest_text_nodes(
        nodes,
        plugin_namespace=plugin_namespace or settings.plugins.default_namespace,
        kb_name=resolved_kb,
        document_id=resolved_doc or "",
    )


def _normalize_parsing_params(params: dict) -> dict:
    """Coerce known boolean string fields in ``parsing_params`` to Python bools.

    The Knowhere SDK ``ParsingParams`` expects bools, but ``settings.yaml`` often
    provides ``"true"``/``"false"`` strings. This performs tolerant conversion for
    known boolean fields and passes ``model``/``doc_type``/``kb_dir`` through
    unchanged. Returns ``{}`` for empty input.
    """
    if not params:
        return {}
    bool_fields = {
        "ocr_enabled",
        "summary_image",
        "summary_table",
        "summary_txt",
        "smart_title_parse",
        "add_frag_desc",
    }
    out = dict(params)
    for key in bool_fields:
        if key in out and isinstance(out[key], str):
            val = out[key].strip().lower()
            if val in ("true", "1"):
                out[key] = True
            elif val in ("false", "0"):
                out[key] = False
    return out


def _parsing_params_to_parse_options(params: dict[str, Any]):
    """Map ``settings.knowhere.parsing_params`` to ``knowhere_parse.ParseOptions``."""
    from knowhere_parse import ParseOptions

    normalized = _normalize_parsing_params(params)
    if not normalized:
        return ParseOptions()

    option_fields = {
        "smart_title_parse",
        "summary_image",
        "summary_table",
        "summary_txt",
        "doc_type",
        "add_frag_desc",
        "llm_histories",
        "stopwords",
    }
    kwargs = {k: normalized[k] for k in option_fields if k in normalized}
    if "ocr_enabled" in normalized:
        logger.debug(
            "parsing_params.ocr_enabled is ignored in parser mode (MinerU handles PDF OCR)"
        )
    return ParseOptions(**kwargs)


def _sanitize_knowhere_parser_env() -> None:
    """Map Eagle-RAG ``APP_ENV`` to values accepted by knowhere-shared ``AppConfig``.

    knowhere-shared allows only ``""``, ``staging``, or ``production``. Eagle-RAG uses
    ``dev`` / ``test`` / ``prod`` for its own ``settings.app.env``; sanitize before
    bootstrapping ``knowhere-parse-sdk`` so parser mode does not fail validation.
    """
    import os

    raw = (os.environ.get("APP_ENV") or "").strip().lower()
    if raw in ("", "staging", "production"):
        return
    if raw in ("prod", "production"):
        os.environ["APP_ENV"] = "production"
        return
    if raw == "staging":
        os.environ["APP_ENV"] = "staging"
        return
    os.environ["APP_ENV"] = ""


def _build_parser_config():
    """Build ``knowhere_parse.ParserConfig`` from Eagle-RAG settings."""
    from knowhere_parse import ParserConfig

    settings = get_settings()
    kh = settings.knowhere
    parser_cfg = kh.parser
    llm = settings.llm
    vlm = settings.vlm

    tmp_path = parser_cfg.tmp_path.strip()
    if not tmp_path:
        tmp_path = str(Path(settings.storage.data_dir) / "knowhere-parse")

    llm_api_key = parser_cfg.llm_api_key or llm.api_key
    llm_url = parser_cfg.llm_url or llm.base_url
    llm_model = parser_cfg.llm_model or llm.model
    image_model = parser_cfg.image_model or vlm.model
    image_model_max = parser_cfg.image_model_max or vlm.model

    return ParserConfig(
        mineru_api_keys=parser_cfg.mineru_api_keys,
        mineru_url=parser_cfg.mineru_url,
        llm_api_key=llm_api_key,
        llm_url=llm_url,
        llm_model=llm_model,
        hierarchy_llm_model=parser_cfg.hierarchy_llm_model or "",
        image_model=image_model,
        image_model_max=image_model_max,
        tmp_path=tmp_path,
        llm_mock_enabled=parser_cfg.llm_mock_enabled,
    )


# ---------------------------------------------------------------------------
# SDK clients
# ---------------------------------------------------------------------------


def _parse_via_api_sdk(
    file_path: str,
    *,
    file_name: str,
    kb_name: str | None = None,
):  # noqa: ANN001, ARG001
    """Parse via ``knowhere-python-sdk`` (HTTP :5005)."""
    import knowhere

    settings = get_settings()
    kh = settings.knowhere
    client = knowhere.Knowhere(
        api_key=kh.api_key or None,
        base_url=kh.base_url.rstrip("/"),
        timeout=kh.timeout,
        upload_timeout=kh.upload_timeout,
        max_retries=kh.max_retries,
    )

    try:
        return client.parse(
            file=Path(file_path),
            file_name=file_name,
            parsing_params=_normalize_parsing_params(kh.parsing_params) or None,
            poll_interval=kh.poll_interval,
            poll_timeout=kh.poll_timeout,
        )
    except Exception as exc:
        logger.error(
            "Knowhere API SDK call failed (file=%s): %s",
            file_name,
            exc,
        )
        raise KnowhereError(f"Knowhere API SDK call failed (file={file_name}): {exc}") from exc


def _parse_via_parser_sdk(
    file_path: str,
    *,
    file_name: str,
    kb_name: str | None = None,
):  # noqa: ANN001, ARG001
    """Parse via ``knowhere-parse-sdk`` (in-process worker pipeline)."""
    from knowhere_parse import KnowhereParser
    from knowhere_parse.exceptions import ConfigError, OutputError, ParseError

    settings = get_settings()
    kh = settings.knowhere
    _sanitize_knowhere_parser_env()
    parser = KnowhereParser(_build_parser_config())
    options = _parsing_params_to_parse_options(kh.parsing_params)

    try:
        return parser.parse(
            file_path,
            options=options,
            use_llm_nav_summary=kh.parser.use_llm_nav_summary,
        )
    except (ConfigError, ParseError, OutputError) as exc:
        logger.error(
            "Knowhere parser SDK call failed (file=%s): %s",
            file_name,
            exc,
        )
        raise KnowhereError(f"Knowhere parser SDK call failed (file={file_name}): {exc}") from exc
    except Exception as exc:
        logger.error(
            "Knowhere parser SDK call failed (file=%s): %s",
            file_name,
            exc,
        )
        raise KnowhereError(f"Knowhere parser SDK call failed (file={file_name}): {exc}") from exc


# ---------------------------------------------------------------------------
# Public parse entry (mode dispatch)
# ---------------------------------------------------------------------------


def parse_with_knowhere_sdk(
    file_path: str,
    *,
    file_name: str,
    kb_name: str | None = None,
):  # noqa: ANN201
    """Parse a document via the configured Knowhere backend; returns in-memory ``ParseResult``.

    Dispatches to ``knowhere-python-sdk`` (``mode=api``) or ``knowhere-parse-sdk``
    (``mode=parser``) based on ``settings.knowhere.mode``. Both backends return a
    type-compatible ``ParseResult`` with ``.chunks`` / ``.text_chunks`` /
    ``.image_chunks`` / ``.table_chunks`` / ``.manifest`` / ``.full_markdown``.

    On SDK failure the function is fail-closed: logs the error and re-raises wrapped
    as ``KnowhereError``; the outer ``knowhere_parse`` handler marks the task FAILED.
    """
    mode = get_settings().knowhere.mode
    if mode == "parser":
        return _parse_via_parser_sdk(file_path, file_name=file_name, kb_name=kb_name)
    return _parse_via_api_sdk(file_path, file_name=file_name, kb_name=kb_name)


# ---------------------------------------------------------------------------
# Chunk → TextNode
# ---------------------------------------------------------------------------


def _meta(chunk, name: str, default=None):
    """Read a field from ``chunk.metadata`` (unified access for SDK and inline chunks).

    The SDK ``TextChunk`` / ``TableChunk`` / ``ImageChunk`` store summary,
    keywords, page_nums, connect_to, file_path on a nested ``metadata`` object
    (``ChunkMetadata``). Inline chunks built by ``attachments/parser.py`` mirror
    this shape via ``SimpleNamespace(metadata=...)``. This helper reads
    ``chunk.metadata.<name>`` uniformly, falling back to ``default`` when the
    attribute or value is missing/None.
    """
    meta = getattr(chunk, "metadata", None)
    val = getattr(meta, name, default) if meta is not None else default
    return val if val is not None else default


def _attach_source_ref(node: TextNode, document_id: str) -> None:
    """Bind ``document_id`` to Milvus ``doc_id`` via LlamaIndex SOURCE relationship."""
    from llama_index.core.schema import NodeRelationship, RelatedNodeInfo

    rel = dict(node.relationships or {})
    rel[NodeRelationship.SOURCE] = RelatedNodeInfo(node_id=document_id)
    node.relationships = rel


def chunks_to_text_nodes(
    parse_result,
    *,
    document_id: str,
    source_type: str,
    kb_name: str,
) -> list[TextNode]:
    """Convert Knowhere ``ParseResult.chunks`` into LlamaIndex ``TextNode``s.

    Iterates ``parse_result.chunks`` and maps content by ``type``:
    - text  → ``chunk.content``
    - table → ``chunk.html`` (top-level on ``TableChunk``; falls back to
      ``chunk.content`` when absent)
    - image → ``chunk.metadata.summary`` (falls back to ``chunk.content``)

    Preserves hierarchy path, summary, type, file_path, page_nums, keywords and
    cross-chunk relations (connect_to), and attaches ``document_id`` /
    ``source_type`` / ``kb_name`` for retrieval-time filtering.
    ``document_top_summary`` (a document-level outline summary shared by all
    chunks) is stored as a scalar metadata field so it can be returned as
    document-level context; it is deliberately NOT concatenated into ``text`` to
    avoid diluting the chunk-topic embedding. Chunk objects are accessed via
    duck typing (``getattr``), without importing SDK types.
    """
    from llama_index.core.schema import TextNode

    nodes: list[TextNode] = []
    for chunk in parse_result.chunks:
        ctype = getattr(chunk, "type", "text")
        path = getattr(chunk, "path", "") or ""
        if ctype == "table":
            text = getattr(chunk, "html", None) or getattr(chunk, "content", "")
        elif ctype == "image":
            text = _meta(chunk, "summary", "") or getattr(chunk, "content", "")
        else:
            text = getattr(chunk, "content", "")
        node = TextNode(
            text=text,
            id_=getattr(chunk, "chunk_id", None),
        )
        node.metadata = {
            "path": path,
            "level": infer_level_from_path(path),
            "summary": _meta(chunk, "summary", "") or "",
            "type": ctype,
            "file_path": _meta(chunk, "file_path", "") or "",
            "page_nums": _meta(chunk, "page_nums", []) or [],
            "keywords": _meta(chunk, "keywords", []) or [],
            "connect_to": _meta(chunk, "connect_to", []) or [],
            "document_top_summary": _meta(chunk, "document_top_summary", "") or "",
            "document_id": document_id,
            "source_type": source_type,
            "kb_name": kb_name,
        }
        _attach_source_ref(node, document_id)
        nodes.append(node)
    return nodes


def sections_to_text_nodes(
    parse_result,
    *,
    document_id: str,
    source_type: str,
    kb_name: str,
) -> list[TextNode]:
    """Convert ``ParseResult.doc_nav.sections`` section summaries into LlamaIndex ``TextNode``s.

    Walks the doc_nav section tree (recursively flattening ``children``) and emits
    a ``type="section_summary"`` TextNode for each section whose ``summary`` is
    non-empty and ``chunk_count > 0``. This enables Parent-Document Retrieval:
    first recall section-level summaries, then drill down to fine-grained chunks
    via ``path`` prefix matching.

    Section-summary chunk ``path`` shares a prefix with fine-grained chunk
    ``path`` (e.g. ``doc/3 Model Architecture`` vs
    ``doc/3 Model Architecture/3.2 Attention/...``), so retrieval can use
    ``MetadataFilter(key="path", ...)`` or prefix matching to associate parent
    and children. Sections with empty ``summary`` or ``chunk_count==0`` are
    skipped (leaf sections without content only add noise if indexed).

    ``id_`` is derived from the first 16 hex chars of SHA-1 over
    ``document_id`` + section ``path`` (``sec_{digest}``), keeping IDs stable
    across re-parses of the same document to support idempotent upsert.

    Returns an empty list when ``parse_result.doc_nav`` is absent (older SDK or
    parse failure), so the main pipeline is not blocked.
    """
    from llama_index.core.schema import TextNode

    doc_nav = getattr(parse_result, "doc_nav", None)
    if doc_nav is None:
        return []
    sections = getattr(doc_nav, "sections", None) or []
    nodes: list[TextNode] = []

    def _walk(section_list) -> None:
        for section in section_list:
            summary = (getattr(section, "summary", "") or "").strip()
            chunk_count = getattr(section, "chunk_count", 0) or 0
            path = getattr(section, "path", "") or ""
            if summary and chunk_count > 0:
                digest = hashlib.sha1(f"{document_id}:{path}".encode()).hexdigest()[:16]
                node = TextNode(
                    text=summary,
                    id_=f"sec_{digest}",
                )
                node.metadata = {
                    "path": path,
                    "level": getattr(section, "level", 1),
                    "summary": summary,
                    "type": "section_summary",
                    "document_id": document_id,
                    "source_type": source_type,
                    "kb_name": kb_name,
                    "chunk_count": chunk_count,
                }
                _attach_source_ref(node, document_id)
                nodes.append(node)
            children = getattr(section, "children", None) or []
            if children:
                _walk(children)

    _walk(sections)
    return nodes


def build_doc_nav_tree(
    parse_result,
    *,
    max_nodes: int = 2000,
    summary_cap: int = 400,
) -> list[dict]:
    """Build a trimmed, JSON-serializable section tree from ``ParseResult.doc_nav``.

    Preserves the SDK hierarchy so the API can serve a document's parsed semantic
    structure without a re-parse. Each node is
    ``{path, level, title, summary, chunk_count, children}``; ``summary`` is
    truncated to ``summary_cap`` chars and the total node count is bounded by
    ``max_nodes``. Returns an empty list when ``doc_nav`` is absent.

    Args:
        parse_result: Knowhere ``ParseResult`` (may lack ``doc_nav``).
        max_nodes: Upper bound on emitted section nodes.
        summary_cap: Max characters retained per section summary.

    Returns:
        A nested list of section dicts (document roots).
    """
    doc_nav = getattr(parse_result, "doc_nav", None)
    if doc_nav is None:
        return []
    sections = getattr(doc_nav, "sections", None) or []
    remaining = {"n": max_nodes}

    def _node(section) -> dict | None:
        if remaining["n"] <= 0:
            return None
        remaining["n"] -= 1
        path = getattr(section, "path", "") or ""
        summary = (getattr(section, "summary", "") or "").strip()
        if len(summary) > summary_cap:
            summary = summary[:summary_cap]
        title = (getattr(section, "title", "") or "").strip()
        if not title and path:
            title = path.split("/")[-1].strip()
        children_out: list[dict] = []
        for child in getattr(section, "children", None) or []:
            built = _node(child)
            if built is not None:
                children_out.append(built)
        return {
            "path": path,
            "level": getattr(section, "level", 1),
            "title": title,
            "summary": summary,
            "chunk_count": getattr(section, "chunk_count", 0) or 0,
            "children": children_out,
        }

    out: list[dict] = []
    for section in sections:
        built = _node(section)
        if built is not None:
            out.append(built)
    return out


def extract_visual_chunks(parse_result) -> list[dict]:
    """Extract visual chunks (image/table) from ``ParseResult.chunks``.

    Iterates ``parse_result.chunks`` in original order, tracking the most recent
    text chunk's ``path`` as ``parent_section``: each ``type=="text"`` chunk
    updates ``parent_section`` to its ``path``; each ``type=="image"`` or
    ``type=="table"`` chunk produces a visual-chunk descriptor dict appended to
    the result.

    Each returned dict contains:
        - ``chunk_id``: chunk id (``getattr(chunk, "chunk_id", None)``)
        - ``type``: ``"image"`` or ``"table"``
        - ``data``: image bytes (``getattr(chunk, "data", None)``); ``None`` for tables
        - ``html``: table HTML string (``getattr(chunk, "html", None) or
          getattr(chunk, "content", "")``); ``None`` for images
        - ``summary``: visual summary (``_meta(chunk, "summary", "")``)
        - ``parent_section``: ``path`` of the current enclosing text chunk
        - ``file_path``: ``_meta(chunk, "file_path", "")``

    Other chunk types (e.g. text) are skipped and only used to update
    ``parent_section``.
    """
    visual_chunks: list[dict] = []
    parent_section = ""
    for chunk in parse_result.chunks:
        ctype = getattr(chunk, "type", "text")
        if ctype == "text":
            parent_section = getattr(chunk, "path", "") or ""
            continue
        if ctype in ("image", "table"):
            if ctype == "image":
                data = getattr(chunk, "data", None)
                html = None
            else:
                data = None
                html = getattr(chunk, "html", None) or getattr(chunk, "content", "")
            visual_chunks.append(
                {
                    "chunk_id": getattr(chunk, "chunk_id", None),
                    "type": ctype,
                    "data": data,
                    "html": html,
                    "summary": _meta(chunk, "summary", "") or "",
                    "parent_section": parent_section,
                    "file_path": _meta(chunk, "file_path", "") or "",
                }
            )
    return visual_chunks


def dispatch_visual_chunks(
    job_id: str,
    document_id: str,
    visual_chunks: list[dict],
    *,
    kb_name: str | None,
    source_type: str,
) -> None:
    """Upload visual chunks to MinIO and dispatch the ``knowhere_visual_chunks`` Celery subtask.

    Flow:
        1. For each visual chunk:
           - image: ``object_key = {document_id}/visual_chunks/{chunk_id}.{ext}``,
             where ``ext`` is inferred from ``file_path`` (e.g. ``.jpg``),
             defaulting to ``.png``; uploads ``chunk["data"]`` bytes with
             ``content_type="image/jpeg"``.
           - table: ``object_key = {document_id}/visual_chunks/{chunk_id}.html``;
             uploads ``chunk["html"].encode("utf-8")`` with
             ``content_type="text/html"``.
        2. Builds a byte-free serializable chunk descriptor dict
           (``chunk_id``/``type``/``object_key``/``summary``/``parent_section``/
           ``file_path``).
        3. Dispatches via ``app.send_task`` to ``pixelrag_queue``.

    Any failure is logged and the function returns ``None`` without raising —
    visual dispatch failure must not block the ``knowhere_parse`` main pipeline
    (the document is still marked ready).
    """
    try:
        from eagle_rag.storage.minio_client import ensure_bucket, upload_bytes

        ensure_bucket()
        chunk_descriptors: list[dict] = []
        for chunk in visual_chunks:
            chunk_id = chunk["chunk_id"]
            ctype = chunk["type"]
            if ctype == "image":
                ext = ".png"
                file_path = chunk.get("file_path", "") or ""
                suffix = Path(file_path).suffix
                if suffix:
                    ext = suffix.lower()
                object_key = f"{document_id}/visual_chunks/{chunk_id}{ext}"
                upload_bytes(
                    object_key,
                    chunk["data"] or b"",
                    content_type="image/jpeg",
                )
            else:  # table
                object_key = f"{document_id}/visual_chunks/{chunk_id}.html"
                upload_bytes(
                    object_key,
                    (chunk["html"] or "").encode("utf-8"),
                    content_type="text/html",
                )
            chunk_descriptors.append(
                {
                    "chunk_id": chunk_id,
                    "type": ctype,
                    "object_key": object_key,
                    "summary": chunk["summary"],
                    "parent_section": chunk["parent_section"],
                    "file_path": chunk["file_path"],
                }
            )

        from eagle_rag.tasks.celery_app import app

        # Use a dedicated sub-job_id so the visual-chunks task has its own
        # state-machine lifecycle. Sharing the parent job_id would conflict
        # with knowhere_parse's SUCCESS terminal state (success→rendering is
        # illegal), causing infinite Celery retries.
        visual_job_id = f"{job_id}:visual"

        app.send_task(
            "eagle_rag.tasks.knowhere_visual_chunks",
            kwargs={
                "job_id": visual_job_id,
                "parent_job_id": job_id,
                "document_id": document_id,
                "kb_name": kb_name,
                "source_type": source_type,
                "chunks": chunk_descriptors,
            },
            queue="pixelrag_queue",
            routing_key="pixelrag_queue",
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "dispatch_visual_chunks failed job=%s doc=%s: %s",
            job_id,
            document_id,
            exc,
            exc_info=True,
        )
        return None


# ---------------------------------------------------------------------------
# Ingest pipeline wrapper
# ---------------------------------------------------------------------------


class KnowherePipeline:
    """Registered knowhere ingest pipeline (minimal Celery dispatch wrapper)."""

    name = "knowhere"

    def celery_task_name(self) -> str:
        return "eagle_rag.tasks.knowhere_parse"

    def queue(self) -> str:
        return "knowhere_queue"

    def parse(self, ctx: ParseContext) -> ParseResult:
        from eagle_rag.plugins.hotpath_hooks import apply_parse_hook

        raw = parse_with_knowhere_sdk(
            ctx.file_path,
            file_name=ctx.file_name,
            kb_name=ctx.kb_name,
        )
        raw = apply_parse_hook(
            raw,
            file_path=ctx.file_path,
            file_name=ctx.file_name,
            plugin_namespace=get_settings().plugins.default_namespace,
            kb_name=ctx.kb_name,
            document_id=ctx.document_id,
        )
        chunks = getattr(raw, "chunks", None) or []
        return ParseResult(raw=raw, pipeline=self.name, chunk_count=len(chunks))

    def to_nodes(self, parse_result: ParseResult, ctx: ParseContext) -> list[Any]:
        from eagle_rag.plugins.hotpath_hooks import apply_chunk_hook

        nodes = chunks_to_text_nodes(
            parse_result.raw,
            document_id=ctx.document_id,
            source_type=ctx.source_type,
            kb_name=ctx.kb_name,
        )
        section_nodes = sections_to_text_nodes(
            parse_result.raw,
            document_id=ctx.document_id,
            source_type=ctx.source_type,
            kb_name=ctx.kb_name,
        )
        nodes.extend(section_nodes)
        return apply_chunk_hook(
            nodes,
            file_path=ctx.file_path,
            file_name=ctx.file_name,
            plugin_namespace=get_settings().plugins.default_namespace,
            kb_name=ctx.kb_name,
            document_id=ctx.document_id,
        )


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------


@with_retry(name="eagle_rag.tasks.knowhere_parse", queue="knowhere_queue", bind=True)
def knowhere_parse(  # noqa: ANN001
    self,
    job_id: str,
    document_id: str,
    name: str,
    object_key: str | None = None,
    local_path: str | None = None,
    source_type: str = "policy",
    source_uri: str | None = None,
    kb_name: str | None = None,
    sha256: str | None = None,
    plugin_namespace: str | None = None,
) -> None:
    """Knowhere pipeline: fetch file → SDK parse → vectorize → Milvus → update registry.

    Args:
        job_id: Celery task id (maps to ``task_audit.job_id``).
        document_id: Document registry primary key.
        name: Display name (used as Knowhere upload ``file_name``).
        object_key: MinIO object key (mutually exclusive with ``local_path``).
        local_path: Local file path (preferred to avoid re-download).
        source_type: Source type (policy/financial/business/bidding/tax/other).
        source_uri: Original source URI (logging only).
        kb_name: Knowledge base id; falls back to ``settings.kb_name`` when None.
        plugin_namespace: Plugin namespace from the router; defaults to instance binding.
    """
    from eagle_rag.db.repositories.base import instance_namespace

    effective_kb = kb_name if kb_name is not None else get_settings().kb_name
    ns = instance_namespace(plugin_namespace)

    from eagle_rag.tasks.state import get_audit, prepare_rerun

    existing = get_audit(job_id)
    if existing is not None:
        if (existing.get("status") or "").lower() == TaskState.SUCCESS.value:
            return
        # Worker restart / Celery redelivery leaves audits mid-pipeline
        # (embedding/indexing). prepare_rerun bridges to a legal RENDERING entry.
        prepare_rerun(job_id)

    try:
        with trace_span("ingest.knowhere"):
            t0 = time.monotonic()
            update_state(
                job_id,
                TaskState.RENDERING,
                log_entry=f"Knowhere parsing source_uri={source_uri}",
            )

            # 1. Resolve a local file path.
            if local_path:
                file_path = local_path
            else:
                if not object_key:
                    raise ValueError("object_key or local_path is required")
                data_dir = Path(get_settings().storage.data_dir)
                data_dir.mkdir(parents=True, exist_ok=True)
                tmp_path = data_dir / f"knowhere_{document_id}_{Path(object_key).name}"
                download_file(object_key, tmp_path)
                file_path = str(tmp_path)

            # 1b. Defense-in-depth: reject oversize / over-page PDFs before MinerU.
            # Permanent failures — return without raising so Celery does not retry.
            from eagle_rag.ingest.limits import IngestLimitError, validate_ingest_file

            try:
                validate_ingest_file(Path(file_path), name)
            except IngestLimitError as limit_exc:
                try:
                    ai_logger.info(
                        "ingest",
                        job_id=job_id,
                        document_id=document_id,
                        pipeline="knowhere",
                        kb_name=effective_kb,
                        status="failed",
                        error=truncate(str(limit_exc), 256),
                        duration_ms=int((time.monotonic() - t0) * 1000),
                    )
                except Exception:  # noqa: BLE001
                    logger.debug("telemetry emit failed", exc_info=True)
                update_state(job_id, TaskState.FAILED, error=str(limit_exc))
                return

            # 2. Parse via Knowhere SDK; KnowhereError bubbles up → outer handler marks FAILED.
            parse_result = parse_with_knowhere_sdk(file_path, kb_name=effective_kb, file_name=name)

            from eagle_rag.plugins.hotpath_hooks import apply_chunk_hook, apply_parse_hook

            parse_result = apply_parse_hook(
                parse_result,
                file_path=str(file_path),
                file_name=name,
                plugin_namespace=ns,
                kb_name=effective_kb,
                document_id=document_id,
            )

            # 3. Vectorization stage.
            chunk_count = len(getattr(parse_result, "chunks", None) or [])
            update_state(
                job_id,
                TaskState.EMBEDDING,
                current=0,
                total=chunk_count,
                log_entry=f"Parse complete, {chunk_count} chunks",
            )

            # 4. Chunk → TextNode.
            nodes = chunks_to_text_nodes(
                parse_result,
                document_id=document_id,
                source_type=source_type,
                kb_name=effective_kb,
            )
            # 4.5 Section summaries → TextNode (parent-doc retrieval via path prefix).
            section_nodes = sections_to_text_nodes(
                parse_result,
                document_id=document_id,
                source_type=source_type,
                kb_name=effective_kb,
            )
            nodes.extend(section_nodes)
            nodes = apply_chunk_hook(
                nodes,
                file_path=str(file_path),
                file_name=name,
                plugin_namespace=ns,
                kb_name=effective_kb,
                document_id=document_id,
            )

            # 5. Write Milvus text index (failure bubbles up → FAILED; no silent success).
            update_state(job_id, TaskState.INDEXING, log_entry="Writing Milvus text index")
            from eagle_rag.plugins.ingest_tracker import (
                clear_ingest_collections,
                snapshot_ingest_collections,
            )

            clear_ingest_collections()
            upsert_text_nodes(
                nodes,
                plugin_namespace=get_settings().plugins.default_namespace,
                kb_name=effective_kb,
                document_id=document_id,
            )

            # 5.2 Populate the keyword (tag) catalog from chunk keywords. Non-blocking:
            # a catalog write failure must not fail the ingest (Milvus already written).
            try:
                keyword_counts = aggregate_keyword_counts(nodes)
                upsert_document_keywords(
                    document_id,
                    effective_kb,
                    keyword_counts,
                    plugin_namespace=get_settings().plugins.default_namespace,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "tag catalog write failed (non-blocking) doc=%s: %s",
                    document_id,
                    exc,
                )

            # 5.5 Extract visual chunks; dispatch to pixelrag_queue (failure is non-blocking).
            try:
                from eagle_rag.plugins import get_plugin_manager
                from eagle_rag.plugins.hookbus import HookContext
                from eagle_rag.plugins.hooks import Hook

                mgr = get_plugin_manager()
                hook_ctx = HookContext(
                    plugin_namespace=ns,
                    kb_name=effective_kb,
                    document_id=document_id,
                )
                visual_chunks = mgr.bus.invoke_first(
                    Hook.INGEST_VISUAL_EXTRACT,
                    hook_ctx,
                    parse_result,
                )
                if visual_chunks is None:
                    visual_chunks = extract_visual_chunks(parse_result)
                if visual_chunks:
                    dispatch_visual_chunks(
                        job_id,
                        document_id,
                        visual_chunks,
                        kb_name=effective_kb,
                        source_type=source_type,
                    )
                    logger.info(
                        "job=%s doc=%s dispatched %d visual chunks to pixelrag_queue",
                        job_id,
                        document_id,
                        len(visual_chunks),
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("visual chunk dispatch failed (non-blocking): %s", exc)

            # 5.7 Persist the parsed semantic tree to documents.extra (non-blocking):
            # a doc_nav write failure must not fail the ingest.
            try:
                max_nodes = getattr(get_settings().router, "structure_max_nodes", 2000)
                doc_nav_tree = build_doc_nav_tree(parse_result, max_nodes=max_nodes)
                if doc_nav_tree:
                    update_extra(document_id, {"doc_nav": doc_nav_tree})
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "doc_nav persistence failed (non-blocking) doc=%s: %s",
                    document_id,
                    exc,
                )

            # 6. Update the registry.
            update_chunk_count(document_id, len(nodes))
            update_status(document_id, "ready")

            settings_ns = get_settings()
            collections = snapshot_ingest_collections()
            if not collections:
                collections = [settings_ns.milvus.text_collection]
            if visual_chunks:
                collections = sorted(set(collections) | {settings_ns.milvus.visual_collection})

            from eagle_rag.plugins.ingest_catalog import commit_ingest_catalog

            commit_ingest_catalog(
                document_id,
                effective_kb,
                collections,
                plugin_namespace=ns,
            )

            # 7. Done.
            update_state(
                job_id,
                TaskState.SUCCESS,
                current=len(nodes),
                total=len(nodes),
                progress=100,
                log_entry=(
                    f"Knowhere pipeline complete ({len(parse_result.chunks)} chunks"
                    f" + {len(section_nodes)} sections)"
                ),
            )

            # Register dedup only after successful parse + index.
            # If the task fails, no dedup record is left behind, so re-uploading
            # the same file won't be mistakenly treated as a duplicate.
            if sha256:
                try:
                    dedup.register(
                        sha256,
                        document_id,
                        kb_name=effective_kb,
                        object_key=object_key,
                        source_name=name,
                    )
                except Exception:  # noqa: BLE001
                    logger.warning("dedup register failed (non-fatal): %s", exc_info=True)

            try:
                ai_logger.info(
                    "ingest",
                    job_id=job_id,
                    document_id=document_id,
                    pipeline="knowhere",
                    kb_name=effective_kb,
                    source_type=source_type,
                    name=truncate(name, 128),
                    chunks=len(nodes),
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
                pipeline="knowhere",
                kb_name=effective_kb,
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
