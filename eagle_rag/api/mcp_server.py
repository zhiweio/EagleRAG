"""Eagle-RAG MCP Server.

Exposes the system's four core capabilities (ingest / query / text retrieval /
visual retrieval) as MCP (Model Context Protocol) tools, so an LLM Agent (e.g.
LlamaIndex ``FunctionAgent`` + ``llama-index-tools-mcp``) can fetch and invoke
them over stdio transport.

Reuses the service layer (runner / engine / retrievers) directly without HTTP
self-calls, avoiding network round-trips and auth overhead, and shares the same
business logic as the ``/query`` and ``/ingest`` REST routes.

Tool list:
1. ``ingest(source_uri, source_type, kb_name)`` -> dispatch document ingest
   (Celery async).
2. ``query(query, mode, scope, kb_name, scope_filter)`` -> routed Q&A, returns
   answer / sources / route / steps.
3. ``retrieve_text(query, scope, top_k, kb_name)`` -> pure text vector retrieval
   (KnowhereGraphRetriever).
4. ``retrieve_visual(query, scope, top_k, kb_name)`` -> visual Tile retrieval
   (PixelRAGVisualRetriever).

Design notes:
- Uses FastMCP (``@mcp.tool`` decorator) and calls the service layer
  synchronously (runner/engine/retrievers are all sync; FastMCP tools are sync
  by default and run inside an internal thread pool).
- Tool functions lazy-import the service layer and try/except to return a
  dict/list with an ``error`` field on failure (graceful degradation: when
  Milvus/PostgreSQL/VLM are unavailable, the MCP session is not interrupted and
  the error is propagated back to the Agent).
- ``TOOL_DEFINITIONS`` mirrors tool metadata so the REST ``/mcp/tools`` route can
  read it directly, avoiding ``await mcp.list_tools()`` in a sync HTTP handler
  (which requires a running server context and is async).
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastmcp import FastMCP

from eagle_rag.mcp_cache import cache_key, get_cached, set_cached
from eagle_rag.mcp_resilience import CircuitBreakerError, resilient_call
from eagle_rag.metrics import _set_cache_hit, with_metrics
from eagle_rag.telemetry import get_logger

logger = get_logger(__name__)

__all__ = ["mcp", "TOOL_DEFINITIONS", "configure_mcp_auth", "main"]

# FastMCP instance (PrefectHQ/fastmcp), named eagle-rag. Defaults to streamable
# HTTP transport (stateless + JSON-only), controlled by ``settings.mcp.transport``;
# stdio mode is a fallback for llama-index-tools-mcp ``BasicMCPClient`` subprocess
# pulls. Auth (``auth=``) is injected into ``mcp.auth`` by ``configure_mcp_auth()``
# before startup per settings (``self.auth`` is a public attribute assignable after
# construction); supports static-token / oauth-github / oauth-custom.
mcp = FastMCP("eagle-rag")


# Tool metadata list: mirrors the functions registered by ``@mcp.tool`` below, for
# the REST ``/mcp/tools`` route to read directly (avoids await mcp.list_tools() in
# a sync HTTP handler).
TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "ingest",
        "description": (
            "Ingest a document. Accepts a local file path or web URL (file types include "
            "PDF/Word/Markdown/Excel/images, etc.). Asynchronously dispatches to the Celery "
            "router queue and returns job_id / document_id for subsequent status polling "
            "and query scoping."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "source_uri": {
                    "type": "string",
                    "description": "File path or web URL (http/https prefix is treated as a URL)",
                },
                "source_type": {
                    "type": "string",
                    "enum": ["policy", "financial", "business", "bidding", "tax", "other"],
                    "description": "Document source type hint, optional",
                },
                "kb_name": {
                    "type": "string",
                    "description": "Knowledge base id (multi-tenant); optional, defaults to config",
                },
            },
            "required": ["source_uri"],
        },
    },
    {
        "name": "query",
        "description": (
            "Multimodal Q&A. Auto-routes to text / visual / hybrid retrieval and generates "
            "the final answer, returning the answer, sources, route decision, and execution steps."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "User natural-language question"},
                "mode": {
                    "type": "string",
                    "enum": ["auto", "text", "visual", "hybrid"],
                    "description": "Retrieval mode; defaults to auto",
                },
                "scope": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of document_ids to constrain recall; optional",
                },
                "kb_name": {
                    "type": "string",
                    "description": "Knowledge base id (multi-tenant); optional, defaults to config",
                },
                "scope_filter": {
                    "type": "object",
                    "description": (
                        "Advanced scope filter combining knowledge bases, documents and tags "
                        "as a union (OR); optional. Overrides scope when non-empty."
                    ),
                    "properties": {
                        "kb_names": {"type": "array", "items": {"type": "string"}},
                        "document_ids": {"type": "array", "items": {"type": "string"}},
                        "tags": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "retrieve_text",
        "description": (
            "Pure text vector retrieval (Knowhere + graph expansion). Returns Top-K text chunks "
            "with their hierarchical metadata; does not generate an answer."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Retrieval query string"},
                "scope": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of document_ids to constrain recall; optional",
                },
                "top_k": {
                    "type": "integer",
                    "default": 5,
                    "description": "Number of results to return; defaults to 5",
                },
                "kb_name": {
                    "type": "string",
                    "description": "Knowledge base id (multi-tenant); optional, defaults to config",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "retrieve_visual",
        "description": (
            "Visual Tile retrieval (PixelRAG). Returns Top-K visual chunks (including image id, "
            "page number, and position); does not generate an answer."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Retrieval query string"},
                "scope": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of document_ids to constrain recall; optional",
                },
                "top_k": {
                    "type": "integer",
                    "default": 5,
                    "description": "Number of results to return; defaults to 5",
                },
                "kb_name": {
                    "type": "string",
                    "description": "Knowledge base id (multi-tenant); optional, defaults to config",
                },
            },
            "required": ["query"],
        },
    },
]


# ---------------------------------------------------------------------------
# MCP tool implementations
# ---------------------------------------------------------------------------


@mcp.tool()
@with_metrics("ingest")
def ingest(
    source_uri: str, source_type: str | None = None, kb_name: str | None = None
) -> dict[str, Any]:
    """Ingest a document. Accepts a file path or URL, dispatched async to the Celery router queue.

    Args:
        source_uri: File path or web URL (http/https prefix is treated as a URL).
        source_type: Document source type hint
            (policy/financial/business/bidding/tax/other).
        kb_name: Knowledge base identifier (multi-tenant isolation); optional,
            defaults to system config.

    Returns:
        ``{"job_id", "status", "document_id", "dedup_hit"}``, or
        ``{"error": ...}`` on failure.
    """
    import time as _time

    _start = _time.perf_counter()
    _args = {"source_uri": source_uri, "source_type": source_type, "kb_name": kb_name}
    try:
        from eagle_rag.ingest.runner import ingest as _ingest

        is_url = source_uri.startswith(("http://", "https://"))

        def _do_ingest():
            if is_url:
                return _ingest(
                    source_uri=source_uri,
                    source_type_hint=source_type,
                    kb_name=kb_name,
                )
            return _ingest(
                file_path=source_uri,
                source_type_hint=source_type,
                kb_name=kb_name,
            )

        raw = resilient_call("ingest", _do_ingest)
        result = {
            "job_id": raw.get("job_id"),
            "status": raw.get("status"),
            "document_id": raw.get("document_id"),
            "dedup_hit": raw.get("dedup_hit"),
        }
        _latency = int((_time.perf_counter() - _start) * 1000)
        try:
            from eagle_rag.admin.mcp_log import record_mcp_call

            record_mcp_call(
                tool_name="ingest",
                arguments=_args,
                result_summary=(
                    f"status={result.get('status')}, document_id={result.get('document_id')}"
                ),
                caller="mcp",
                latency_ms=_latency,
            )
        except Exception:  # noqa: BLE001
            logger.opt(exception=True).warning("MCP call log write failed (ingest)")
        return result
    except CircuitBreakerError as exc:
        _latency = int((_time.perf_counter() - _start) * 1000)
        try:
            from eagle_rag.admin.mcp_log import record_mcp_call

            record_mcp_call(
                tool_name="ingest",
                arguments=_args,
                result_summary="circuit_open",
                caller="mcp",
                latency_ms=_latency,
            )
        except Exception:  # noqa: BLE001
            logger.opt(exception=True).warning("MCP call log write failed (ingest)")
        logger.warning("MCP ingest circuit breaker open: %s", exc)
        return {"error": "circuit_open: ingest"}
    except TimeoutError as exc:
        _latency = int((_time.perf_counter() - _start) * 1000)
        try:
            from eagle_rag.admin.mcp_log import record_mcp_call

            record_mcp_call(
                tool_name="ingest",
                arguments=_args,
                result_summary="timeout",
                caller="mcp",
                latency_ms=_latency,
            )
        except Exception:  # noqa: BLE001
            logger.opt(exception=True).warning("MCP call log write failed (ingest)")
        logger.warning("MCP ingest tool call timed out: %s", exc)
        return {"error": "timeout: ingest"}
    except Exception as exc:  # noqa: BLE001
        _latency = int((_time.perf_counter() - _start) * 1000)
        try:
            from eagle_rag.admin.mcp_log import record_mcp_call

            record_mcp_call(
                tool_name="ingest",
                arguments=_args,
                result_summary=f"error: {type(exc).__name__}: {exc}",
                caller="mcp",
                latency_ms=_latency,
            )
        except Exception:  # noqa: BLE001
            logger.opt(exception=True).warning("MCP call log write failed (ingest)")
        logger.warning("MCP ingest tool call failed: %s", exc)
        return {"error": f"{type(exc).__name__}: {exc}"}


@mcp.tool()
@with_metrics("query")
def query(
    query: str,
    mode: str | None = None,
    scope: list[str] | None = None,
    kb_name: str | None = None,
    scope_filter: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Multimodal Q&A. Auto-routes retrieval and generates the answer.

    Args:
        query: User natural-language question.
        mode: Retrieval mode (auto/text/visual/hybrid); defaults to auto.
        scope: List of document_ids to constrain recall.
        kb_name: Knowledge base identifier (multi-tenant isolation); optional,
            defaults to system config.
        scope_filter: Advanced scope filter ``{kb_names, document_ids, tags}``
            combined as a union (OR); optional, overrides ``scope`` when set.

    Returns:
        ``{"answer", "sources", "route", "steps"}``, or ``{"error": ...}`` on
        failure.
    """
    import time as _time

    _start = _time.perf_counter()
    _args = {
        "query": query,
        "mode": mode,
        "scope": scope,
        "kb_name": kb_name,
        "scope_filter": scope_filter,
    }
    try:
        from eagle_rag.router.router_engine import EagleRouterQueryEngine

        def _do_query():
            engine = EagleRouterQueryEngine()
            return engine.query(
                query,
                mode=mode,
                scope=scope,
                kb_name=kb_name,
                scope_filter=scope_filter,
            )

        result = resilient_call("query", _do_query)
        # Trim to the agreed four fields (engine may return extras; unify here).
        result = {
            "answer": result.get("answer"),
            "sources": result.get("sources"),
            "route": result.get("route"),
            "steps": result.get("steps"),
        }
        _latency = int((_time.perf_counter() - _start) * 1000)
        try:
            from eagle_rag.admin.mcp_log import record_mcp_call

            _answer = result.get("answer") or ""
            _answer_len = len(_answer) if isinstance(_answer, str) else 0
            record_mcp_call(
                tool_name="query",
                arguments=_args,
                result_summary=f"route={result.get('route')}, answer_len={_answer_len}",
                caller="mcp",
                latency_ms=_latency,
            )
        except Exception:  # noqa: BLE001
            logger.opt(exception=True).warning("MCP call log write failed (query)")
        return result
    except CircuitBreakerError as exc:
        _latency = int((_time.perf_counter() - _start) * 1000)
        try:
            from eagle_rag.admin.mcp_log import record_mcp_call

            record_mcp_call(
                tool_name="query",
                arguments=_args,
                result_summary="circuit_open",
                caller="mcp",
                latency_ms=_latency,
            )
        except Exception:  # noqa: BLE001
            logger.opt(exception=True).warning("MCP call log write failed (query)")
        logger.warning("MCP query circuit breaker open: %s", exc)
        return {"error": "circuit_open: query"}
    except TimeoutError as exc:
        _latency = int((_time.perf_counter() - _start) * 1000)
        try:
            from eagle_rag.admin.mcp_log import record_mcp_call

            record_mcp_call(
                tool_name="query",
                arguments=_args,
                result_summary="timeout",
                caller="mcp",
                latency_ms=_latency,
            )
        except Exception:  # noqa: BLE001
            logger.opt(exception=True).warning("MCP call log write failed (query)")
        logger.warning("MCP query tool call timed out: %s", exc)
        return {"error": "timeout: query"}
    except Exception as exc:  # noqa: BLE001
        _latency = int((_time.perf_counter() - _start) * 1000)
        try:
            from eagle_rag.admin.mcp_log import record_mcp_call

            record_mcp_call(
                tool_name="query",
                arguments=_args,
                result_summary=f"error: {type(exc).__name__}: {exc}",
                caller="mcp",
                latency_ms=_latency,
            )
        except Exception:  # noqa: BLE001
            logger.opt(exception=True).warning("MCP call log write failed (query)")
        logger.warning("MCP query tool call failed: %s", exc)
        return {"error": f"{type(exc).__name__}: {exc}"}


