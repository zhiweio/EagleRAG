"""Routing data models: ``RouteContext`` (input) and ``RouteDecision`` (output).

- ``RouteContext``: immutable routing input carrying the query text and context
  (mode/scope/kb_name/attachments).
- ``RouteDecision``: immutable routing output carrying the effective mode, selected
  retrieval methods, reason, and decision source. ``to_dict()`` is used by SSE step
  events and the ``EagleMultimodalQueryEngine.custom_query`` boundary conversion.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = ["RouteContext", "RouteDecision"]


@dataclass(frozen=True)
class RouteContext:
    """Routing decision input context."""

    query: str
    mode: str | None = None
    scope: list[str] | None = None
    kb_name: str | None = None
    has_image_attachment: bool = False


@dataclass(frozen=True)
class RouteDecision:
    """Routing decision result.

    Attributes:
        mode: effective routing mode (auto/text/visual/hybrid).
        selected: selected retrieval methods, e.g. ``["text"]`` / ``["visual"]`` /
            ``["text", "visual"]``.
        reason: human-readable decision reason.
        selector: decision source identifier
            (forced/attachment/llm/heuristic/default).
    """

    mode: str
    selected: list[str]
    reason: str
    kb_name: str | None = None
    selector: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for SSE step events and the generation module's dict contract."""
        return {
            "mode": self.mode,
            "selected": list(self.selected),
            "reason": self.reason,
            "kb_name": self.kb_name,
            "selector": self.selector,
        }
