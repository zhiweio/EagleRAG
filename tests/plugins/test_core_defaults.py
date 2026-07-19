"""Core default query classifier (G4)."""

from __future__ import annotations

from eagle_rag.plugins import reset_plugin_manager
from eagle_rag.plugins.core_defaults import _default_classify_query
from eagle_rag.plugins.hookbus import HookContext


def test_default_query_text_only() -> None:
    reset_plugin_manager()
    ctx = HookContext(plugin_namespace="core")
    decision = _default_classify_query(ctx, "hello", route_mode="text")
    assert decision is not None
    collections = {p.collection for p in decision.plans}
    assert collections == {"eagle_text"}


def test_default_query_hybrid_adds_visual() -> None:
    ctx = HookContext(plugin_namespace="core")
    decision = _default_classify_query(ctx, "chart?", route_mode="hybrid")
    assert decision is not None
    collections = {p.collection for p in decision.plans}
    assert collections == {"eagle_text", "eagle_visual"}
