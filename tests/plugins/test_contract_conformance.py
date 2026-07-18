"""Plugin contract conformance tests (P2-8) + RAG-only / hot-path assertions."""

from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest

from eagle_rag.plugins.contract import PluginManifest
from eagle_rag.plugins.errors import PluginLoadError
from eagle_rag.plugins.hotpath_hooks import apply_chunk_hook, apply_parse_hook, apply_query_assemble
from eagle_rag.plugins.hookbus import HookBus, HookContext
from eagle_rag.plugins.hooks import Hook
from eagle_rag.plugins.manager import PluginManager
from eagle_rag.plugins.mcp_registry import (
    FORBIDDEN_MCP_TOOL_FRAGMENTS,
    assert_rag_only_tool_name,
)


@pytest.mark.parametrize(
    "module_path",
    [
        "eagle_rag.plugins.core_defaults",
        "plugins._template",
    ],
)
def test_plugin_exports_contract(module_path: str) -> None:
    mod = importlib.import_module(module_path)
    plugin = getattr(mod, "plugin")
    assert hasattr(plugin, "manifest")
    assert isinstance(plugin.manifest, PluginManifest)
    assert plugin.manifest.namespace
    assert plugin.manifest.version
    for method in ("register_hooks", "on_load", "on_unload", "ensure_collections"):
        assert callable(getattr(plugin, method))


def test_template_exposes_explicit_mcp_registration() -> None:
    mod = importlib.import_module("plugins._template")
    plugin = mod.plugin
    assert callable(getattr(plugin, "register_mcp_tools", None))


def test_manager_rejects_mismatched_default_namespace(monkeypatch: pytest.MonkeyPatch) -> None:
    from eagle_rag.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(
        settings.plugins,
        "enabled",
        ["eagle_rag.plugins.core_defaults", "plugins.lakehouse_bi"],
    )
    monkeypatch.setattr(settings.plugins, "default_namespace", "biomed")
    mgr = PluginManager(settings)
    with pytest.raises(PluginLoadError):
        mgr.load_all()


def test_rag_only_mcp_tool_names_reject_side_effects() -> None:
    for fragment in ("execute_sql", "run_sql", "send_email", "place_order", "write_db"):
        with pytest.raises(ValueError, match="RAG-only"):
            assert_rag_only_tool_name(f"acme_{fragment}")
    assert_rag_only_tool_name("acme_retrieve_assets")
    assert_rag_only_tool_name("biomed_query_entities")
    assert all(isinstance(f, str) and f for f in FORBIDDEN_MCP_TOOL_FRAGMENTS)


def test_hotpath_hooks_invoke_parse_chunk_query_assemble(monkeypatch: pytest.MonkeyPatch) -> None:
    bus = HookBus()
    seen: list[str] = []

    def on_parse(ctx: HookContext, parse_result: object, **kwargs: object) -> object:
        del ctx, kwargs
        seen.append("PARSE")
        if isinstance(parse_result, dict):
            out = dict(parse_result)
            out["enriched"] = True
            return out
        return parse_result

    def on_chunk(ctx: HookContext, nodes: list[object], **kwargs: object) -> list[object]:
        del ctx, kwargs
        seen.append("CHUNK")
        return list(nodes) + [{"id": "extra"}]

    def on_assemble(ctx: HookContext, query: str, **kwargs: object) -> str:
        del ctx, kwargs
        seen.append("QUERY_ASSEMBLE")
        return "[expanded]"

    bus.subscribe(Hook.PARSE, on_parse, priority=10, namespace="core", plugin_name="t")
    bus.subscribe(Hook.CHUNK, on_chunk, priority=10, namespace="core", plugin_name="t")
    bus.subscribe(Hook.QUERY_ASSEMBLE, on_assemble, priority=10, namespace="core", plugin_name="t")

    class _Mgr:
        default_namespace = "core"

    _Mgr.bus = bus  # type: ignore[attr-defined]

    monkeypatch.setattr(
        "eagle_rag.plugins.hotpath_hooks.get_plugin_manager",
        lambda: _Mgr(),
    )
    monkeypatch.setattr(
        "eagle_rag.plugins.hotpath_hooks.get_settings",
        lambda: SimpleNamespace(
            plugins=SimpleNamespace(
                default_namespace="core",
                query_assemble_enabled=True,
            )
        ),
    )

    parsed = apply_parse_hook({"ok": True}, file_name="a.md")
    assert parsed.get("enriched") is True

    nodes = apply_chunk_hook([{"id": "a"}], file_name="a.md")
    assert len(nodes) == 2

    q = apply_query_assemble("her2")
    assert "her2" in q and "expanded" in q
    assert seen == ["PARSE", "CHUNK", "QUERY_ASSEMBLE"]
