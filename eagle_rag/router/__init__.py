"""Query routing package: strategy-based routing decisions and composite retrieval engine.

- ``route_query(ctx)``: pure-function routing decision based on ``FallbackChain``.
- ``EagleRouterQueryEngine``: query engine combining text/visual retrievers.
- ``RouteContext`` / ``RouteDecision``: routing input context and decision result.
"""

from __future__ import annotations

from eagle_rag.router.models import RouteContext, RouteDecision
from eagle_rag.router.router_engine import EagleRouterQueryEngine, route_query

__all__ = ["RouteContext", "RouteDecision", "EagleRouterQueryEngine", "route_query"]
