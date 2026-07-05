"""Query, search, and session API routes."""

from __future__ import annotations

import asyncio
import json
import queue
import threading
import time
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query
from sse_starlette.sse import EventSourceResponse

from eagle_rag.api.schemas.common import DeletedResponse
from eagle_rag.api.schemas.query import (
    QueryRequest,
    QueryResponse,
    QuerySources,
    QueryStep,
    RouteInfo,
    SearchRequest,
    SearchResponse,
)
from eagle_rag.api.schemas.sessions import (
    MessageListResponse,
    MessageOut,
    SessionCreate,
    SessionListResponse,
    SessionSummary,
)
from eagle_rag.router.router_engine import EagleRouterQueryEngine
from eagle_rag.sessions.store import (
    add_message,
    create_session,
    delete_session,
    get_session,
    list_messages,
    list_sessions,
    set_session_scope_filter,
    update_session,
)
from eagle_rag.telemetry import bind_context, get_ai_logger, get_logger

__all__ = ["router"]

logger = get_logger(__name__)
ai_logger = get_ai_logger(__name__)

router = APIRouter(tags=["query"])

_engine_instance: EagleRouterQueryEngine | None = None


def _get_engine() -> EagleRouterQueryEngine:
    """Module-level lazy singleton to avoid rebuilding the engine per request."""
    global _engine_instance  # noqa: PLW0603
    if _engine_instance is None:
        _engine_instance = EagleRouterQueryEngine()
    return _engine_instance


def _serialize_sse(data: dict) -> str:
    return json.dumps(data, default=str, ensure_ascii=False)


async def _resolve_session(req: QueryRequest) -> tuple[str, str]:
    """Create or validate a session, returning (session_id, user_message_id)."""
    scope_filter_dict = (
        req.scope_filter.model_dump()
        if req.scope_filter is not None and not req.scope_filter.is_empty()
        else None
    )
    session_id = req.session_id
    if session_id is None:
        session_id = str(uuid4())
        await create_session(
            session_id,
            title=req.query[:30],
            kb_name=req.kb_name,
            scope_filter=scope_filter_dict,
        )
    else:
        existing = await get_session(session_id)
        if existing is None:
            raise HTTPException(status_code=404, detail=f"session not found: {session_id}")
        # Persist the latest scope selection so switching back restores it.
        await set_session_scope_filter(session_id, scope_filter_dict)
    user_message_id = str(uuid4())
    await add_message(
        session_id,
        message_id=user_message_id,
        role="user",
        content=req.query,
        attachments=req.attachments,
        kb_name=req.kb_name,
    )
    return session_id, user_message_id