@mcp.tool()
@with_metrics("retrieve_text")
def retrieve_text(
    query: str,
    scope: list[str] | None = None,
    top_k: int = 5,
    kb_name: str | None = None,
) -> list[dict[str, Any]]:
    """Pure text vector retrieval (Knowhere + graph expansion).

    Args:
        query: Retrieval query string.
        scope: List of document_ids to constrain recall.
        top_k: Number of results to return; defaults to 5.
        kb_name: Knowledge base identifier (multi-tenant isolation); optional,
            defaults to system config.

    Returns:
        ``list[{"node_id", "text", "score", "metadata"}]`` (metadata contains
        path/level/summary/document_id/source_type), or ``[{"error": ...}]`` on
        failure.
    """
    import time as _time

    _start = _time.perf_counter()
    _args = {"query": query, "scope": scope, "top_k": top_k, "kb_name": kb_name}
    # Cache read: on hit, return immediately and skip vector retrieval + rerank.
    _ckey = cache_key("retrieve_text", query, scope=scope, top_k=top_k, kb_name=kb_name)
    _cached = get_cached(_ckey)
    if _cached is not None:
        _latency = int((_time.perf_counter() - _start) * 1000)
        try:
            from eagle_rag.admin.mcp_log import record_mcp_call

            record_mcp_call(
                tool_name="retrieve_text",
                arguments=_args,
                result_summary=f"cache_hit hits={len(_cached)}",
                caller="mcp",
                latency_ms=_latency,
            )
        except Exception:  # noqa: BLE001
            logger.opt(exception=True).warning("MCP call log write failed (retrieve_text)")
        _set_cache_hit(True)
        return _cached
    try:
        from eagle_rag.retrievers.knowhere_graph_retriever import KnowhereGraphRetriever

        def _do_retrieve():
            retriever = KnowhereGraphRetriever(top_k=top_k, kb_name=kb_name)
            return retriever.retrieve(query)

        nodes = resilient_call("retrieve_text", _do_retrieve) or []
        scope_set = set(scope) if scope else None
        out: list[dict[str, Any]] = []
        for nws in nodes:
            node = nws.node
            meta = dict(node.metadata or {})
            if scope_set is not None and meta.get("document_id") not in scope_set:
                continue
            # Trim metadata to the agreed fields (connect_to and other internal
            # fields are not exposed).
            trimmed = {
                "path": meta.get("path"),
                "level": meta.get("level"),
                "summary": meta.get("summary"),
                "document_id": meta.get("document_id"),
                "source_type": meta.get("source_type"),
            }
            text = node.get_content() if hasattr(node, "get_content") else (node.text or "")
            out.append(
                {
                    "node_id": node.node_id,
                    "text": text,
                    "score": float(nws.score) if nws.score is not None else None,
                    "metadata": trimmed,
                }
            )
        # Cache write: write back on miss (only non-empty results, to avoid caching
        # an empty list).
        if out:
            set_cached(_ckey, out)
        _latency = int((_time.perf_counter() - _start) * 1000)
        try:
            from eagle_rag.admin.mcp_log import record_mcp_call

            record_mcp_call(
                tool_name="retrieve_text",
                arguments=_args,
                result_summary=f"hits={len(out)}",
                caller="mcp",
                latency_ms=_latency,
            )
        except Exception:  # noqa: BLE001
            logger.opt(exception=True).warning("MCP call log write failed (retrieve_text)")
        return out
    except CircuitBreakerError as exc:
        _latency = int((_time.perf_counter() - _start) * 1000)
        try:
            from eagle_rag.admin.mcp_log import record_mcp_call

            record_mcp_call(
                tool_name="retrieve_text",
                arguments=_args,
                result_summary="circuit_open",
                caller="mcp",
                latency_ms=_latency,
            )
        except Exception:  # noqa: BLE001
            logger.opt(exception=True).warning("MCP call log write failed (retrieve_text)")
        logger.warning("MCP retrieve_text circuit breaker open: %s", exc)
        return [{"error": "circuit_open: retrieve_text"}]
    except TimeoutError as exc:
        _latency = int((_time.perf_counter() - _start) * 1000)
        try:
            from eagle_rag.admin.mcp_log import record_mcp_call

            record_mcp_call(
                tool_name="retrieve_text",
                arguments=_args,
                result_summary="timeout",
                caller="mcp",
                latency_ms=_latency,
            )
        except Exception:  # noqa: BLE001
            logger.opt(exception=True).warning("MCP call log write failed (retrieve_text)")
        logger.warning("MCP retrieve_text tool call timed out: %s", exc)
        return [{"error": "timeout: retrieve_text"}]
    except Exception as exc:  # noqa: BLE001
        _latency = int((_time.perf_counter() - _start) * 1000)
        try:
            from eagle_rag.admin.mcp_log import record_mcp_call

            record_mcp_call(
                tool_name="retrieve_text",
                arguments=_args,
                result_summary=f"error: {type(exc).__name__}: {exc}",
                caller="mcp",
                latency_ms=_latency,
            )
        except Exception:  # noqa: BLE001
            logger.opt(exception=True).warning("MCP call log write failed (retrieve_text)")
        logger.warning("MCP retrieve_text tool call failed: %s", exc)
        return [{"error": f"{type(exc).__name__}: {exc}"}]


