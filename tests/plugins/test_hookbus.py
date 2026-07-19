"""HookBus invocation semantics and G13 exception behavior."""

from __future__ import annotations

import pytest

from eagle_rag.plugins.errors import HookInvocationError
from eagle_rag.plugins.hookbus import HookBus, HookContext
from eagle_rag.plugins.hooks import Hook


def test_invoke_first_priority_and_abstain() -> None:
    bus = HookBus()
    ctx = HookContext(plugin_namespace="core")
    calls: list[str] = []

    def high(_ctx: HookContext) -> None:
        calls.append("high")
        return None

    def low(_ctx: HookContext) -> str:
        calls.append("low")
        return "ok"

    bus.subscribe(Hook.CLASSIFY_CHUNK, high, priority=10)
    bus.subscribe(Hook.CLASSIFY_CHUNK, low, priority=1)
    assert bus.invoke_first(Hook.CLASSIFY_CHUNK, ctx) == "ok"
    assert calls == ["high", "low"]


def test_invoke_first_namespace_filter() -> None:
    bus = HookBus()
    ctx = HookContext(plugin_namespace="biomed")

    bus.subscribe(
        Hook.CLASSIFY_CHUNK,
        lambda _c: "biomed",
        namespace="biomed",
    )
    bus.subscribe(
        Hook.CLASSIFY_CHUNK,
        lambda _c: "core",
        namespace="core",
    )
    assert bus.invoke_first(Hook.CLASSIFY_CHUNK, ctx) == "biomed"


def test_invoke_first_fail_fast() -> None:
    bus = HookBus()
    ctx = HookContext(plugin_namespace="core")

    def boom(_ctx: HookContext) -> None:
        raise ValueError("boom")

    bus.subscribe(Hook.CLASSIFY_CHUNK, boom, plugin_name="bad")
    with pytest.raises(HookInvocationError) as exc_info:
        bus.invoke_first(Hook.CLASSIFY_CHUNK, ctx)
    assert exc_info.value.hook == "CLASSIFY_CHUNK"


def test_invoke_all_degrades_on_failure() -> None:
    bus = HookBus()
    ctx = HookContext(plugin_namespace="core")

    def fail(_ctx: HookContext) -> str:
        raise RuntimeError("nope")

    def ok(_ctx: HookContext) -> str:
        return "piece"

    bus.subscribe(Hook.QUERY_ASSEMBLE, fail, plugin_name="a")
    bus.subscribe(Hook.QUERY_ASSEMBLE, ok, plugin_name="b")
    assert bus.invoke_all(Hook.QUERY_ASSEMBLE, ctx) == ["piece"]
    assert bus.audit_failures()


def test_invoke_transform_chains() -> None:
    bus = HookBus()
    ctx = HookContext(plugin_namespace="core")

    bus.subscribe(Hook.PARSE, lambda _c, v: v + "b")
    bus.subscribe(Hook.PARSE, lambda _c, v: v + "c")
    assert bus.invoke_transform(Hook.PARSE, ctx, "a") == "abc"
