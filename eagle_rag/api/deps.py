"""FastAPI dependencies (G19 namespace trust boundary)."""

from __future__ import annotations

from typing import Annotated

from fastapi import Header, HTTPException

from eagle_rag.config import get_settings
from eagle_rag.db.namespace import resolve_namespace

__all__ = ["OptionalPluginNamespace", "enforce_plugin_namespace_header"]


def enforce_plugin_namespace_header(
    x_plugin_namespace: Annotated[str | None, Header(alias="X-Plugin-Namespace")] = None,
) -> str:
    """Resolve instance namespace; reject explicit mismatch with 403 (G19)."""
    if x_plugin_namespace:
        return resolve_namespace(x_plugin_namespace)
    return resolve_namespace(None)


OptionalPluginNamespace = Annotated[str, Header(alias="X-Plugin-Namespace")]


def validate_request_namespace(plugin_namespace: str | None) -> None:
    """Validate optional body field ``plugin_namespace`` against the instance."""
    if plugin_namespace is None:
        return
    settings = get_settings()
    if settings.plugins.allow_namespace_override:
        return
    if plugin_namespace != settings.plugins.default_namespace:
        raise HTTPException(
            status_code=403,
            detail=(
                f"plugin_namespace {plugin_namespace!r} does not match instance "
                f"{settings.plugins.default_namespace!r}"
            ),
        )
