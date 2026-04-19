from __future__ import annotations

import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI

from darth_schwader.ai.contracts import AiRunContext, StrategySignal
from darth_schwader.quant.features import Features

MAX_TOKENS = 2048
PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "strategy_selection.md"
_CODE_FENCE_OPEN_RE = re.compile(r"^\s*```(?:json)?\s*", re.IGNORECASE)
_CODE_FENCE_CLOSE_RE = re.compile(r"\s*```\s*$")
_JSON_BLOCK_RE = re.compile(r"(\{.*\}|\[.*\])", re.DOTALL)


class OpenRouterStrategySelector:
    """OpenRouter-backed strategy selector using the OpenAI-compatible API."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        http_referer: str | None = None,
        app_title: str | None = None,
    ) -> None:
        default_headers: dict[str, str] = {}
        if http_referer is not None:
            default_headers["HTTP-Referer"] = http_referer
        if app_title is not None:
            default_headers["X-Title"] = app_title
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            default_headers=default_headers or None,
        )
        self._model = model

    async def select(
        self,
        features: Features,
        context: AiRunContext,
        *,
        setups: Sequence[dict[str, Any]] | None = None,
    ) -> list[StrategySignal]:
        if not PROMPT_PATH.exists():
            raise FileNotFoundError(f"missing prompt file: {PROMPT_PATH}")
        prompt = PROMPT_PATH.read_text(encoding="utf-8")
        user_payload: dict[str, Any] = {
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
        if setups:
            user_payload["setups"] = list(setups)
        response = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=MAX_TOKENS,
            messages=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": json.dumps(user_payload),
                },
            ],
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("OpenRouter response did not include message content")
        payload = json.loads(_extract_json(content))
        if isinstance(payload, dict):
            items = payload.get("signals", [])
        elif isinstance(payload, list):
            items = payload
        else:
            raise ValueError("OpenRouter response must decode to a JSON object or array")
        if not isinstance(items, list):
            raise ValueError("OpenRouter response 'signals' value must be a list")
        return [StrategySignal.model_validate(item) for item in items]


def _extract_json(text: str) -> str:
    normalized = text.strip()
    normalized = _CODE_FENCE_OPEN_RE.sub("", normalized, count=1)
    normalized = _CODE_FENCE_CLOSE_RE.sub("", normalized, count=1)
    match = _JSON_BLOCK_RE.search(normalized)
    if match is None:
        raise ValueError(f"no JSON object or array found in model output: {text[:200]!r}")
    return match.group(1)


__all__ = ["OpenRouterStrategySelector"]
