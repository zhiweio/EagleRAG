"""Knowledge base management REST API (``/knowledge_bases*``)."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from eagle_rag.api.schemas.knowledge_bases import (
    KBCollectionsResponse,
    KBCreate,
    KBDeleteResponse,
    KBDetailOut,
    KBFacetsResponse,
    KBFormatDistributionResponse,
    KBIngestionVolumeResponse,
    KBItem,
    KBKpi,
    KBListResponse,
    KBOverviewResponse,
    KBUpdate,
    RebuildResponse,
)
from eagle_rag.kb import health, lifecycle, registry, stats
from eagle_rag.telemetry import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["knowledge_bases"])


def _kb_item(meta: dict[str, Any], item_stats: dict[str, Any]) -> KBItem:
    return KBItem(
        kb_name=meta["kb_name"],
        display_name=meta["display_name"],
        description=meta.get("description", ""),
        theme=meta.get("theme", "blue"),
        icon=meta.get("icon", "landmark"),
        pdf_text_page_ratio=float(meta.get("pdf_text_page_ratio", 0.2)),
        documents=item_stats["documents"],
        graph_nodes=item_stats["graph_nodes"],
        visual_slices=item_stats["visual_slices"],
        collections=item_stats.get("collections", ["eagle_text", "eagle_visual"]),
        active_ingestions=item_stats["active_ingestions"],
        updated_at=meta.get("updated_at"),
    )


@router.get("/knowledge_bases", response_model=KBListResponse)
async def list_knowledge_bases(
    query: str | None = Query(None),
    sort: str = Query("recent", pattern="^(recent|name|size)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> KBListResponse:
    """List all registered knowledge bases with stats."""
    try:
        rows, total = await registry.list_kbs(
            query=query,
            sort=sort,
            limit=limit,
            offset=offset,
        )
        items: list[KBItem] = []
        for meta in rows:
            st = await stats.get_kb_stats(meta["kb_name"])
            items.append(_kb_item(meta, st))
        return KBListResponse(items=items, total=total)
    except Exception as exc:  # noqa: BLE001
        logger.exception("list_knowledge_bases failed")
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/knowledge_bases/overview", response_model=KBOverviewResponse)
async def knowledge_bases_overview() -> KBOverviewResponse:
    """Cross-KB aggregate metrics."""
    try:
        return KBOverviewResponse.model_validate(await stats.get_overview())
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/knowledge_bases", response_model=KBItem, status_code=201)
async def create_knowledge_base(body: KBCreate) -> KBItem:
    """Create a knowledge base namespace."""
    if not registry.KB_NAME_PATTERN.match(body.kb_name):
        raise HTTPException(
            status_code=422, detail="kb_name allows only lowercase letters, digits, and underscores"
        )
    if await registry.kb_exists(body.kb_name):
        raise HTTPException(status_code=409, detail=f"kb_name already exists: {body.kb_name}")
    try:
        meta = await registry.create_kb(
            kb_name=body.kb_name,
            display_name=body.display_name,
            description=body.description,
            theme=body.theme,
            icon=body.icon,
            pdf_text_page_ratio=body.pdf_text_page_ratio,
        )
        st = await stats.get_kb_stats(body.kb_name)
        return _kb_item(meta, st)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/knowledge_bases/{kb_name}", response_model=KBDetailOut)
async def get_knowledge_base(kb_name: str) -> KBDetailOut:
    """Knowledge base detail with KPIs."""
    meta = await registry.get_kb(kb_name)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"knowledge base not found: {kb_name}")
    st = await stats.get_kb_stats(kb_name)
    queries_7d = await stats.count_queries_7d(kb_name)
    base = _kb_item(meta, st)
    try:
        kb_status = await health.compute_kb_status(kb_name)
    except Exception:  # noqa: BLE001
        kb_status = "degraded"
    return KBDetailOut(
        **base.model_dump(),
        status=kb_status,
        kpi=KBKpi(
            documents=st["documents"],
            graph_nodes=st["graph_nodes"],
            visual_slices=st["visual_slices"],
            queries_7d=queries_7d,
        ),
    )


@router.get(
    "/knowledge_bases/{kb_name}/format-distribution",
    response_model=KBFormatDistributionResponse,
)
async def kb_format_distribution(kb_name: str) -> KBFormatDistributionResponse:
    if not await registry.kb_exists(kb_name):
        raise HTTPException(status_code=404, detail=f"knowledge base not found: {kb_name}")
    return KBFormatDistributionResponse.model_validate(
        await stats.get_format_distribution(kb_name),
    )


@router.get(
    "/knowledge_bases/{kb_name}/ingestion-volume",
    response_model=KBIngestionVolumeResponse,
)
async def kb_ingestion_volume(
    kb_name: str,
    days: int = Query(7, ge=1, le=90),
) -> KBIngestionVolumeResponse:
    if not await registry.kb_exists(kb_name):
        raise HTTPException(status_code=404, detail=f"knowledge base not found: {kb_name}")
    return KBIngestionVolumeResponse.model_validate(
        await stats.get_ingestion_volume(kb_name, days=days),
    )


@router.get("/knowledge_bases/{kb_name}/collections", response_model=KBCollectionsResponse)
async def kb_collections(kb_name: str) -> KBCollectionsResponse:
    if not await registry.kb_exists(kb_name):
        raise HTTPException(status_code=404, detail=f"knowledge base not found: {kb_name}")
    return KBCollectionsResponse.model_validate(await stats.get_collections(kb_name))


@router.get("/knowledge_bases/{kb_name}/facets", response_model=KBFacetsResponse)
async def kb_facets(kb_name: str) -> KBFacetsResponse:
    if not await registry.kb_exists(kb_name):
        raise HTTPException(status_code=404, detail=f"knowledge base not found: {kb_name}")
    return KBFacetsResponse.model_validate(await stats.get_facets(kb_name))


@router.patch("/knowledge_bases/{kb_name}", response_model=KBItem)
async def patch_knowledge_base(kb_name: str, body: KBUpdate) -> KBItem:
    if not await registry.kb_exists(kb_name):
        raise HTTPException(status_code=404, detail=f"knowledge base not found: {kb_name}")
    meta = await registry.update_kb(
        kb_name,
        display_name=body.display_name,
        description=body.description,
        theme=body.theme,
        icon=body.icon,
        pdf_text_page_ratio=body.pdf_text_page_ratio,
    )
    if meta is None:
        raise HTTPException(status_code=404, detail=f"knowledge base not found: {kb_name}")
    st = await stats.get_kb_stats(kb_name)
    return _kb_item(meta, st)


@router.delete("/knowledge_bases/{kb_name}", response_model=KBDeleteResponse)
async def delete_knowledge_base(kb_name: str) -> KBDeleteResponse:
    if not await registry.kb_exists(kb_name):
        raise HTTPException(status_code=404, detail=f"knowledge base not found: {kb_name}")
    counts = await asyncio.to_thread(lifecycle.delete_kb_namespace, kb_name)
    return KBDeleteResponse(kb_name=kb_name, deleted=counts)


@router.post("/knowledge_bases/{kb_name}/rebuild", response_model=RebuildResponse)
async def rebuild_knowledge_base(kb_name: str) -> RebuildResponse:
    if not await registry.kb_exists(kb_name):
        raise HTTPException(status_code=404, detail=f"knowledge base not found: {kb_name}")
    job_id = await asyncio.to_thread(lifecycle.start_rebuild, kb_name)
    return RebuildResponse(job_id=job_id)
