from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from darth_schwader.market.indicator_engine import (
    MIN_BARS,
    Bar,
    IndicatorEngine,
)


def _make_bars(
    closes: list[float],
    *,
    volume: float = 1_000.0,
    spread: float = 0.5,
) -> list[Bar]:
    start = datetime(2026, 1, 2, 14, 30, tzinfo=UTC)
    bars: list[Bar] = []
    for i, close in enumerate(closes):
        price = Decimal(str(close))
        half = Decimal(str(spread))
        bars.append(
            Bar(
                timestamp=start + timedelta(minutes=i),
                open=price,
                high=price + half,
                low=price - half,
                close=price,
                volume=Decimal(str(volume)),
            )
        )
    return bars


def _flat(count: int, value: float = 100.0) -> list[Bar]:
    return _make_bars([value] * count)


def _monotonic(count: int, start: float = 100.0, step: float = 0.5) -> list[Bar]:
    return _make_bars([start + step * i for i in range(count)])


def test_requires_min_bars() -> None:
    engine = IndicatorEngine()
    bars = _flat(MIN_BARS - 1)
    with pytest.raises(ValueError, match="at least"):
        engine.compute("AAPL", bars)


def test_flat_series_produces_neutral_rsi_and_zero_volatility() -> None:
    engine = IndicatorEngine()
    result = engine.compute("AAPL", _flat(MIN_BARS))
    # Flat closes → no gains and no losses → neutral RSI.
    assert result.rsi14 == Decimal(50)
    # EMAs collapse to the constant level.
    assert result.ema8 == Decimal("100")
    assert result.ema21 == Decimal("100")
    # Band width must be zero when standard deviation is zero.
    assert result.bb_width == Decimal("0")
    # VWAP equals typical price when prices are flat.
    assert result.vwap == Decimal("100")
    assert result.vwap_distance == Decimal("0")


def test_steady_uptrend_yields_high_rsi_and_bullish_ema_stack() -> None:
    engine = IndicatorEngine()
    result = engine.compute("AAPL", _monotonic(MIN_BARS))
    assert result.rsi14 == Decimal(100)
    assert result.ema8 > result.ema21
    # Uptrend means the last close is above EMAs (faster reacts more).
    assert result.close > result.ema8 > result.ema21
    # ADX climbs well above 20 in a clean trend.
    assert result.adx14 > Decimal(30)


def test_downtrend_flips_ema_stack_and_floors_rsi() -> None:
    engine = IndicatorEngine()
    bars = _make_bars([200.0 - 0.5 * i for i in range(MIN_BARS)])
    result = engine.compute("SPY", bars)
    assert result.rsi14 == Decimal(0)
    assert result.ema8 < result.ema21


def test_indicator_set_is_immutable_dataclass() -> None:
    engine = IndicatorEngine()
    result = engine.compute("AAPL", _flat(MIN_BARS))
    with pytest.raises(AttributeError):
        result.rsi14 = Decimal(0)  # type: ignore[misc]


def test_mapping_rows_are_accepted() -> None:
    engine = IndicatorEngine()
    start = datetime(2026, 1, 2, 14, 30, tzinfo=UTC)
    rows = [
        {
            "timestamp": (start + timedelta(minutes=i)).isoformat(),
            "open": "100",
            "high": "100.5",
            "low": "99.5",
            "close": "100",
            "volume": "1000",
        }
        for i in range(MIN_BARS)
    ]
    result = engine.compute("AAPL", rows)
    assert result.close == Decimal("100")


def test_missing_field_raises() -> None:
    engine = IndicatorEngine()
    bad_row = {
        "timestamp": datetime(2026, 1, 2, tzinfo=UTC),
        "open": "100",
        "high": "100",
        "low": "100",
        "close": "100",
    }
    rows = [bad_row] * MIN_BARS
    with pytest.raises(ValueError, match="missing required bar field: volume"):
        engine.compute("AAPL", rows)


def test_naive_mapping_timestamp_is_assumed_utc() -> None:
    engine = IndicatorEngine()
    naive = datetime(2026, 1, 2, 14, 30)  # noqa: DTZ001 — intentional naive input
    rows = [
        {
            "timestamp": naive + timedelta(minutes=i),
            "open": "100",
            "high": "100.5",
            "low": "99.5",
            "close": "100",
            "volume": "1000",
        }
        for i in range(MIN_BARS)
    ]
    result = engine.compute("AAPL", rows)
    assert result.as_of.tzinfo is UTC


def test_bollinger_width_expands_with_volatility() -> None:
    engine = IndicatorEngine()
    calm = _flat(MIN_BARS, value=100.0)
    volatile = _make_bars(
        [100.0 + (5.0 if i % 2 else -5.0) for i in range(MIN_BARS)]
    )
    calm_result = engine.compute("AAPL", calm)
    wild_result = engine.compute("AAPL", volatile)
    assert wild_result.bb_width > calm_result.bb_width


def test_vwap_respects_volume_weighting() -> None:
    engine = IndicatorEngine()
    base_closes = [100.0] * (MIN_BARS - 1) + [120.0]
    bars = _make_bars(base_closes, volume=1000.0)
    # Zero the heavy tail so VWAP sticks near the early price band.
    last = bars[-1]
    bars[-1] = Bar(
        timestamp=last.timestamp,
        open=last.open,
        high=last.high,
        low=last.low,
        close=last.close,
        volume=Decimal("0"),
    )
    result = engine.compute("AAPL", bars)
    assert result.vwap == Decimal("100")


def test_bb_width_is_non_negative() -> None:
    engine = IndicatorEngine()
    result = engine.compute("AAPL", _monotonic(MIN_BARS))
    assert result.bb_width >= Decimal("0")
    assert Decimal("0") <= result.bb_width_pct <= Decimal("1")
