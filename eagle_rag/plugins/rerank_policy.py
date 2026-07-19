"""Namespace-level post-RRF rerank policy (core vs domain plugin hooks)."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from eagle_rag.plugins.hookbus import HookBus

__all__ = [
    "RerankPolicy",
    "rerank_model_label",
    "resolve_rerank_policy",
    "uses_domain_rerank",
]


class RerankPolicy(StrEnum):
    """How fused retrieval hits are re-ranked after RRF."""

    GENERAL = "general"
    DOMAIN = "domain"
    NONE = "none"


def resolve_rerank_policy(
    plugin_namespace: str | None,
    hook_bus: HookBus | None = None,
) -> RerankPolicy:
    """Resolve rerank policy for a plugin namespace."""
    from eagle_rag.config import get_settings, plugin_options
    from eagle_rag.plugins.hooks import Hook

    if plugin_namespace:
        try:
            opts = plugin_options(plugin_namespace, get_settings())
            raw = opts.get("rerank_policy")
            if raw is None and opts.get("use_general_rerank") is False:
                raw = RerankPolicy.DOMAIN
            if raw is not None:
                return RerankPolicy(str(raw).lower())
        except Exception:  # noqa: BLE001
            pass

    if hook_bus is not None and plugin_namespace:
        from eagle_rag.plugins.hookbus import HookContext

        ctx = HookContext(plugin_namespace=plugin_namespace)
        if hook_bus.has_subscribers(Hook.RERANK_MERGED, ctx):
            return RerankPolicy.DOMAIN

    return RerankPolicy.GENERAL


def uses_domain_rerank(
    plugin_namespace: str | None,
    hook_bus: HookBus | None = None,
) -> bool:
    return resolve_rerank_policy(plugin_namespace, hook_bus) == RerankPolicy.DOMAIN


def rerank_model_label(
    plugin_namespace: str | None,
    hook_bus: HookBus | None = None,
) -> str:
    policy = resolve_rerank_policy(plugin_namespace, hook_bus)
    if policy == RerankPolicy.DOMAIN:
        try:
            from eagle_rag.config import get_settings, plugin_options

            if plugin_namespace:
                enc = plugin_options(plugin_namespace, get_settings()).get(
                    "domain_rerank_encoder", "medcpt-rerank"
                )
                return str(enc)
        except Exception:  # noqa: BLE001
            pass
        return "domain"
    if policy == RerankPolicy.GENERAL:
        return "qwen3-rerank"
    return "passthrough"
