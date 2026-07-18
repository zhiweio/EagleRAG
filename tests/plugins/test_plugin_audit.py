"""PluginAudit multi-sink telemetry + scope_routing error handling tests."""

from __future__ import annotations

import logging

import fakeredis
import pytest

from eagle_rag.plugins.audit import EVENT_NAME, PluginAudit, redis_key
from eagle_rag.plugins.context import PluginAudit as PluginAuditReexport


def test_context_reexports_plugin_audit() -> None:
    assert PluginAuditReexport is PluginAudit


def test_log_decision_appends_to_ring_buffer() -> None:
    audit = PluginAudit(redis_enabled=False)
    audit.log_decision(
        category="classify_chunk",
        target_collection="eagle_text_biomed",
        confidence=0.8,
        reason="biomed_term_keyword",
        plugin_namespace="biomed",
    )
    recent = audit.recent()
    assert len(recent) == 1
    entry = recent[0]
    assert entry["category"] == "classify_chunk"
    assert entry["target_collection"] == "eagle_text_biomed"
    assert entry["confidence"] == 0.8
    assert entry["plugin_namespace"] == "biomed"
    assert entry["event"] == EVENT_NAME
    assert "ts" in entry


def test_log_decision_emits_structured_event() -> None:
    audit = PluginAudit(redis_enabled=False)
    audit.log_decision(
        category="route_query",
        target_collection="eagle_text_biomed",
        confidence=0.75,
        reason="umls_hit",
        plugin_namespace="biomed",
        extra={"entity": "HER2"},
    )
    entry = audit.recent()[0]
    assert entry["event"] == EVENT_NAME
    assert entry["category"] == "route_query"
    assert entry["extra"]["entity"] == "HER2"


def test_ring_buffer_caps_at_max_entries() -> None:
    audit = PluginAudit(redis_enabled=False, ring_cap=1000)
    for i in range(1500):
        audit.log_decision(category="bulk", reason=f"r{i}")
    assert len(audit.recent(limit=10_000)) == 1000
    recent = audit.recent(limit=10_000)
    assert recent[-1]["reason"] == "r1499"


def test_recent_respects_limit() -> None:
    audit = PluginAudit(redis_enabled=False)
    for i in range(10):
        audit.log_decision(category="c", reason=f"r{i}")
    assert len(audit.recent(limit=3)) == 3
    assert audit.recent(limit=3)[-1]["reason"] == "r9"


def test_clear_empties_buffer() -> None:
    audit = PluginAudit(redis_enabled=False)
    audit.log_decision(category="c")
    audit.clear()
    assert audit.recent() == []


def test_redis_recent_window_lpush_ltrim() -> None:
    client = fakeredis.FakeRedis(decode_responses=True)
    audit = PluginAudit(
        redis_client=client,
        redis_enabled=True,
        ring_cap=3,
        default_namespace="biomed",
        health_limit=10,
    )
    for i in range(5):
        audit.log_decision(category="c", reason=f"r{i}", plugin_namespace="biomed")
    key = redis_key("biomed")
    assert client.llen(key) == 3
    recent = audit.recent(limit=10)
    assert len(recent) == 3
    assert recent[-1]["reason"] == "r4"
    assert audit.audit_stats()["source"] == "redis"


def test_redis_down_falls_back_to_memory() -> None:
    class _Boom:
        def lpush(self, *_a: object, **_k: object) -> None:
            raise RuntimeError("redis down")

        def lrange(self, *_a: object, **_k: object) -> list[str]:
            raise RuntimeError("redis down")

        def ltrim(self, *_a: object, **_k: object) -> None:
            raise RuntimeError("redis down")

        def delete(self, *_a: object, **_k: object) -> None:
            raise RuntimeError("redis down")

    audit = PluginAudit(redis_client=_Boom(), redis_enabled=True, default_namespace="core")
    audit.log_decision(category="c", reason="kept")
    recent = audit.recent(limit=5)
    assert len(recent) == 1
    assert recent[0]["reason"] == "kept"
    assert audit.audit_stats()["source"] == "memory"


def test_disabled_audit_is_noop() -> None:
    audit = PluginAudit(enabled=False, redis_enabled=False)
    audit.log_decision(category="c")
    assert audit.recent() == []


def test_scope_routing_tag_failure_is_logged_not_silent(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """scope_routing must not silently swallow tag-resolution exceptions."""
    from eagle_rag.plugins import scope_routing
    from eagle_rag.plugins.encoder_registry import EncoderRegistry
    from eagle_rag.plugins.routing import CollectionQueryPlan, QueryRouteDecision

    def _boom(*_a: object, **_k: object) -> list[str]:
        raise RuntimeError("tag DB down")

    monkeypatch.setattr(
        "eagle_rag.index.tag_catalog.resolve_tags_to_document_ids",
        _boom,
    )
    audit = PluginAudit(redis_enabled=False)
    decision = QueryRouteDecision(
        plans=(CollectionQueryPlan(collection="eagle_text", encoder="text-embedding-v4"),)
    )
    with caplog.at_level(logging.WARNING, logger="eagle_rag.plugins.scope_routing"):
        out, changed = scope_routing.apply_scope_aware_union(
            decision,
            plugin_namespace="biomed",
            encoder_registry=EncoderRegistry(),
            scope_tags=["oncology"],
            audit=audit,
        )
    assert changed is False
    assert out == decision
    assert any("tag resolution failed" in r.message.lower() for r in caplog.records)
    assert any(
        e["category"] == "scope_routing_error" and e.get("reason") == "tag_resolution_failed"
        for e in audit.recent()
    )


def test_hookbus_failures_route_through_plugin_audit() -> None:
    from eagle_rag.plugins.hookbus import HookBus, HookContext
    from eagle_rag.plugins.hooks import Hook

    audit = PluginAudit(redis_enabled=False)
    bus = HookBus(audit=audit)
    ctx = HookContext(plugin_namespace="core")

    def fail(_ctx: HookContext) -> str:
        raise RuntimeError("nope")

    def ok(_ctx: HookContext) -> str:
        return "piece"

    bus.subscribe(Hook.QUERY_ASSEMBLE, fail, plugin_name="a")
    bus.subscribe(Hook.QUERY_ASSEMBLE, ok, plugin_name="b")
    assert bus.invoke_all(Hook.QUERY_ASSEMBLE, ctx) == ["piece"]
    failures = bus.audit_failures()
    assert len(failures) == 1
    assert failures[0]["error"] == "nope"
    assert failures[0]["plugin"] == "a"
    assert any(e["category"] == "hook_failure" for e in audit.recent())
