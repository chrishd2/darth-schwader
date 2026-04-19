from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import respx

from darth_schwader.ai.contracts import AiRunContext, StrategySignal
from darth_schwader.ai.llm.openrouter_provider import OpenRouterStrategySelector
from darth_schwader.quant.features import Features
from darth_schwader.quant.regime import VolRegime

OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"


@pytest.fixture
def valid_signal_payload() -> dict[str, object]:
    return {
        "signal_id": "sig-aapl-vertical-001",
        "strategy_type": "VERTICAL_SPREAD",
        "underlying": "AAPL",
        "direction": "LONG",
        "legs": [
            {
                "occ_symbol": "AAPL  260619C00195000",
                "side": "LONG",
                "quantity": 1,
                "strike": "195",
                "expiration": "2026-06-19",
                "option_type": "CALL",
            },
            {
                "occ_symbol": "AAPL  260619C00200000",
                "side": "SHORT",
                "quantity": 1,
                "strike": "200",
                "expiration": "2026-06-19",
                "option_type": "CALL",
            },
        ],
        "thesis": "Elevated implied volatility with constructive call-spread setup.",
        "confidence": "0.74",
        "expiration_date": "2026-06-19",
        "suggested_quantity": 1,
        "suggested_max_loss": "500",
        "features_snapshot": {"underlying": "AAPL", "iv_rank": "82"},
    }


@pytest.fixture
def features() -> Features:
    return Features(
        underlying="AAPL",
        iv_rank=Decimal("82"),
        iv_percentile=Decimal("77"),
        term_slope=Decimal("0.08"),
        skew=Decimal("-0.03"),
        rv_iv_spread=Decimal("0.12"),
        regime=VolRegime.EXTREME,
        momentum_5d=Decimal("0.02"),
        momentum_20d=Decimal("0.04"),
        as_of=datetime(2026, 4, 18, 14, 30, tzinfo=UTC),
    )


@pytest.fixture
def context() -> AiRunContext:
    return AiRunContext(
        as_of=datetime(2026, 4, 18, 14, 30, tzinfo=UTC),
        account_snapshot={"net_liquidation_value": "10000"},
        positions=[],
        features_by_underlying={},
        reason="IV_SPIKE",
    )


def _selector() -> OpenRouterStrategySelector:
    return OpenRouterStrategySelector(
        api_key="openrouter-key",
        model="anthropic/claude-sonnet-4.6",
        base_url="https://openrouter.ai/api/v1",
        http_referer="https://example.com",
        app_title="Darth Schwader",
    )


def _completion_response(content: str) -> dict[str, object]:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1_713_447_000,
        "model": "anthropic/claude-sonnet-4.6",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    }


async def test_select_returns_parsed_signals(
    respx_mock: respx.MockRouter,
    valid_signal_payload: dict[str, object],
    features: Features,
    context: AiRunContext,
) -> None:
    content = json.dumps({"signals": [valid_signal_payload]})
    respx_mock.post(OPENROUTER_CHAT_URL).mock(
        return_value=httpx.Response(200, json=_completion_response(content))
    )

    result = await _selector().select(features, context)

    assert len(result) == 1
    assert isinstance(result[0], StrategySignal)
    assert result[0].signal_id == "sig-aapl-vertical-001"
    assert result[0].underlying == "AAPL"
    assert result[0].confidence == Decimal("0.74")


async def test_select_raises_on_missing_prompt(
    monkeypatch: pytest.MonkeyPatch,
    features: Features,
    context: AiRunContext,
) -> None:
    monkeypatch.setattr(
        "darth_schwader.ai.llm.openrouter_provider.PROMPT_PATH",
        Path("/tmp/does-not-exist/strategy_selection.md"),
    )

    with pytest.raises(FileNotFoundError):
        await _selector().select(features, context)


async def test_select_unwraps_signals_envelope(
    respx_mock: respx.MockRouter,
    valid_signal_payload: dict[str, object],
    features: Features,
    context: AiRunContext,
) -> None:
    content = json.dumps({"signals": [valid_signal_payload]})
    respx_mock.post(OPENROUTER_CHAT_URL).mock(
        return_value=httpx.Response(200, json=_completion_response(content))
    )

    result = await _selector().select(features, context)

    assert [signal.signal_id for signal in result] == ["sig-aapl-vertical-001"]


async def test_select_accepts_top_level_list(
    respx_mock: respx.MockRouter,
    valid_signal_payload: dict[str, object],
    features: Features,
    context: AiRunContext,
) -> None:
    content = json.dumps([valid_signal_payload])
    respx_mock.post(OPENROUTER_CHAT_URL).mock(
        return_value=httpx.Response(200, json=_completion_response(content))
    )

    result = await _selector().select(features, context)

    assert [signal.signal_id for signal in result] == ["sig-aapl-vertical-001"]


async def test_select_strips_code_fences(
    respx_mock: respx.MockRouter,
    valid_signal_payload: dict[str, object],
    features: Features,
    context: AiRunContext,
) -> None:
    inner = json.dumps({"signals": [valid_signal_payload]})
    content = f"```json\n{inner}\n```"
    respx_mock.post(OPENROUTER_CHAT_URL).mock(
        return_value=httpx.Response(200, json=_completion_response(content))
    )

    result = await _selector().select(features, context)

    assert [signal.signal_id for signal in result] == ["sig-aapl-vertical-001"]


async def test_select_tolerates_leading_prose(
    respx_mock: respx.MockRouter,
    valid_signal_payload: dict[str, object],
    features: Features,
    context: AiRunContext,
) -> None:
    inner = json.dumps({"signals": [valid_signal_payload]})
    content = f"Here is the result:\n{inner}"
    respx_mock.post(OPENROUTER_CHAT_URL).mock(
        return_value=httpx.Response(200, json=_completion_response(content))
    )

    result = await _selector().select(features, context)

    assert [signal.signal_id for signal in result] == ["sig-aapl-vertical-001"]


async def test_select_includes_setups_in_user_payload(
    respx_mock: respx.MockRouter,
    valid_signal_payload: dict[str, object],
    features: Features,
    context: AiRunContext,
) -> None:
    content = json.dumps({"signals": [valid_signal_payload]})
    route = respx_mock.post(OPENROUTER_CHAT_URL).mock(
        return_value=httpx.Response(200, json=_completion_response(content))
    )
    setups = [
        {
            "symbol": "AAPL",
            "best_setup": "BULL_PULLBACK",
            "best_score": "72",
            "scores": {"BULL_PULLBACK": "72", "BEAR_BREAKDOWN": "10", "IV_CONTRACTION": "5"},
            "indicators": {"rsi14": "34", "adx14": "25"},
        }
    ]

    await _selector().select(features, context, setups=setups)

    sent_body = json.loads(route.calls.last.request.content.decode())
    user_message = sent_body["messages"][1]["content"]
    user_payload = json.loads(user_message)
    assert user_payload["setups"][0]["symbol"] == "AAPL"
    assert user_payload["setups"][0]["best_setup"] == "BULL_PULLBACK"


async def test_select_omits_setups_key_when_none_provided(
    respx_mock: respx.MockRouter,
    valid_signal_payload: dict[str, object],
    features: Features,
    context: AiRunContext,
) -> None:
    content = json.dumps({"signals": [valid_signal_payload]})
    route = respx_mock.post(OPENROUTER_CHAT_URL).mock(
        return_value=httpx.Response(200, json=_completion_response(content))
    )

    await _selector().select(features, context)

    sent_body = json.loads(route.calls.last.request.content.decode())
    user_payload = json.loads(sent_body["messages"][1]["content"])
    assert "setups" not in user_payload
