"""Router LLM factory: creates LLM instances based on ``settings.llm.provider``.

Decouples LLM creation from routing logic; adding a new provider (e.g. openai) only
requires a new branch here without touching ``LLMIntentSelector``. Returns ``None``
when ``api_key`` is not configured, letting the selector fall back to heuristics.
"""

from __future__ import annotations

from typing import Any

__all__ = ["create_router_llm"]


def create_router_llm(llm_cfg: Any) -> Any | None:
    """Create a router LLM by ``llm_cfg.provider``; return None when api_key is missing.

    Args:
        llm_cfg: ``settings.llm`` (``LLMSettings``).
    """
    if not llm_cfg.api_key:
        return None
    provider = (llm_cfg.provider or "dashscope").lower()
    if provider == "dashscope":
        from llama_index.llms.dashscope import DashScope  # type: ignore

        return DashScope(
            model=llm_cfg.model,
            api_key=llm_cfg.api_key,
            api_base=llm_cfg.base_url,
        )
    # Unknown provider: return None so LLMIntentSelector falls back to heuristics.
    return None
