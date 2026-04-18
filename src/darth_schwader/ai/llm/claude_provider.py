from __future__ import annotations

import json
from pathlib import Path

from anthropic import AsyncAnthropic

from darth_schwader.ai.contracts import AiRunContext, StrategySignal
from darth_schwader.quant.features import Features

MODEL_NAME = "claude-3-5-sonnet-latest"
MAX_TOKENS = 2048
PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "strategy_selection.md"


class ClaudeStrategySelector:
    def __init__(self, api_key: str) -> None:
        self._client = AsyncAnthropic(api_key=api_key)

    async def select(self, features: Features, context: AiRunContext) -> list[StrategySignal]:
        if not PROMPT_PATH.exists():
            raise FileNotFoundError(f"missing prompt file: {PROMPT_PATH}")
        prompt = PROMPT_PATH.read_text(encoding="utf-8")
        message = await self._client.messages.create(
            model=MODEL_NAME,
            max_tokens=MAX_TOKENS,
            system=prompt,
            messages=[
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "features": {
                                "underlying": features.underlying,
                                "iv_rank": str(features.iv_rank),
                                "iv_percentile": str(features.iv_percentile),
                                "term_slope": str(features.term_slope),
                                "skew": str(features.skew),
                                "rv_iv_spread": str(features.rv_iv_spread),
                                "regime": int(features.regime),
                            },
                            "context": context.model_dump(mode="json"),
                        }
                    ),
                }
            ],
        )
        text_chunks = [block.text for block in message.content if getattr(block, "type", "") == "text"]
        payload = json.loads("".join(text_chunks) or "[]")
        return [StrategySignal.model_validate(item) for item in payload]


__all__ = ["ClaudeStrategySelector"]