@mcp.tool()
@with_metrics("retrieve_visual")
def retrieve_visual(
    query: str,
    scope: list[str] | None = None,
    top_k: int = 5,
    kb_name: str | None = None,
) -> list[dict[str, Any]]:
    """Visual Tile retrieval (PixelRAG).

    Args:
        query: Retrieval query string.
        scope: List of document_ids to constrain recall.
        top_k: Number of results to return; defaults to 5.
        kb_name: Knowledge base identifier (multi-tenant isolation); optional,
            defaults to system config.

    Returns:
        ``list[{"image_id", "document_id", "page", "position", "score"}]``, or
        ``[{"error": ...}]`` on failure.
    """
    import time as _time

    _start = _time.perf_counter()
    _args = {"query": query, "scope": scope, "top_k": top_k, "kb_name": kb_name}
    # Cache read: on hit, return immediately and skip visual Tile retrieval.
    _ckey = cache_key("retrieve_visual", query, scope=scope, top_k=top_k, kb_name=kb_name)
    _cached = get_cached(_ckey)
    if _cached is not None:
        _latency = int((_time.perf_counter() - _start) * 1000)
        try:
            from eagle_rag.admin.mcp_log import record_mcp_call

            record_mcp_call(
                tool_name="retrieve_visual",
                arguments=_args,
                result_summary=f"cache_hit hits={len(_cached)}",
                caller="mcp",
                latency_ms=_latency,
            )
        except Exception:  # noqa: BLE001
            logger.opt(exception=True).warning("MCP call log write failed (retrieve_visual)")
        _set_cache_hit(True)
        return _cached
    try:
        from eagle_rag.retrievers.pixelrag_visual_retriever import PixelRAGVisualRetriever

        def _do_retrieve():
            retriever = PixelRAGVisualRetriever(top_k=top_k, kb_name=kb_name)
            return retriever.retrieve(query)

        nodes = resilient_call("retrieve_visual", _do_retrieve) or []
        scope_set = set(scope) if scope else None
        out: list[dict[str, Any]] = []
        for nws in nodes:
            node = nws.node
            meta = node.metadata or {}
            document_id = meta.get("document_id")
            if scope_set is not None and document_id not in scope_set:
                continue
            out.append(
                {
                    "image_id": meta.get("image_id"),
                    "document_id": document_id,
                    "page": meta.get("page"),
                    "position": meta.get("position"),
                    "score": float(nws.score) if nws.score is not None else None,
                }
            )
        # Cache write: write back on miss (only non-empty results, to avoid caching
        # an empty list).
        if out:
            set_cached(_ckey, out)
        _latency = int((_time.perf_counter() - _start) * 1000)
        try:
            from eagle_rag.admin.mcp_log import record_mcp_call

            record_mcp_call(
                tool_name="retrieve_visual",
                arguments=_args,
                result_summary=f"hits={len(out)}",
                caller="mcp",
                latency_ms=_latency,
            )
        except Exception:  # noqa: BLE001
            logger.opt(exception=True).warning("MCP call log write failed (retrieve_visual)")
        return out
    except CircuitBreakerError as exc:
        _latency = int((_time.perf_counter() - _start) * 1000)
        try:
            from eagle_rag.admin.mcp_log import record_mcp_call

            record_mcp_call(
                tool_name="retrieve_visual",
                arguments=_args,
                result_summary="circuit_open",
                caller="mcp",
                latency_ms=_latency,
            )
        except Exception:  # noqa: BLE001
            logger.opt(exception=True).warning("MCP call log write failed (retrieve_visual)")
        logger.warning("MCP retrieve_visual circuit breaker open: %s", exc)
        return [{"error": "circuit_open: retrieve_visual"}]
    except TimeoutError as exc:
        _latency = int((_time.perf_counter() - _start) * 1000)
        try:
            from eagle_rag.admin.mcp_log import record_mcp_call

            record_mcp_call(
                tool_name="retrieve_visual",
                arguments=_args,
                result_summary="timeout",
                caller="mcp",
                latency_ms=_latency,
            )
        except Exception:  # noqa: BLE001
            logger.opt(exception=True).warning("MCP call log write failed (retrieve_visual)")
        logger.warning("MCP retrieve_visual tool call timed out: %s", exc)
        return [{"error": "timeout: retrieve_visual"}]
    except Exception as exc:  # noqa: BLE001
        _latency = int((_time.perf_counter() - _start) * 1000)
        try:
            from eagle_rag.admin.mcp_log import record_mcp_call

            record_mcp_call(
                tool_name="retrieve_visual",
                arguments=_args,
                result_summary=f"error: {type(exc).__name__}: {exc}",
                caller="mcp",
                latency_ms=_latency,
            )
        except Exception:  # noqa: BLE001
            logger.opt(exception=True).warning("MCP call log write failed (retrieve_visual)")
        logger.warning("MCP retrieve_visual tool call failed: %s", exc)
        return [{"error": f"{type(exc).__name__}: {exc}"}]


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def configure_mcp_auth() -> Any:
    """Build the MCP auth provider per settings and inject it into ``mcp.auth``.

    Auth policy is decided jointly by ``settings.auth.enabled`` and
    ``settings.mcp.auth_provider``:

    - ``auth.enabled=false``: returns ``None`` (no auth; pure internal network or
      local dev).
    - ``auth_provider="static-token"`` (default): ``StaticTokenVerifier`` validates
      ``Authorization: Bearer <api_key>``. The API key is provided via
      ``auth.api_key`` (env ``AUTH_API_KEY``) or ``AUTH_API_KEY_FILE`` (Docker
      Swarm secret mounted as a file). The token carries the ``eagle-rag:tools``
      scope; ``required_scopes`` enforces it.
    - ``auth_provider="oauth-github"``: ``GitHubProvider`` (fastmcp OAuth 2.1
      Proxy); requires ``mcp.oauth.client_id`` / ``client_secret`` / ``issuer_url``
      (used as base_url, the public address of the OAuth callback endpoint).
    - ``auth_provider="oauth-custom"``: ``JWTVerifier`` validates a JWT Bearer
      token via the external Authorization Server's JWKS endpoint
      (``issuer_url/.well-known/jwks.json``); validates iss against ``issuer_url``
      and scope against ``required_scopes``.

    Returns the Provider instance (already assigned to ``mcp.auth``), or ``None``
    when auth is disabled.

    Note:
        ``StaticTokenVerifier`` suits internal / single-tenant scenarios (API key
        injected via env / Swarm secret, never committed); for multi-tenant
        production prefer ``oauth-github`` or ``oauth-custom`` against an external
        IdP.
    """
    from eagle_rag.config import get_settings

    settings = get_settings()
    # Default to cleared; only the success branch assigns a Provider (ensures
    # ``mcp.auth`` does not retain the previous config when disabled / incomplete /
    # unknown provider).
    mcp.auth = None
    if not settings.auth.enabled:
        return None

    provider = settings.mcp.auth_provider

    if provider == "static-token":
        # API key resolution: prefer auth.api_key (env AUTH_API_KEY), then
        # AUTH_API_KEY_FILE (Docker Swarm secret mounted at /run/secrets/<name>).
        api_key = settings.auth.api_key
        api_key_file = os.environ.get("AUTH_API_KEY_FILE", "")
        if not api_key and api_key_file:
            try:
                with open(api_key_file, encoding="utf-8") as fh:
                    api_key = fh.read().strip()
            except OSError as exc:
                logger.warning("failed to read AUTH_API_KEY_FILE=%s: %s", api_key_file, exc)
        if not api_key:
            logger.warning("auth.enabled=true but api_key is empty; MCP auth disabled")
            return None
        from fastmcp.server.auth import StaticTokenVerifier

        scopes = ["eagle-rag:tools"]
        verifier = StaticTokenVerifier(
            tokens={api_key: {"client_id": "eagle-rag", "scopes": scopes}},
            required_scopes=scopes,
        )
        mcp.auth = verifier
        logger.info("MCP auth enabled: StaticTokenVerifier")
        return verifier

    if provider == "oauth-github":
        oauth = settings.mcp.oauth
        if not oauth.enabled or not oauth.client_id or not oauth.client_secret:
            logger.warning(
                "auth_provider=oauth-github but mcp.oauth config incomplete "
                "(requires enabled/client_id/client_secret); auth disabled"
            )
            return None
        from fastmcp.server.auth.providers.github import GitHubProvider

        base_url = oauth.issuer_url or f"http://0.0.0.0:{settings.mcp.port}"
        verifier = GitHubProvider(
            client_id=oauth.client_id,
            client_secret=oauth.client_secret,
            base_url=base_url,
            required_scopes=oauth.required_scopes or None,
        )
        mcp.auth = verifier
        logger.info("MCP auth enabled: GitHubProvider (base_url=%s)", base_url)
        return verifier

    if provider == "oauth-custom":
        oauth = settings.mcp.oauth
        if not oauth.enabled or not oauth.issuer_url:
            logger.warning(
                "auth_provider=oauth-custom but mcp.oauth.issuer_url is empty; auth disabled"
            )
            return None
        from fastmcp.server.auth import JWTVerifier

        jwks_uri = f"{oauth.issuer_url.rstrip('/')}/.well-known/jwks.json"
        verifier = JWTVerifier(
            jwks_uri=jwks_uri,
            issuer=oauth.issuer_url,
            required_scopes=oauth.required_scopes or None,
        )
        mcp.auth = verifier
        logger.info("MCP auth enabled: JWTVerifier (jwks_uri=%s)", jwks_uri)
        return verifier

    logger.warning("unknown auth_provider=%s; MCP auth disabled", provider)
    return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Start the MCP server (defaults to streamable HTTP, can fall back to stdio).

    Transport mode is controlled by ``settings.mcp.transport``:
    - ``http`` (default, fastmcp streamable HTTP): ``mcp.run(transport="http",
      host=..., port=...)``, stateless + JSON-only, no sticky routing, supports
      horizontal scaling. When ``settings.mcp.stateless_http=true``, the
      ``FASTMCP_STATELESS_HTTP=true`` env var is injected before startup (fastmcp
      convention).
    - ``stdio``: ``mcp.run(transport="stdio")``, local subprocess fallback for
      llama-index-tools-mcp ``BasicMCPClient`` over stdin/stdout.

    Invoked by ``python -m eagle_rag.api.mcp_server``.
    """
    import fastmcp

    from eagle_rag.config import get_settings

    settings = get_settings()
    logging.basicConfig(level=logging.INFO)

    # Inject the auth provider (static-token / oauth-github / oauth-custom) before
    # startup.
    configure_mcp_auth()

    transport = settings.mcp.transport
    if transport == "http":
        if settings.mcp.stateless_http:
            # fastmcp convention: env var enables stateless mode (any replica can
            # serve any request, no sticky routing needed). The ``fastmcp.settings``
            # singleton is instantiated at ``import fastmcp``; post-import env var
            # changes do not update it, so also mutate the singleton directly to
            # ensure ``mcp.run`` / ``mcp.http_app`` read the correct stateless value.
            os.environ["FASTMCP_STATELESS_HTTP"] = "true"
            fastmcp.settings.stateless_http = True
        if settings.mcp.json_response:
            os.environ["FASTMCP_JSON_RESPONSE"] = "true"
            fastmcp.settings.json_response = True
        mcp.run(
            transport="http",
            host=settings.mcp.host,
            port=settings.mcp.port,
        )
    else:  # stdio
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
