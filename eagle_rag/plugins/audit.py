"""Plugin decision telemetry: typed events with multi-sink fan-out.

Sinks (all best-effort, never raise into callers):

1. In-memory ring buffer (process-local fallback)
2. Redis LIST (``LPUSH`` + ``LTRIM``) for cross-process recent window
3. AI JSONL via ``get_ai_logger`` (durable, aggregator-consumable)
4. Prometheus counters for aggregate dashboards
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from eagle_rag.telemetry import get_ai_logger, get_context, get_logger

__all__ = [
    "EVENT_NAME",
    "PluginAudit",
    "PluginAuditEvent",
    "redis_key",
]

EVENT_NAME = "plugin_audit_decision"
_DEFAULT_RING_CAP = 1000
_DEFAULT_HEALTH_LIMIT = 50
_EXTRA_MAX_CHARS = 2048

_LOGGER = get_logger(__name__)
_AI_LOGGER = get_ai_logger(__name__)

# Lazy Redis client for the default factory (process-wide).
_redis_client: Any = None
_redis_client_initialized = False
_redis_warn_emitted = False


def redis_key(namespace: str) -> str:
    """Redis LIST key for the recent-decision window of a plugin namespace."""
    return f"eagle:plugin_audit:{namespace}:recent"


def reset_audit_redis_client() -> None:
    """Clear the default Redis client cache (tests only)."""
    global _redis_client, _redis_client_initialized, _redis_warn_emitted
    _redis_client = None
    _redis_client_initialized = False
    _redis_warn_emitted = False


def _default_redis_factory() -> Any | None:
    """Return a shared ``redis.Redis`` client, or ``None`` when unavailable."""
    global _redis_client, _redis_client_initialized, _redis_warn_emitted
    if _redis_client_initialized:
        return _redis_client
    try:
        from eagle_rag.config import get_settings

        settings = get_settings()
        url = settings.mcp.redis_url or settings.celery.broker_url
        if not url:
            _redis_client = None
        else:
            import redis

            _redis_client = redis.Redis.from_url(url, decode_responses=True)
    except Exception as exc:  # noqa: BLE001
        if not _redis_warn_emitted:
            _LOGGER.warning("plugin audit Redis unavailable: %s", exc)
            _redis_warn_emitted = True
        _redis_client = None
    _redis_client_initialized = True
    return _redis_client


def _truncate_extra(extra: dict[str, Any] | None) -> dict[str, Any]:
    if not extra:
        return {}
    out: dict[str, Any] = {}
    for key, value in extra.items():
        if isinstance(value, str) and len(value) > _EXTRA_MAX_CHARS:
            out[key] = value[:_EXTRA_MAX_CHARS] + "…"
        else:
            out[key] = value
    return out


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass
class PluginAuditEvent:
    """One classification / routing / hook decision event."""

    category: str
    event: str = EVENT_NAME
    ts: str = field(default_factory=_utc_now_iso)
    target_collection: str | None = None
    confidence: float | None = None
    reason: str | None = None
    plugin_namespace: str | None = None
    kb_name: str | None = None
    document_id: str | None = None
    error: str | None = None
    trace_id: str | None = None
    span_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize omitting ``None`` values (keeps JSONL / Redis compact)."""
        data = asdict(self)
        return {k: v for k, v in data.items() if v is not None and v != {}}


