"""In-process hook bus with namespace filtering and G13 exception semantics."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from eagle_rag.plugins.errors import HookInvocationError
from eagle_rag.plugins.hooks import HOOK_MODES, Hook, HookMode
from eagle_rag.telemetry import get_logger

__all__ = ["HookBus", "HookContext", "HookSubscriber"]

logger = get_logger(__name__)


@dataclass(frozen=True)
class HookSubscriber:
    """Registered hook callback."""

    fn: Callable[..., Any]
    priority: int
    namespace: str | None
    plugin_name: str | None = None


@dataclass
class HookContext:
    """Common context passed to hook subscribers."""

    plugin_namespace: str
    kb_name: str | None = None
    document_id: str | None = None
    extra: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.extra is None:
            self.extra = {}


class HookBus:
    """Process-wide hook dispatcher."""

    def __init__(self) -> None:
        self._subscribers: dict[Hook, list[HookSubscriber]] = {}
        self._audit_failures: list[dict[str, Any]] = []

    def subscribe(
        self,
        hook: Hook | str,
        fn: Callable[..., Any],
        *,
        priority: int = 0,
        namespace: str | None = None,
        plugin_name: str | None = None,
    ) -> None:
        hook_key = Hook(hook) if not isinstance(hook, Hook) else hook
        subs = self._subscribers.setdefault(hook_key, [])
        subs.append(
            HookSubscriber(
                fn=fn,
                priority=priority,
                namespace=namespace,
                plugin_name=plugin_name,
            )
        )
        subs.sort(key=lambda s: s.priority, reverse=True)

    def _filtered(self, hook: Hook, ctx: HookContext) -> list[HookSubscriber]:
        return [
            s
            for s in self._subscribers.get(hook, [])
            if s.namespace is None or s.namespace == ctx.plugin_namespace
        ]

    def invoke_first(self, hook: Hook | str, ctx: HookContext, *args: Any, **kwargs: Any) -> Any:
        hook_key = Hook(hook) if not isinstance(hook, Hook) else hook
        for sub in self._filtered(hook_key, ctx):
            try:
                result = sub.fn(ctx, *args, **kwargs)
            except Exception as exc:
                raise HookInvocationError(
                    str(exc),
                    hook=hook_key.value,
                    plugin=sub.plugin_name,
                    namespace=sub.namespace,
                ) from exc
            if result is not None:
                return result
        return None

    def invoke_transform(
        self,
        hook: Hook | str,
        ctx: HookContext,
        value: Any,
        **kwargs: Any,
    ) -> Any:
        hook_key = Hook(hook) if not isinstance(hook, Hook) else hook
        current = value
        for sub in self._filtered(hook_key, ctx):
            try:
                if inspect.iscoroutinefunction(sub.fn):
                    raise TypeError("invoke_transform does not support async hooks")
                current = sub.fn(ctx, current, **kwargs)
            except Exception as exc:
                raise HookInvocationError(
                    str(exc),
                    hook=hook_key.value,
                    plugin=sub.plugin_name,
                    namespace=sub.namespace,
                ) from exc
        return current

    def invoke_all(
        self,
        hook: Hook | str,
        ctx: HookContext,
        *args: Any,
        **kwargs: Any,
    ) -> list[Any]:
        hook_key = Hook(hook) if not isinstance(hook, Hook) else hook
        results: list[Any] = []
        for sub in self._filtered(hook_key, ctx):
            try:
                result = sub.fn(ctx, *args, **kwargs)
            except Exception as exc:
                logger.warning(
                    "QUERY_ASSEMBLE subscriber failed (degraded): %s",
                    exc,
                    extra={
                        "hook": hook_key.value,
                        "plugin": sub.plugin_name,
                        "namespace": sub.namespace,
                    },
                )
                self._audit_failures.append(
                    {
                        "hook": hook_key.value,
                        "plugin": sub.plugin_name,
                        "namespace": sub.namespace,
                        "error": str(exc),
                    }
                )
                continue
            if result is not None:
                if isinstance(result, list):
                    results.extend(result)
                else:
                    results.append(result)
        return results

    def invoke(self, hook: Hook | str, ctx: HookContext, *args: Any, **kwargs: Any) -> Any:
        hook_key = Hook(hook) if not isinstance(hook, Hook) else hook
        mode = HOOK_MODES.get(hook_key, HookMode.FIRST)
        if mode == HookMode.ALL:
            return self.invoke_all(hook_key, ctx, *args, **kwargs)
        if mode == HookMode.TRANSFORM:
            if not args:
                raise ValueError("invoke_transform requires an initial value")
            return self.invoke_transform(hook_key, ctx, args[0], **kwargs)
        return self.invoke_first(hook_key, ctx, *args, **kwargs)

    def audit_failures(self) -> list[dict[str, Any]]:
        return list(self._audit_failures)
