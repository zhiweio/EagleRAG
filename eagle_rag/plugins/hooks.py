"""Hook point constants and invocation mode metadata."""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "Hook",
    "HookMode",
    "HOOK_MODES",
]


class Hook(StrEnum):
    """Named hook points for ingest and query pipelines."""

    PARSE = "PARSE"
    CHUNK = "CHUNK"
    INGEST_VISUAL_EXTRACT = "INGEST_VISUAL_EXTRACT"
    CLASSIFY_CHUNK = "CLASSIFY_CHUNK"
    CLASSIFY_VISUAL = "CLASSIFY_VISUAL"
    CLASSIFY_QUERY = "CLASSIFY_QUERY"
    EMBED_TEXT = "EMBED_TEXT"
    EMBED_VISUAL = "EMBED_VISUAL"
    UPSERT_VECTORS = "UPSERT_VECTORS"
    INGEST_ROUTE_SELECTORS = "INGEST_ROUTE_SELECTORS"
    RERANK = "RERANK"
    RERANK_MERGED = "RERANK_MERGED"
    QUERY_DENSE_EXPAND = "QUERY_DENSE_EXPAND"
    RETRIEVE_SUPPLEMENT = "RETRIEVE_SUPPLEMENT"
    QUERY_ASSEMBLE = "QUERY_ASSEMBLE"
    RETRIEVE_VISUAL_FILTER = "RETRIEVE_VISUAL_FILTER"
    CELERY_TASKS = "CELERY_TASKS"


class HookMode(StrEnum):
    """How subscribers on a hook are invoked."""

    FIRST = "invoke_first"
    ALL = "invoke_all"
    TRANSFORM = "invoke_transform"


HOOK_MODES: dict[Hook, HookMode] = {
    Hook.PARSE: HookMode.TRANSFORM,
    Hook.CHUNK: HookMode.TRANSFORM,
    Hook.INGEST_VISUAL_EXTRACT: HookMode.FIRST,
    Hook.CLASSIFY_CHUNK: HookMode.FIRST,
    Hook.CLASSIFY_VISUAL: HookMode.FIRST,
    Hook.CLASSIFY_QUERY: HookMode.FIRST,
    Hook.EMBED_TEXT: HookMode.FIRST,
    Hook.EMBED_VISUAL: HookMode.FIRST,
    Hook.UPSERT_VECTORS: HookMode.TRANSFORM,
    Hook.INGEST_ROUTE_SELECTORS: HookMode.FIRST,
    Hook.RERANK: HookMode.FIRST,
    Hook.RERANK_MERGED: HookMode.FIRST,
    Hook.QUERY_DENSE_EXPAND: HookMode.FIRST,
    Hook.RETRIEVE_SUPPLEMENT: HookMode.ALL,
    Hook.QUERY_ASSEMBLE: HookMode.ALL,
    Hook.RETRIEVE_VISUAL_FILTER: HookMode.FIRST,
    Hook.CELERY_TASKS: HookMode.ALL,
}