class PluginAudit:
    """Multi-sink decision telemetry facade.

    ``log_decision`` is the stable call-site API. Sinks never raise into callers.
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        ring_cap: int = _DEFAULT_RING_CAP,
        redis_enabled: bool = True,
        redis_client: Any | None = None,
        redis_client_factory: Callable[[], Any | None] | None = None,
        default_namespace: str = "core",
        health_limit: int = _DEFAULT_HEALTH_LIMIT,
    ) -> None:
        self.enabled = enabled
        self.ring_cap = max(1, ring_cap)
        self.redis_enabled = redis_enabled
        self._redis_client = redis_client
        self._redis_client_factory = redis_client_factory or _default_redis_factory
        self.default_namespace = default_namespace
        self.health_limit = max(1, health_limit)
        self._entries: deque[dict[str, Any]] = deque(maxlen=self.ring_cap)
        self._last_source: str = "memory"

    @classmethod
    def from_settings(cls, settings: Any | None = None) -> PluginAudit:
        """Build from ``Settings.telemetry`` plugin-audit knobs."""
        if settings is None:
            from eagle_rag.config import get_settings

            settings = get_settings()
        tel = settings.telemetry
        return cls(
            enabled=tel.plugin_audit_enabled,
            ring_cap=tel.plugin_audit_ring_cap,
            redis_enabled=tel.plugin_audit_redis_enabled,
            default_namespace=settings.plugins.default_namespace,
            health_limit=tel.plugin_audit_health_limit,
        )

    def _resolve_redis(self) -> Any | None:
        if not self.redis_enabled:
            return None
        if self._redis_client is not None:
            return self._redis_client
        try:
            return self._redis_client_factory()
        except Exception:  # noqa: BLE001
            return None

    def _build_event(
        self,
        *,
        category: str,
        target_collection: str | None,
        confidence: float | None,
        reason: str | None,
        plugin_namespace: str | None,
        error: str | None,
        extra: dict[str, Any] | None,
    ) -> PluginAuditEvent:
        ctx = get_context()
        return PluginAuditEvent(
            category=category,
            target_collection=target_collection,
            confidence=confidence,
            reason=reason,
            plugin_namespace=plugin_namespace or ctx.get("plugin_namespace"),
            kb_name=ctx.get("kb_name"),
            document_id=ctx.get("document_id") or ctx.get("doc_id"),
            error=error,
            trace_id=ctx.get("trace_id"),
            span_id=ctx.get("span_id"),
            extra=_truncate_extra(extra),
        )

    def log_decision(
        self,
        *,
        category: str,
        target_collection: str | None = None,
        confidence: float | None = None,
        reason: str | None = None,
        plugin_namespace: str | None = None,
        error: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        if not self.enabled:
            return
        try:
            event = self._build_event(
                category=category,
                target_collection=target_collection,
                confidence=confidence,
                reason=reason,
                plugin_namespace=plugin_namespace,
                error=error,
                extra=extra,
            )
            payload = event.to_dict()
            self._entries.append(payload)
            self._emit_redis(payload)
            self._emit_ai_log(event)
            self._emit_metrics(event)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("plugin audit log_decision failed", exc_info=True)

    def _emit_redis(self, payload: dict[str, Any]) -> None:
        client = self._resolve_redis()
        if client is None:
            self._last_source = "memory"
            return
        try:
            ns = payload.get("plugin_namespace") or self.default_namespace
            key = redis_key(str(ns))
            client.lpush(key, json.dumps(payload, ensure_ascii=False, default=str))
            client.ltrim(key, 0, self.ring_cap - 1)
            self._last_source = "redis"
        except Exception:  # noqa: BLE001
            self._last_source = "memory"
            _LOGGER.debug("plugin audit Redis write failed", exc_info=True)

    def _emit_ai_log(self, event: PluginAuditEvent) -> None:
        try:
            _AI_LOGGER.info(
                EVENT_NAME,
                category=event.category,
                target_collection=event.target_collection,
                confidence=event.confidence,
                reason=event.reason,
                plugin_namespace=event.plugin_namespace,
                kb_name=event.kb_name,
                document_id=event.document_id,
                error=event.error,
                decision_extra=event.extra or {},
            )
        except Exception:  # noqa: BLE001
            # Fallback to ops logger (stdlib-compatible) when AI logger unavailable.
            _LOGGER.info(
                EVENT_NAME,
                extra={
                    "category": event.category,
                    "target_collection": event.target_collection,
                    "confidence": event.confidence,
                    "reason": event.reason,
                    "plugin_namespace": event.plugin_namespace,
                    "error": event.error,
                    "decision_extra": event.extra or {},
                },
            )

    def _emit_metrics(self, event: PluginAuditEvent) -> None:
        try:
            from eagle_rag.metrics import PLUGIN_AUDIT_DECISIONS, PLUGIN_AUDIT_RRF_DEDUPE

            outcome = "error" if event.error else "ok"
            ns = event.plugin_namespace or self.default_namespace or "unknown"
            PLUGIN_AUDIT_DECISIONS.labels(
                category=event.category,
                plugin_namespace=ns,
                outcome=outcome,
            ).inc()
            if event.reason == "rrf_dedupe":
                PLUGIN_AUDIT_RRF_DEDUPE.labels(plugin_namespace=ns).inc()
        except Exception:  # noqa: BLE001
            _LOGGER.debug("plugin audit metrics emit failed", exc_info=True)

    def recent(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Return newest-last decisions from Redis when available, else memory."""
        n = self.health_limit if limit is None else max(0, limit)
        if n == 0:
            return []
        client = self._resolve_redis()
        if client is not None:
            try:
                key = redis_key(self.default_namespace)
                raw = client.lrange(key, 0, n - 1)
                if raw:
                    items: list[dict[str, Any]] = []
                    for item in raw:
                        if isinstance(item, bytes):
                            item = item.decode("utf-8")
                        parsed = json.loads(item)
                        if isinstance(parsed, dict):
                            items.append(parsed)
                    # Redis LIST is newest-first (LPUSH); reverse for newest-last.
                    items.reverse()
                    self._last_source = "redis"
                    return items
            except Exception:  # noqa: BLE001
                _LOGGER.debug("plugin audit Redis read failed", exc_info=True)
        self._last_source = "memory"
        items = list(self._entries)
        return items[-n:]

    def clear(self) -> None:
        self._entries.clear()
        client = self._resolve_redis()
        if client is None:
            return
        try:
            client.delete(redis_key(self.default_namespace))
        except Exception:  # noqa: BLE001
            _LOGGER.debug("plugin audit Redis clear failed", exc_info=True)

    def audit_stats(self) -> dict[str, Any]:
        """Summary for ``GET /health/plugins``."""
        return {
            "buffer_size": self.ring_cap,
            "source": self._last_source,
            "enabled": self.enabled,
            "redis_enabled": self.redis_enabled,
        }
