"""KB statistics aggregation.

Aggregates documents, graph nodes, vector entities, ingestion trends, and facets.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from eagle_rag.config import get_settings
from eagle_rag.db import async_fetch, async_fetchrow
from eagle_rag.telemetry import get_logger

logger = get_logger(__name__)

__all__ = [
    "get_kb_stats",
    "get_overview",
    "get_format_distribution",
    "get_ingestion_volume",
    "get_collections",
    "get_facets",
    "count_queries_7d",
]

_WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Stable segment keys aligned with ingest routing (Knowhere vs PixelRAG).
_EXT_FORMAT_KEYS: dict[str, str] = {
    ".docx": "docx",
    ".doc": "docx",
    ".pptx": "pptx",
    ".xlsx": "xlsx",
    ".xls": "xlsx",
    ".csv": "csv",
    ".md": "md",
    ".markdown": "md",
    ".txt": "txt",
    ".json": "json",
    ".html": "web",
    ".htm": "web",
    ".jpg": "image",
    ".jpeg": "image",
    ".png": "image",
    ".webp": "image",
    ".gif": "image",
    ".bmp": "image",
    ".tiff": "image",
    ".tif": "image",
}

_FORMAT_CATALOG: list[tuple[str, str, str]] = [
    ("pdf_text", "PDF (text)", "#3B82F6"),
    ("pdf_scan", "PDF (scanned)", "#A855F7"),
    ("docx", "Word (.docx)", "#0EA5E9"),
    ("pptx", "PowerPoint (.pptx)", "#F97316"),
    ("xlsx", "Excel (.xlsx)", "#FBBF24"),
    ("csv", "CSV", "#84CC16"),
    ("md", "Markdown", "#14B8A6"),
    ("txt", "Text (.txt)", "#64748B"),
    ("json", "JSON", "#6366F1"),
    ("web", "Web/HTML", "#10B981"),
    ("image", "Image", "#F43F5E"),
    ("other", "Other", "#9CA3AF"),
]


def _lower_ext(name: str) -> str:
    dot = name.rfind(".")
    if dot < 0:
        return ""
    return name[dot:].lower()


def _is_http_uri(source_uri: str | None) -> bool:
    if not source_uri:
        return False
    try:
        parsed = urlparse(source_uri)
    except ValueError:
        return False
    return parsed.scheme.lower() in ("http", "https")


def _classify_format(*, name: str, pipeline: str, source_uri: str | None) -> str:
    """Map a ready document to a format-distribution bucket key."""
    lower_name = (name or "").lower()
    ext = _lower_ext(lower_name)
    pipeline_l = (pipeline or "").lower()

    if ext == ".pdf":
        if "pixelrag" in pipeline_l and "knowhere" not in pipeline_l:
            return "pdf_scan"
        return "pdf_text"

    if ext_key := _EXT_FORMAT_KEYS.get(ext):
        return ext_key

    if _is_http_uri(source_uri) or "html" in pipeline_l:
        return "web"

    return "other"


async def _doc_stats(kb_name: str) -> dict[str, int]:
    """Document and graph-node counts for a single KB."""
    row = await async_fetchrow(
        """
        SELECT
          COUNT(*)::int AS documents,
          COALESCE(SUM(chunk_count) FILTER (
            WHERE pipeline LIKE '%knowhere%' AND status = 'ready'
          ), 0)::int AS graph_nodes,
          COALESCE(SUM(chunk_count) FILTER (
            WHERE pipeline LIKE '%pixelrag%' AND status = 'ready'
          ), 0)::int AS visual_slices_fallback
        FROM documents
        WHERE kb_name = $1
        """,
        kb_name,
    )
    if row is None:
        return {"documents": 0, "graph_nodes": 0, "visual_slices_fallback": 0}
    return {
        "documents": int(row["documents"] or 0),
        "graph_nodes": int(row["graph_nodes"] or 0),
        "visual_slices_fallback": int(row["visual_slices_fallback"] or 0),
    }


async def _active_ingestions(kb_name: str | None = None) -> int:
    """Count of in-progress ingestion tasks."""
    if kb_name:
        row = await async_fetchrow(
            """
            SELECT COUNT(*)::int AS cnt FROM task_audit
            WHERE kb_name = $1 AND status NOT IN ('success', 'failed')
            """,
            kb_name,
        )
    else:
        row = await async_fetchrow(
            """
            SELECT COUNT(*)::int AS cnt FROM task_audit
            WHERE status NOT IN ('success', 'failed')
            """
        )
    return int(row["cnt"] or 0) if row else 0


def _count_visual_safe(kb_name: str) -> int:
    try:
        from eagle_rag.index.milvus_visual_store import count_visual

        return count_visual(kb_name=kb_name)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Milvus visual count failed kb=%s: %s", kb_name, exc)
        return 0


def _count_text_safe(kb_name: str) -> int:
    try:
        from eagle_rag.index.milvus_text_store import count_text

        return count_text(kb_name=kb_name)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Milvus text count failed kb=%s: %s", kb_name, exc)
        return 0


async def count_queries_7d(kb_name: str) -> int:
    """User query message count for this KB in the last 7 days."""
    row = await async_fetchrow(
        """
        SELECT COUNT(*)::int AS cnt FROM messages
        WHERE kb_name = $1 AND role = 'user'
          AND created_at >= NOW() - INTERVAL '7 days'
        """,
        kb_name,
    )
    return int(row["cnt"] or 0) if row else 0


def _milvus_collections_for_kb(kb_name: str) -> list[str]:
    """Return the list of Milvus collections actually present for this KB (best-effort)."""
    try:
        from pymilvus import MilvusClient
    except ImportError:
        return []
    cfg = get_settings().milvus
    client = MilvusClient(uri=f"http://{cfg.host}:{cfg.port}")
    result: list[str] = []
    try:
        for name in [cfg.text_collection, cfg.visual_collection]:
            try:
                if client.has_collection(name):
                    result.append(name)
            except Exception:  # noqa: BLE001
                logger.warning("Milvus has_collection failed %s", name)
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass
    return result


async def get_kb_stats(kb_name: str) -> dict[str, Any]:
    """Per-KB list-item stats: documents/graph_nodes/visual_slices/active_ingestions."""
    doc = await _doc_stats(kb_name)
    visual = _count_visual_safe(kb_name)
    if visual == 0:
        visual = doc["visual_slices_fallback"]
    return {
        "documents": doc["documents"],
        "graph_nodes": doc["graph_nodes"],
        "visual_slices": visual,
        "active_ingestions": await _active_ingestions(kb_name),
        "collections": _milvus_collections_for_kb(kb_name),
    }


async def get_overview() -> dict[str, Any]:
    """Aggregate across all KBs."""
    kb_row = await async_fetchrow("SELECT COUNT(*)::int AS cnt FROM knowledge_bases")
    kb_count = int(kb_row["cnt"] or 0) if kb_row else 0

    doc_row = await async_fetchrow(
        """
        SELECT
          COUNT(*)::int AS total_documents,
          COALESCE(SUM(chunk_count) FILTER (
            WHERE pipeline LIKE '%knowhere%' AND status = 'ready'
          ), 0)::int AS total_graph_nodes
        FROM documents d
        INNER JOIN knowledge_bases kb ON d.kb_name = kb.kb_name
        """
    )
    total_documents = int(doc_row["total_documents"] or 0) if doc_row else 0
    total_graph_nodes = int(doc_row["total_graph_nodes"] or 0) if doc_row else 0

    total_vectors = 0
    kbs = await async_fetch("SELECT kb_name FROM knowledge_bases")
    for r in kbs:
        kn = r["kb_name"]
        total_vectors += _count_text_safe(kn) + _count_visual_safe(kn)

    return {
        "kb_count": kb_count,
        "active_ingestions": await _active_ingestions(),
        "total_documents": total_documents,
        "total_graph_nodes": total_graph_nodes,
        "total_vectors": total_vectors,
    }


async def get_format_distribution(kb_name: str) -> dict[str, Any]:
    """Document format distribution (donut chart data)."""
    rows = await async_fetch(
        """
        SELECT pipeline, name, source_uri
        FROM documents
        WHERE kb_name = $1 AND status = 'ready'
        """,
        kb_name,
    )
    buckets = {key: 0 for key, _, _ in _FORMAT_CATALOG}
    for r in rows:
        fmt_key = _classify_format(
            name=r["name"] or "",
            pipeline=r["pipeline"] or "",
            source_uri=r.get("source_uri"),
        )
        buckets[fmt_key] = buckets.get(fmt_key, 0) + 1

    total = sum(buckets.values()) or 1
    segments: list[dict[str, Any]] = []
    for key, label, color in _FORMAT_CATALOG:
        count = buckets.get(key, 0)
        if count == 0:
            continue
        segments.append(
            {
                "key": key,
                "label": label,
                "value": round(count / total * 100),
                "color": color,
            }
        )
    return {"segments": segments}


async def get_ingestion_volume(kb_name: str, *, days: int = 7) -> dict[str, Any]:
    """Aggregate successful ingestion counts per day."""
    start = datetime.now(UTC) - timedelta(days=days - 1)
    rows = await async_fetch(
        """
        SELECT DATE(created_at AT TIME ZONE 'UTC') AS day, COUNT(*)::int AS cnt
        FROM task_audit
        WHERE kb_name = $1 AND status = 'success'
          AND created_at >= $2
        GROUP BY day
        ORDER BY day
        """,
        kb_name,
        start,
    )
    by_day = {str(r["day"]): int(r["cnt"]) for r in rows}
    points: list[dict[str, Any]] = []
    peak = 0
    for i in range(days):
        d = (start + timedelta(days=i)).date()
        key = str(d)
        value = by_day.get(key, 0)
        peak = max(peak, value)
        wd = d.weekday()
        points.append(
            {
                "date": key,
                "label": _WEEKDAY_LABELS[wd],
                "value": value,
            }
        )
    return {"unit": "docs", "peak": peak, "points": points}


def _capacity_ratio(entities: int, collection: str) -> float:
    """Estimate capacity ratio against the configured upper limit."""
    settings = get_settings()
    limits = {
        "eagle_text": settings.kb.text_entity_limit,
        "eagle_visual": settings.kb.visual_entity_limit,
    }
    limit = limits.get(collection, 500_000)
    return round(min(1.0, entities / limit), 2) if limit > 0 else 0.0


async def get_collections(kb_name: str) -> dict[str, Any]:
    """Storage watermarks of the two Milvus collections."""
    settings = get_settings()
    cfg = settings.milvus
    text_entities = _count_text_safe(kb_name)
    visual_entities = _count_visual_safe(kb_name)

    return {
        "collections": [
            {
                "name": "eagle_text",
                "model": settings.embedding.text.model,
                "dim": cfg.dim_text,
                "index": "hnsw",
                "entities": text_entities,
                "capacity_ratio": _capacity_ratio(text_entities, "eagle_text"),
            },
            {
                "name": "eagle_visual",
                "model": settings.embedding.visual.model,
                "dim": cfg.dim_visual,
                "index": cfg.visual_index_type,
                "entities": visual_entities,
                "capacity_ratio": _capacity_ratio(visual_entities, "eagle_visual"),
            },
        ],
    }


async def get_facets(kb_name: str) -> dict[str, Any]:
    """Optional facets for retrieval scope filtering."""
    st_rows = await async_fetch(
        "SELECT DISTINCT source_type FROM documents WHERE kb_name = $1 ORDER BY 1",
        kb_name,
    )
    pl_rows = await async_fetch(
        """
        SELECT DISTINCT unnest(string_to_array(pipeline, ',')) AS p
        FROM documents WHERE kb_name = $1
        ORDER BY 1
        """,
        kb_name,
    )
    years: list[int] = []
    try:
        from eagle_rag.index.milvus_visual_store import distinct_years

        years = distinct_years(kb_name=kb_name)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Milvus distinct years failed: %s", exc)

    return {
        "source_type": [r["source_type"] for r in st_rows if r["source_type"]],
        "pipeline": [r["p"].strip() for r in pl_rows if r["p"] and r["p"].strip()],
        "year": years,
    }
