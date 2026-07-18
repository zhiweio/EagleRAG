"""Plugin namespace resolution for repositories and API (G9/G19)."""

from __future__ import annotations

from fastapi import HTTPException

from eagle_rag.config import get_settings

__all__ = ["resolve_namespace", "resolve_namespace_or_raise"]


def resolve_namespace(requested: str | None = None) -> str:
    """Return the effective plugin_namespace for this instance."""
    settings = get_settings()
    default = settings.plugins.default_namespace
    if requested is None or requested == "":
        return default
    if settings.plugins.allow_namespace_override:
        return requested
    if requested != default:
        raise HTTPException(
            status_code=403,
            detail=f"plugin_namespace {requested!r} does not match instance {default!r}",
        )
    return default


def resolve_namespace_or_raise(requested: str | None = None) -> str:
    """Alias for ``resolve_namespace`` (explicit naming at call sites)."""
    return resolve_namespace(requested)
