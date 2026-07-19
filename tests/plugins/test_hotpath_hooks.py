"""Hot-path hook wiring tests (PARSE / CHUNK / QUERY_ASSEMBLE)."""

from __future__ import annotations

from types import SimpleNamespace

from eagle_rag.plugins.hookbus import HookBus
from eagle_rag.plugins.hooks import Hook
from eagle_rag.plugins.hotpath_hooks import (
    apply_chunk_hook,
    apply_parse_hook,
    apply_query_assemble,
)


def test_apply_parse_and_chunk_hooks(monkeypatch) -> None:
    bus = HookBus()
    bus.subscribe(
        Hook.PARSE,
        lambda _ctx, value, **_kw: SimpleNamespace(chunks=getattr(value, "chunks", []) + ["x"]),
        namespace="core",
    )
    bus.subscribe(
        Hook.CHUNK,
        lambda _ctx, nodes, **_kw: list(nodes) + ["extra"],
        namespace="core",
    )

    class _Mgr:
        default_namespace = "core"

    _Mgr.bus = bus  # type: ignore[attr-defined]

    monkeypatch.setattr(
        "eagle_rag.plugins.hotpath_hooks.get_plugin_manager",
        lambda: _Mgr(),
    )
    monkeypatch.setattr(
        "eagle_rag.plugins.hotpath_hooks.get_settings",
        lambda: SimpleNamespace(plugins=SimpleNamespace(default_namespace="core")),
    )

    parsed = apply_parse_hook(SimpleNamespace(chunks=["a"]), file_name="a.sql")
    assert "x" in parsed.chunks
    chunked = apply_chunk_hook(["n1"], file_name="a.sql")
    assert chunked == ["n1", "extra"]


def test_apply_query_assemble(monkeypatch) -> None:
    bus = HookBus()
    bus.subscribe(
        Hook.QUERY_ASSEMBLE,
        lambda _ctx, query, **_kw: "[biomed entities: HER2]",
        namespace="biomed",
    )

    class _Mgr:
        default_namespace = "biomed"

    _Mgr.bus = bus  # type: ignore[attr-defined]

    monkeypatch.setattr(
        "eagle_rag.plugins.hotpath_hooks.get_plugin_manager",
        lambda: _Mgr(),
    )
    monkeypatch.setattr(
        "eagle_rag.plugins.hotpath_hooks.get_settings",
        lambda: SimpleNamespace(
            plugins=SimpleNamespace(default_namespace="biomed", query_assemble_enabled=True)
        ),
    )

    out = apply_query_assemble("HER2 mutation", plugin_namespace="biomed")
    assert "HER2 mutation" in out
    assert "biomed entities" in out
