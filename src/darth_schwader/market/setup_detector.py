from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType

from darth_schwader.market.indicator_engine import IndicatorSet

_ZERO = Decimal("0")
_ONE = Decimal("1")
_HUNDRED = Decimal("100")

_DEFAULT_MIN_SCORE = Decimal("60")

BULL_PULLBACK = "BULL_PULLBACK"
BEAR_BREAKDOWN = "BEAR_BREAKDOWN"
IV_CONTRACTION = "IV_CONTRACTION"


@dataclass(frozen=True, slots=True)
class SetupScore:
    symbol: str
    scores: Mapping[str, Decimal]
    best_setup: str | None
    best_score: Decimal


def _ramp(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    """Linearly map value in [low, high] onto [0, 1]. Clamp to [0, 1]."""
    if high <= low:
        return _ZERO
    if value <= low:
        return _ZERO
    if value >= high:
        return _ONE
    return (value - low) / (high - low)


def _mean(parts: list[Decimal]) -> Decimal:
    if not parts:
        return _ZERO
    return sum(parts, _ZERO) / Decimal(len(parts))


def _score_bull_pullback(ind: IndicatorSet) -> Decimal:
    # EMA stacked bullish — strength scaled by separation relative to price.
    if ind.close == _ZERO:
        trend_score = _ZERO
    else:
        separation = (ind.ema8 - ind.ema21) / ind.close
        trend_score = _ramp(separation, _ZERO, Decimal("0.02"))
    # RSI pullback: fully scored below 40, decaying to 0 by 55.
    rsi_score = _ramp(Decimal("55") - ind.rsi14, _ZERO, Decimal("15"))
    # ADX trend strength: 20 → 30 ramps into full confidence.
    adx_score = _ramp(ind.adx14, Decimal("20"), Decimal("30"))
    # VWAP proximity: within 0.5% earns full credit, fades to 2%.
    vwap_score = _ramp(
        Decimal("0.02") - abs(ind.vwap_distance), _ZERO, Decimal("0.015")
    )
    return _mean([trend_score, rsi_score, adx_score, vwap_score]) * _HUNDRED


def _score_bear_breakdown(ind: IndicatorSet) -> Decimal:
    if ind.close == _ZERO:
        trend_score = _ZERO
    else:
        separation = (ind.ema21 - ind.ema8) / ind.close
        trend_score = _ramp(separation, _ZERO, Decimal("0.02"))
    rsi_score = _ramp(ind.rsi14 - Decimal("45"), _ZERO, Decimal("15"))
    vol_score = _ramp(ind.bb_width_pct, Decimal("0.5"), Decimal("0.9"))
    return _mean([trend_score, rsi_score, vol_score]) * _HUNDRED


def _score_iv_contraction(ind: IndicatorSet) -> Decimal:
    # Rewards the lowest 30th percentile of recent BB width.
    return _ramp(Decimal("0.3") - ind.bb_width_pct, _ZERO, Decimal("0.3")) * _HUNDRED


class SetupDetector:
    def __init__(self, *, min_score: Decimal | int | float = _DEFAULT_MIN_SCORE) -> None:
        self._min_score = Decimal(str(min_score))

    def score(self, ind: IndicatorSet) -> SetupScore:
        scores: dict[str, Decimal] = {
            BULL_PULLBACK: _score_bull_pullback(ind),
            BEAR_BREAKDOWN: _score_bear_breakdown(ind),
            IV_CONTRACTION: _score_iv_contraction(ind),
        }
        best_name, best_value = max(scores.items(), key=lambda kv: kv[1])
        gated = best_name if best_value >= self._min_score else None
        return SetupScore(
            symbol=ind.symbol,
            scores=MappingProxyType(scores),
            best_setup=gated,
            best_score=best_value,
        )


__all__ = [
    "BEAR_BREAKDOWN",
    "BULL_PULLBACK",
    "IV_CONTRACTION",
    "SetupDetector",
    "SetupScore",
]
