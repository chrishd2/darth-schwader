from __future__ import annotations

from darth_schwader.ai.llm.openrouter_provider import OpenRouterStrategySelector
from darth_schwader.ai.llm.selector import LLMStrategySelector, NullLLMSelector
from darth_schwader.config import Settings


def build_selector(settings: Settings) -> LLMStrategySelector:
    if settings.ai_provider == "none" or settings.openrouter_api_key is None:
        return NullLLMSelector()
    return OpenRouterStrategySelector(
        api_key=settings.openrouter_api_key.get_secret_value(),
        model=settings.openrouter_model,
        base_url=settings.openrouter_base_url,
        http_referer=settings.openrouter_http_referer,
        app_title=settings.openrouter_app_title,
    )


__all__ = [
    "LLMStrategySelector",
    "NullLLMSelector",
    "OpenRouterStrategySelector",
    "build_selector",
]
