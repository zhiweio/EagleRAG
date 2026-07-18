"""Data router: dispatch to Knowhere / PixelRAG pipelines by format + content form.

Industry-agnostic routing matrix shared across knowledge-base instances (kb_name):

    - Text PDF → Knowhere; scanned/image PDF → PixelRAG (decided by the form probe).
    - Word/Excel/CSV/PPTX/Markdown/txt/json → Knowhere.
    - Images / web URLs / HTML → PixelRAG.

There is no longer a "financial-report keyword → PixelRAG" branch; ``source_type``
is metadata only and does not influence routing.

Routing uses a strategy pattern + ``FallbackChain`` (see
``eagle_rag/ingest/selectors.py``). Extension/prefix/content_type rules and
source_type keywords are all driven by ``settings.ingest``; adding a new strategy
only requires implementing the selector protocol and inserting it into the chain,
without touching the entry function.

Override priority (high → low, matches FallbackChain order):
    1. ``PrefixSelector`` — filename prefix ``knowhere:``/``pixelrag:`` forces a
       single pipeline.
    2. ``ForcedModeSelector`` — ``settings.router.mode`` set to
       ``text``/``visual``/``hybrid`` forces the pipeline(s).
    3. ``HttpUriSelector`` — ``source_uri`` of http/https → pixelrag.
    4. ``PdfFormSelector`` — PDF form probe (``probe_pdf_form``; requires
       ``local_path``).
    5. ``ExtensionSelector`` — extension hit on the knowhere/pixelrag sets.
    6. ``ContentTypeSelector`` — sequential content_type rule matching as the
       fallback.

The Celery task ``ingest_router`` is bound to ``router_queue`` with ``with_retry``
and dispatches downstream tasks via ``app.send_task`` based on the routing
result:
    - knowhere → ``eagle_rag.tasks.knowhere_parse`` (knowhere_queue)
    - pixelrag → ``eagle_rag.tasks.pixelrag_build`` (pixelrag_queue)
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from eagle_rag.config import get_settings
from eagle_rag.index.registry import register_document
from eagle_rag.ingest.selectors import (
    ContentTypeSelector,
    ExtensionSelector,
    FallbackChain,
    ForcedModeSelector,
    HttpUriSelector,
    IngestRouteContext,
    PdfFormSelector,
    PluginHookSelector,
    PrefixSelector,
)
from eagle_rag.tasks.celery_app import app
from eagle_rag.tasks.dead_letter import retry_on_failure, with_retry
from eagle_rag.tasks.state import TaskState, update_state
from eagle_rag.telemetry import get_logger

__all__ = [
    "route",
    "probe_pdf_form",
    "infer_source_type",
    "ingest_router",
]

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Small helpers (``_strip_prefix`` takes ``prefix_force`` as a parameter; no module globals)
# ---------------------------------------------------------------------------


def _lower_ext(filename: str) -> str:
    """Return the lowercase extension (with leading dot), or empty string if none."""
    dot = filename.rfind(".")
    if dot < 0:
        return ""
    return filename[dot:].lower()


def _strip_prefix(filename: str, prefix_force: dict[str, str]) -> tuple[str, str | None]:
    """Strip ``knowhere:``/``pixelrag:`` prefix; return ``(name, forced|None)``."""
    lower = filename.lower()
    for prefix, pipeline in prefix_force.items():
        if lower.startswith(prefix):
            return filename[len(prefix) :], pipeline
    return filename, None


def _has_keyword(text: str, keywords: list[str]) -> bool:
    """Case-insensitively check whether ``text`` contains any of ``keywords``."""
    lowered = text.lower()
    return any(kw.lower() in lowered for kw in keywords)


def _is_http_uri(source_uri: str | None) -> bool:
    if not source_uri:
        return False
    try:
        parsed = urlparse(source_uri)
    except ValueError:
        return False
    return parsed.scheme.lower() in ("http", "https")


# ---------------------------------------------------------------------------
# PDF form probe
# ---------------------------------------------------------------------------


def _extract_pdf_pages_text(file_path: str) -> list[str] | None:
    """Extract text per page. Tries pypdf first, then pdfplumber; returns None on full failure."""
    # pypdf primary path
    try:
        from pypdf import PdfReader

        reader = PdfReader(file_path)
        return [page.extract_text() or "" for page in reader.pages]
    except Exception:  # noqa: BLE001
        pass

    # pdfplumber fallback path
    try:
        import pdfplumber

        with pdfplumber.open(file_path) as pdf:
            return [page.extract_text() or "" for page in pdf.pages]
    except Exception:  # noqa: BLE001
        return None


def probe_pdf_form(file_path: str, *, text_page_ratio: float | None = None) -> str:
    """PDF form probe: classify a PDF as ``"text"`` vs ``"scanned"``.

    Extracts text per page via pypdf (primary) or pdfplumber (fallback) and
    computes:
    - ``text_page_ratio``: fraction of pages whose char count exceeds the
      ``avg_chars_per_page`` threshold.
    - ``avg_chars_per_page``: mean chars per page across all pages.

    Returns ``"scanned"`` when ``text_page_ratio`` < threshold (the ``text_page_ratio``
    arg or ``settings.pdf_probe.text_page_ratio``) or when ``avg_chars_per_page``
    < ``settings.pdf_probe.avg_chars_per_page``; otherwise returns ``"text"``.

    Missing file or parse failure defaults to ``"text"`` (fallback to Knowhere,
    since text parsing degrades gracefully on scanned docs).
    """
    try:
        probe_cfg = get_settings().pdf_probe
        ratio_threshold = (
            text_page_ratio if text_page_ratio is not None else probe_cfg.text_page_ratio
        )
        chars_threshold = probe_cfg.avg_chars_per_page
    except Exception:  # noqa: BLE001
        ratio_threshold = text_page_ratio if text_page_ratio is not None else 0.2
        chars_threshold = 50

    pages_text = _extract_pdf_pages_text(file_path)
    if pages_text is None:
        return "text"

    total_pages = len(pages_text)
    if total_pages == 0:
        return "text"

    text_pages = sum(1 for t in pages_text if len(t or "") > chars_threshold)
    text_page_ratio = text_pages / total_pages
    avg_chars_per_page = sum(len(t or "") for t in pages_text) / total_pages

    if text_page_ratio < ratio_threshold or avg_chars_per_page < chars_threshold:
        return "scanned"
    return "text"


# ---------------------------------------------------------------------------
# Routing matrix (strategy pattern + FallbackChain)
# ---------------------------------------------------------------------------


def _build_context(
    filename: str,
    content_type: str | None,
    source_uri: str | None,
    local_path: str | None,
    kb_name: str | None,
    text_page_ratio: float | None,
    *,
    prefix_force: dict[str, str],
) -> IngestRouteContext:
    """Pre-compute derived fields and populate an ``IngestRouteContext``."""
    cleaned_name, forced_prefix = _strip_prefix(filename, prefix_force)
    ext = _lower_ext(cleaned_name)
    is_http = _is_http_uri(source_uri)
    return IngestRouteContext(
        filename=filename,
        cleaned_name=cleaned_name,
        ext=ext,
        content_type=content_type,
        source_uri=source_uri,
        is_http=is_http,
        local_path=local_path,
        forced_prefix=forced_prefix,
        kb_name=kb_name,
        text_page_ratio=text_page_ratio,
    )


def _build_chain(cfg: Any, *, probe: Any) -> FallbackChain:
    """Assemble the selector chain from the ``ingest.routing`` config.

    ``probe`` is the module-global ``probe_pdf_form`` (resolved at ``route()``
    call time) so that test patches of ``eagle_rag.ingest.router.probe_pdf_form``
    are picked up by the chain.
    """
    selectors: list[Any] = [
        PrefixSelector(prefix_force=cfg.prefix_force),
        PluginHookSelector(),
        ForcedModeSelector(router_mode=_router_mode()),
        HttpUriSelector(),
        PdfFormSelector(probe=probe, pdf_exts=cfg.pdf_exts),
        ExtensionSelector(
            knowhere_exts=cfg.knowhere_exts,
            pixelrag_exts=cfg.pixelrag_exts,
        ),
        ContentTypeSelector(rules=cfg.content_type_rules),
    ]
    return FallbackChain(selectors, default_pipeline=cfg.default_pipeline)


def _router_mode() -> str:
    """Read ``settings.router.mode``; fall back to ``auto`` on error."""
    try:
        return (get_settings().router.mode or "auto").lower()
    except Exception:  # noqa: BLE001
        return "auto"


def route(
    *,
    filename: str,
    content_type: str | None = None,
    source_uri: str | None = None,
    source_type_hint: str | None = None,
    local_path: str | None = None,
    kb_name: str | None = None,
    text_page_ratio: float | None = None,
) -> list[str]:
    """Decide target pipeline(s) by format + content form.

    Returns a pipeline-name list: ``["knowhere"]``, ``["pixelrag"]``, or
    ``["knowhere", "pixelrag"]``.

    Uses ``FallbackChain`` to try selectors in order; the first non-None wins
    (see module docstring for priority). Extension/prefix/content_type rules are
    driven by ``settings.ingest.routing``.

    ``source_type_hint`` and ``kb_name`` do not currently influence routing:
    ``source_type_hint`` is metadata only (see ``infer_source_type``), and
    ``kb_name`` is passed through for downstream use and future extension.
    """
    cfg = get_settings().ingest.routing
    ctx = _build_context(
        filename,
        content_type,
        source_uri,
        local_path,
        kb_name,
        text_page_ratio,
        prefix_force=cfg.prefix_force,
    )
    # probe resolves the module global each time the chain is rebuilt (patch-friendly).
    chain = _build_chain(cfg, probe=probe_pdf_form)
    return chain.select(ctx)


# ---------------------------------------------------------------------------
# source_type inference (metadata tag only; does not affect routing; config-driven)
# ---------------------------------------------------------------------------


def infer_source_type(
    filename: str,
    source_uri: str | None = None,
    source_type_hint: str | None = None,
) -> str:
    """Infer the source type.

    Returns one of the configured ``source_type`` labels or a free-form hint.
    Prefers ``source_type_hint``; otherwise first-matches against
    ``settings.ingest.source_type.rules``. Metadata only — does not affect routing.
    """
    if source_type_hint:
        hint = source_type_hint.strip().lower()
        if hint:
            return hint

    text = filename or ""
    if source_uri:
        text = f"{text} {source_uri}"

    cfg = get_settings().ingest.source_type
    for rule in cfg.rules:
        if _has_keyword(text, rule.keywords):
            return rule.source_type
    return cfg.default


# ---------------------------------------------------------------------------
# Celery task
# ---------------------------------------------------------------------------


# Downstream dispatch uses the plugin pipeline registry.


def _dispatch_pipeline(pipeline: str, downstream_kwargs: dict[str, Any]) -> None:
    from eagle_rag.plugins import get_plugin_manager

    pipe = get_plugin_manager().get_pipeline(pipeline)
    queue = pipe.queue()
    app.send_task(
        pipe.celery_task_name(),
        kwargs=dict(downstream_kwargs),
        queue=queue,
        routing_key=queue,
    )


@with_retry(queue="router_queue")
def ingest_router(  # type: ignore[no-untyped-def]
    self,
    job_id: str,
    document_id: str,
    name: str,
    object_key: str | None,
    local_path: str | None,
    source_uri: str | None,
    source_type_hint: str | None = None,
    kb_name: str | None = None,
    sha256: str | None = None,
    plugin_namespace: str | None = None,
) -> dict[str, Any]:
    """Router task: decide pipeline(s) and dispatch to downstream queues.

    Args:
        job_id: Celery task id (matches the task_audit primary key).
        document_id: Unique document id.
        name: Filename (may carry a ``knowhere:``/``pixelrag:`` prefix).
        object_key: MinIO object key (at least one of this/``local_path`` must be set).
        local_path: Local temp file path (at least one of this/``object_key`` must be set).
        source_uri: Original path/URL.
        source_type_hint: Caller-provided source-type hint (policy/financial/...; metadata only).
        kb_name: Knowledge base id; passed through to downstream and document registration.

    Flow:
        1. Mark RENDERING ("routing in progress").
        2. ``route()`` → pipelines; ``infer_source_type()`` → source_type.
        3. ``register_document()`` (with kb_name).
        4. For each pipeline, ``app.send_task`` dispatches downstream (with kb_name).
        5. Mark SUCCESS ("dispatched to {pipelines}").
        6. Each downstream adapter updates SUCCESS (single- or multi-pipeline).

    On exception, calls ``retry_on_failure(self, exc)``.
    """
    try:
        update_state(job_id, TaskState.RENDERING, log_entry="Routing decision in progress")

        from eagle_rag.db.repositories.kb import get_pdf_ratio_sync

        pdf_ratio = get_pdf_ratio_sync(kb_name)

        # Log the PDF form probe result once (only for PDFs with a local_path, for observability)
        pdf_exts = set(get_settings().ingest.routing.pdf_exts)
        if local_path and _lower_ext(name) in pdf_exts:
            try:
                form = probe_pdf_form(local_path, text_page_ratio=pdf_ratio)
            except Exception:  # noqa: BLE001
                form = "text"
            logger.info("job=%s doc=%s PDF form probe result=%s", job_id, document_id, form)

        pipelines = route(
            filename=name,
            source_uri=source_uri,
            source_type_hint=source_type_hint,
            local_path=local_path,
            kb_name=kb_name,
            text_page_ratio=pdf_ratio,
        )
        source_type = infer_source_type(
            filename=name,
            source_uri=source_uri,
            source_type_hint=source_type_hint,
        )

        from eagle_rag.db.repositories.base import instance_namespace

        plugin_ns = instance_namespace(plugin_namespace)

        register_document(
            document_id,
            name=name,
            source_type=source_type,
            pipeline=",".join(pipelines),
            kb_name=kb_name,
            source_uri=source_uri,
            status="indexing",
            plugin_namespace=plugin_ns,
        )

        downstream_kwargs = {
            "job_id": job_id,
            "document_id": document_id,
            "name": name,
            "object_key": object_key,
            "local_path": local_path,
            "source_type": source_type,
            "source_uri": source_uri,
            "kb_name": kb_name,
            "sha256": sha256,
            "plugin_namespace": plugin_ns,
        }

        from eagle_rag.tasks.state import append_log

        for pipeline in pipelines:
            try:
                _dispatch_pipeline(pipeline, downstream_kwargs)
            except KeyError:
                append_log(job_id, f"Unknown pipeline skipped: {pipeline}")

        # Downstream adapters own the job lifecycle (RENDERING→…→SUCCESS).
        # Marking SUCCESS here races with knowhere/pixelrag and is illegal once
        # the audit has already entered RENDERING.
        append_log(job_id, f"Dispatched to {pipelines}")
        return {
            "job_id": job_id,
            "document_id": document_id,
            "pipelines": pipelines,
            "source_type": source_type,
        }
    except Exception as exc:  # noqa: BLE001
        retry_on_failure(self, exc)
        # retry_on_failure raises task.retry under limit; exceeded → dead-letters, returns None.
        return {"job_id": job_id, "document_id": document_id, "error": str(exc)}
