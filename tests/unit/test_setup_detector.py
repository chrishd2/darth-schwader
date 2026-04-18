from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from darth_schwader.market.indicator_engine import IndicatorSet
from darth_schwader.market.setup_detector import (
    BEAR_BREAKDOWN,
    BULL_PULLBACK,
    IV_CONTRACTION,
    SetupDetector,
)

_NOW = datetime(2026, 1, 2, 14, 30, tzinfo=UTC)


def _make_indicators(
    *,
    symbol: str = "AAPL",
    close: str = "100",
    rsi14: str = "50",
    ema8: str = "100",
    ema21: str = "100",
    atr14: str = "1",
    adx14: str = "15",
    bb_width: str = "0.02",
    bb_width_pct: str = "0.5",
    vwap: str = "100",
    vwap_distance: str = "0",
) -> IndicatorSet:
    return IndicatorSet(
        symbol=symbol,
        as_of=_NOW,
        close=Decimal(close),
        rsi14=Decimal(rsi14),
        ema8=Decimal(ema8),
        ema21=Decimal(ema21),
        atr14=Decimal(atr14),
        adx14=Decimal(adx14),
        bb_width=Decimal(bb_width),
        bb_width_pct=Decimal(bb_width_pct),
        vwap=Decimal(vwap),
        vwap_distance=Decimal(vwap_distance),
    )


def test_neutral_indicators_produce_no_best_setup() -> None:
    detector = SetupDetector()
    score = detector.score(_make_indicators())
    assert score.best_setup is None
    assert score.best_score < Decimal(60)


def test_bull_pullback_setup_dominates_when_conditions_met() -> None:
    detector = SetupDetector()
    indicators = _make_indicators(
        close="100",
        rsi14="32",
        ema8="102",
        ema21="100",
        adx14="32",
        vwap="99.8",
        vwap_distance="0.002",
    )
    score = detector.score(indicators)
    assert score.best_setup == BULL_PULLBACK
    assert score.scores[BULL_PULLBACK] >= Decimal(60)
    assert score.scores[BULL_PULLBACK] > score.scores[BEAR_BREAKDOWN]
    assert score.scores[BULL_PULLBACK] > score.scores[IV_CONTRACTION]


def test_bear_breakdown_setup_triggers_on_overbought_downtrend() -> None:
    detector = SetupDetector()
    indicators = _make_indicators(
        close="100",
        rsi14="65",
        ema8="98",
        ema21="100",
        bb_width_pct="0.9",
    )
    score = detector.score(indicators)
    assert score.best_setup == BEAR_BREAKDOWN
    assert score.scores[BEAR_BREAKDOWN] >= Decimal(60)


def test_iv_contraction_triggers_on_low_volatility() -> None:
    detector = SetupDetector()
    indicators = _make_indicators(bb_width_pct="0.03")
    score = detector.score(indicators)
    assert score.best_setup == IV_CONTRACTION
    assert score.scores[IV_CONTRACTION] >= Decimal(60)


def test_min_score_gate_filters_weak_winners() -> None:
    detector = SetupDetector(min_score=95)
    indicators = _make_indicators(rsi14="35", ema8="101", ema21="100", adx14="22")
    score = detector.score(indicators)
    assert score.best_setup is None
    assert score.best_score > Decimal(0)


def test_scores_mapping_is_immutable() -> None:
    detector = SetupDetector()
    score = detector.score(_make_indicators())
    assert set(score.scores.keys()) == {BULL_PULLBACK, BEAR_BREAKDOWN, IV_CONTRACTION}


def test_symbol_is_propagated() -> None:
    detector = SetupDetector()
    score = detector.score(_make_indicators(symbol="NVDA"))
    assert score.symbol == "NVDA"
