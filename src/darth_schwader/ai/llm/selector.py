from __future__ import annotations

from typing import Protocol

from darth_schwader.ai.contracts import AiRunContext, StrategySignal
from darth_schwader.quant.features import Features


class LLMStrategySelector(Protocol):
    async def select(self, features: Features, context: AiRunContext) -> list[StrategySignal]:
        ...


class NullLLMSelector:
    async def select(self, features: Features, context: AiRunContext) -> list[StrategySignal]:
        return []


__all__ = ["LLMStrategySelector", "NullLLMSelector"]