@router.post("/search", response_model=SearchResponse)
async def post_search(req: SearchRequest) -> SearchResponse:
    """Pure retrieval: route → retrieve → return sources (no AI generation)."""
    query_id = str(uuid4())
    bind_context(query_id=query_id)
    t0 = time.monotonic()

    engine = _get_engine()
    filters_dict = req.filters.model_dump(exclude_none=True) if req.filters else None
    scope_filter_dict = req.scope_filter.model_dump() if req.scope_filter else None
    try:
        result = await asyncio.to_thread(
            engine.search,
            req.query,
            mode=req.mode,
            scope=req.scope,
            kb_name=req.kb_name,
            filters=filters_dict,
            scope_filter=scope_filter_dict,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("retrieval engine call failed")
        try:
            ai_logger.info(
                "search",
                query_id=query_id,
                mode=req.mode,
                kb_name=req.kb_name,
                duration_ms=int((time.monotonic() - t0) * 1000),
                status="error",
            )
        except Exception:  # noqa: BLE001
            logger.debug("telemetry emit failed", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    sources = QuerySources.model_validate(result.get("sources") or {"text": [], "image": []})
    route = RouteInfo.model_validate(result.get("route") or {})
    steps = [QueryStep.model_validate(step) for step in (result.get("steps") or [])]

    try:
        ai_logger.info(
            "search",
            query_id=query_id,
            mode=req.mode,
            kb_name=req.kb_name,
            text_count=len(sources.text),
            image_count=len(sources.image),
            duration_ms=int((time.monotonic() - t0) * 1000),
            status="success",
        )
    except Exception:  # noqa: BLE001
        logger.debug("telemetry emit failed", exc_info=True)

    return SearchResponse(sources=sources, route=route, steps=steps)


@router.post(
    "/search/stream",
    response_class=EventSourceResponse,
    responses={
        200: {
            "description": "SSE streaming pure retrieval (event: step | sources | done | error)",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        }
    },
)
async def post_search_stream(req: SearchRequest) -> EventSourceResponse:
    """Streaming pure retrieval: push route/recall steps then sources (no LLM generation)."""

    async def event_generator() -> AsyncIterator[dict[str, str]]:
        query_id = str(uuid4())
        bind_context(query_id=query_id)
        t0 = time.monotonic()

        engine = _get_engine()
        filters_dict = req.filters.model_dump(exclude_none=True) if req.filters else None
        scope_filter_dict = req.scope_filter.model_dump() if req.scope_filter else None
        event_q: queue.Queue[dict[str, Any] | None] = queue.Queue()

        def run_stream() -> None:
            try:
                for evt in engine.search_stream(
                    req.query,
                    mode=req.mode,
                    scope=req.scope,
                    kb_name=req.kb_name,
                    filters=filters_dict,
                    scope_filter=scope_filter_dict,
                ):
                    event_q.put(evt)
            except Exception as exc:  # noqa: BLE001
                logger.exception("search_stream failed")
                event_q.put(
                    {"event": "error", "data": {"code": "engine_error", "message": str(exc)}},
                )
            finally:
                event_q.put(None)

        thread = threading.Thread(target=run_stream, daemon=True)
        thread.start()

        had_error = False
        text_count = 0
        image_count = 0
        while True:
            evt = await asyncio.to_thread(event_q.get)
            if evt is None:
                break
            event_name = evt.get("event", "message")
            data = evt.get("data", {})
            if event_name == "error":
                had_error = True
            if event_name == "done":
                sources = data.get("sources") or {}
                text_count = len(sources.get("text") or [])
                image_count = len(sources.get("image") or [])
            yield {"event": event_name, "data": _serialize_sse(data)}

        if not had_error:
            try:
                ai_logger.info(
                    "search",
                    query_id=query_id,
                    mode=req.mode,
                    kb_name=req.kb_name,
                    text_count=text_count,
                    image_count=image_count,
                    duration_ms=int((time.monotonic() - t0) * 1000),
                    status="success",
                )
            except Exception:  # noqa: BLE001
                logger.debug("telemetry emit failed", exc_info=True)

    return EventSourceResponse(event_generator())


@router.post("/query", response_model=QueryResponse)
async def post_query(req: QueryRequest) -> QueryResponse:
    """User query -> route -> retrieve -> generate -> persist."""
    query_id = str(uuid4())
    bind_context(query_id=query_id)
    t0 = time.monotonic()
    try:
        session_id, user_message_id = await _resolve_session(req)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("session resolve/create failed; database may be unavailable")
        try:
            ai_logger.info(
                "query",
                query_id=query_id,
                mode=req.mode,
                kb_name=req.kb_name,
                has_attachments=bool(req.attachments),
                duration_ms=int((time.monotonic() - t0) * 1000),
                status="error",
            )
        except Exception:  # noqa: BLE001
            logger.debug("telemetry emit failed", exc_info=True)
        raise HTTPException(status_code=503, detail="database unavailable") from exc

    engine = _get_engine()
    filters_dict = req.filters.model_dump(exclude_none=True) if req.filters else None
    scope_filter_dict = req.scope_filter.model_dump() if req.scope_filter else None
    try:
        result = await asyncio.to_thread(
            engine.query,
            req.query,
            mode=req.mode,
            scope=req.scope,
            kb_name=req.kb_name,
            filters=filters_dict,
            scope_filter=scope_filter_dict,
            attachments=req.attachments,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Q&A engine call failed")
        try:
            ai_logger.info(
                "query",
                session_id=session_id,
                query_id=query_id,
                mode=req.mode,
                kb_name=req.kb_name,
                has_attachments=bool(req.attachments),
                duration_ms=int((time.monotonic() - t0) * 1000),
                status="error",
            )
        except Exception:  # noqa: BLE001
            logger.debug("telemetry emit failed", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    answer = result.get("answer", "")
    sources = QuerySources.model_validate(result.get("sources") or {"text": [], "image": []})
    route = RouteInfo.model_validate(result.get("route") or {})
    steps = [QueryStep.model_validate(step) for step in (result.get("steps") or [])]

    assistant_message_id = str(uuid4())
    try:
        await add_message(
            session_id,
            message_id=assistant_message_id,
            role="assistant",
            content=answer,
            sources=sources.model_dump(),
            steps=[step.model_dump() for step in steps],
            kb_name=req.kb_name,
        )
    except Exception:  # noqa: BLE001
        logger.exception("assistant message persistence failed (non-fatal; answer still returned)")
        steps = [*steps, QueryStep(name="warning", detail="message persistence failed")]

    try:
        ai_logger.info(
            "query",
            session_id=session_id,
            query_id=query_id,
            mode=req.mode,
            kb_name=req.kb_name,
            has_attachments=bool(req.attachments),
            answer_len=len(answer),
            duration_ms=int((time.monotonic() - t0) * 1000),
            status="success",
        )
    except Exception:  # noqa: BLE001
        logger.debug("telemetry emit failed", exc_info=True)

    return QueryResponse(
        session_id=session_id,
        message_id=assistant_message_id,
        answer=answer,
        sources=sources,
        route=route,
        steps=steps,
    )


@router.post(
    "/query/stream",
    response_class=EventSourceResponse,
    responses={
        200: {
            "description": (
                "SSE streaming Q&A (event: session | step | sources | token | done | error)"
            ),
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        }
    },
)
async def post_query_stream(req: QueryRequest) -> EventSourceResponse:
    """Streaming Q&A: push step events during retrieval and token events during generation."""

    async def event_generator() -> AsyncIterator[dict[str, str]]:
        query_id = str(uuid4())
        bind_context(query_id=query_id)
        t0 = time.monotonic()
        try:
            session_id, user_message_id = await _resolve_session(req)
        except HTTPException as exc:
            try:
                ai_logger.info(
                    "query",
                    query_id=query_id,
                    mode=req.mode,
                    kb_name=req.kb_name,
                    has_attachments=bool(req.attachments),
                    duration_ms=int((time.monotonic() - t0) * 1000),
                    status="error",
                )
            except Exception:  # noqa: BLE001
                logger.debug("telemetry emit failed", exc_info=True)
            yield {
                "event": "error",
                "data": _serialize_sse({"code": "session_error", "message": exc.detail}),
            }
            return
        except Exception as exc:  # noqa: BLE001
            logger.exception("streaming Q&A session failed")
            try:
                ai_logger.info(
                    "query",
                    query_id=query_id,
                    mode=req.mode,
                    kb_name=req.kb_name,
                    has_attachments=bool(req.attachments),
                    duration_ms=int((time.monotonic() - t0) * 1000),
                    status="error",
                )
            except Exception:  # noqa: BLE001
                logger.debug("telemetry emit failed", exc_info=True)
            yield {
                "event": "error",
                "data": _serialize_sse({"code": "database_unavailable", "message": str(exc)}),
            }
            return

        engine = _get_engine()
        filters_dict = req.filters.model_dump(exclude_none=True) if req.filters else None
        scope_filter_dict = req.scope_filter.model_dump() if req.scope_filter else None
        event_q: queue.Queue[dict[str, Any] | None] = queue.Queue()

        def run_stream() -> None:
            try:
                for evt in engine.query_stream(
                    req.query,
                    mode=req.mode,
                    scope=req.scope,
                    kb_name=req.kb_name,
                    filters=filters_dict,
                    scope_filter=scope_filter_dict,
                    attachments=req.attachments,
                    session_id=session_id,
                    user_message_id=user_message_id,
                ):
                    event_q.put(evt)
            except Exception as exc:  # noqa: BLE001
                logger.exception("query_stream failed")
                event_q.put(
                    {"event": "error", "data": {"code": "engine_error", "message": str(exc)}},
                )
            finally:
                event_q.put(None)

        thread = threading.Thread(target=run_stream, daemon=True)
        thread.start()

        done_payload: dict | None = None
        while True:
            evt = await asyncio.to_thread(event_q.get)
            if evt is None:
                break
            event_name = evt.get("event", "message")
            data = evt.get("data", {})
            if event_name == "done":
                done_payload = data
                continue
            if event_name == "error":
                try:
                    ai_logger.info(
                        "query",
                        session_id=session_id,
                        query_id=query_id,
                        mode=req.mode,
                        kb_name=req.kb_name,
                        has_attachments=bool(req.attachments),
                        duration_ms=int((time.monotonic() - t0) * 1000),
                        status="error",
                    )
                except Exception:  # noqa: BLE001
                    logger.debug("telemetry emit failed", exc_info=True)
            yield {"event": event_name, "data": _serialize_sse(data)}

        if done_payload is not None:
            assistant_message_id = str(uuid4())
            sources = done_payload.get("sources") or {"text": [], "image": []}
            steps = done_payload.get("steps") or []
            try:
                await add_message(
                    session_id,
                    message_id=assistant_message_id,
                    role="assistant",
                    content=done_payload.get("answer", ""),
                    sources=sources,
                    steps=steps,
                    kb_name=req.kb_name,
                )
                yield {
                    "event": "done",
                    "data": _serialize_sse({**done_payload, "message_id": assistant_message_id}),
                }
            except Exception:  # noqa: BLE001
                logger.exception("streaming assistant message persistence failed")
                yield {
                    "event": "done",
                    "data": _serialize_sse(
                        {
                            **done_payload,
                            "message_id": assistant_message_id,
                            "warning": "message persistence failed",
                        }
                    ),
                }
            try:
                ai_logger.info(
                    "query",
                    session_id=session_id,
                    query_id=query_id,
                    mode=req.mode,
                    kb_name=req.kb_name,
                    has_attachments=bool(req.attachments),
                    answer_len=len(done_payload.get("answer", "")),
                    duration_ms=int((time.monotonic() - t0) * 1000),
                    status="success",
                )
            except Exception:  # noqa: BLE001
                logger.debug("telemetry emit failed", exc_info=True)

    return EventSourceResponse(event_generator())


@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions_api(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    kb_name: str | None = Query(default=None),
) -> SessionListResponse:
    """List sessions. Degrades to an empty list when DB is unavailable."""
    try:
        sessions = await list_sessions(kb_name=kb_name, limit=limit, offset=offset)
    except Exception:  # noqa: BLE001
        logger.exception("list_sessions failed; database may be unavailable")
        return SessionListResponse(items=[], limit=limit, offset=offset)
    return SessionListResponse(
        items=[SessionSummary.from_store(s) for s in sessions],
        limit=limit,
        offset=offset,
    )


@router.post("/sessions", response_model=SessionSummary, status_code=201)
async def create_session_api(body: SessionCreate) -> SessionSummary:
    """Create a new session."""
    session_id = str(uuid4())
    try:
        session = await create_session(session_id, title=body.title, kb_name=body.kb_name)
    except Exception as exc:  # noqa: BLE001
        logger.exception("create_session failed; database may be unavailable")
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    return SessionSummary.from_store(session)


@router.get("/sessions/{session_id}", response_model=SessionSummary)
async def get_session_api(session_id: str) -> SessionSummary:
    """Get a single session."""
    try:
        session = await get_session(session_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("get_session failed; database may be unavailable")
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    if session is None:
        raise HTTPException(status_code=404, detail=f"session not found: {session_id}")
    return SessionSummary.from_store(session)


@router.patch("/sessions/{session_id}", response_model=SessionSummary)
async def update_session_api(session_id: str, body: SessionCreate) -> SessionSummary:
    """Update session title."""
    try:
        session = await update_session(session_id, title=body.title)
    except Exception as exc:  # noqa: BLE001
        logger.exception("update_session failed; database may be unavailable")
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    if session is None:
        raise HTTPException(status_code=404, detail=f"session not found: {session_id}")
    return SessionSummary.from_store(session)


@router.delete("/sessions/{session_id}", response_model=DeletedResponse)
async def delete_session_api(session_id: str) -> DeletedResponse:
    """Delete a session (cascades to messages)."""
    try:
        deleted = await delete_session(session_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("delete_session failed; database may be unavailable")
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    if not deleted:
        raise HTTPException(status_code=404, detail=f"session not found: {session_id}")
    return DeletedResponse(deleted=True)


@router.get("/sessions/{session_id}/messages", response_model=MessageListResponse)
async def list_messages_api(
    session_id: str,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> MessageListResponse:
    """List messages in a session."""
    try:
        session = await get_session(session_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("get_session failed; database may be unavailable")
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    if session is None:
        raise HTTPException(status_code=404, detail=f"session not found: {session_id}")
    try:
        messages = await list_messages(session_id, limit=limit, offset=offset)
    except Exception as exc:  # noqa: BLE001
        logger.exception("list_messages failed; database may be unavailable")
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    return MessageListResponse(
        items=[MessageOut.from_store(m) for m in messages],
        limit=limit,
        offset=offset,
    )
