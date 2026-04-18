from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from itertools import pairwise

_ZERO = Decimal("0")
_ONE = Decimal("1")
_TWO = Decimal("2")
_HUNDRED = Decimal("100")

_DEFAULT_RSI_PERIOD = 14
_DEFAULT_ATR_PERIOD = 14
_DEFAULT_ADX_PERIOD = 14
_DEFAULT_EMA_FAST = 8
_DEFAULT_EMA_SLOW = 21
_DEFAULT_BB_PERIOD = 20
_DEFAULT_BB_LOOKBACK = 20
_DEFAULT_BB_K = _TWO

# ADX needs a period for DM smoothing plus another period for averaging DX, so
# callers must supply at least 2*period+1 bars. A 50-bar floor covers every
# default indicator plus the BB percentile lookback window with some slack.
MIN_BARS = 50


@dataclass(frozen=True, slots=True)
class Bar:
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


@dataclass(frozen=True, slots=True)
class IndicatorSet:
    symbol: str
    as_of: datetime
    close: Decimal
    rsi14: Decimal
    ema8: Decimal
    ema21: Decimal
    atr14: Decimal
    adx14: Decimal
    bb_width: Decimal
    bb_width_pct: Decimal
    vwap: Decimal
    vwap_distance: Decimal


def _parse_timestamp(value: object) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    raise ValueError(f"unsupported timestamp value: {value!r}")


def _to_bar(row: Bar | Mapping[str, object]) -> Bar:
    if isinstance(row, Bar):
        return row
    required = ("timestamp", "open", "high", "low", "close", "volume")
    for key in required:
        if key not in row:
            raise ValueError(f"missing required bar field: {key}")
    return Bar(
        timestamp=_parse_timestamp(row["timestamp"]),
        open=Decimal(str(row["open"])),
        high=Decimal(str(row["high"])),
        low=Decimal(str(row["low"])),
        close=Decimal(str(row["close"])),
        volume=Decimal(str(row["volume"])),
    )


def _normalize(bars: Sequence[Bar | Mapping[str, object]]) -> tuple[Bar, ...]:
    normalized = tuple(_to_bar(row) for row in bars)
    if len(normalized) < MIN_BARS:
        raise ValueError(f"indicator engine requires at least {MIN_BARS} bars")
    return normalized


def _ema_series(values: Sequence[Decimal], period: int) -> list[Decimal]:
    if len(values) < period:
        raise ValueError(f"ema requires at least {period} values")
    alpha = _TWO / Decimal(period + 1)
    seed = sum(values[:period], _ZERO) / Decimal(period)
    out: list[Decimal] = [seed]
    for value in values[period:]:
        out.append(value * alpha + out[-1] * (_ONE - alpha))
    return out


def _ema(values: Sequence[Decimal], period: int) -> Decimal:
    return _ema_series(values, period)[-1]


def _rsi(closes: Sequence[Decimal], period: int = _DEFAULT_RSI_PERIOD) -> Decimal:
    if len(closes) < period + 1:
        raise ValueError(f"rsi requires at least {period + 1} closes")
    gains: list[Decimal] = []
    losses: list[Decimal] = []
    for prev, curr in pairwise(closes):
        delta = curr - prev
        gains.append(delta if delta > _ZERO else _ZERO)
        losses.append(-delta if delta < _ZERO else _ZERO)
    avg_gain = sum(gains[:period], _ZERO) / Decimal(period)
    avg_loss = sum(losses[:period], _ZERO) / Decimal(period)
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * Decimal(period - 1) + gains[i]) / Decimal(period)
        avg_loss = (avg_loss * Decimal(period - 1) + losses[i]) / Decimal(period)
    if avg_loss == _ZERO:
        return _HUNDRED if avg_gain > _ZERO else Decimal(50)
    rs = avg_gain / avg_loss
    return _HUNDRED - _HUNDRED / (_ONE + rs)


def _true_ranges(bars: Sequence[Bar]) -> list[Decimal]:
    trs: list[Decimal] = []
    for prev, curr in pairwise(bars):
        trs.append(
            max(
                curr.high - curr.low,
                abs(curr.high - prev.close),
                abs(curr.low - prev.close),
            )
        )
    return trs


def _wilder_smooth(values: Sequence[Decimal], period: int) -> list[Decimal]:
    if len(values) < period:
        raise ValueError(f"wilder smooth requires at least {period} values")
    out: list[Decimal] = [sum(values[:period], _ZERO)]
    for value in values[period:]:
        out.append(out[-1] - out[-1] / Decimal(period) + value)
    return out


def _atr(bars: Sequence[Bar], period: int = _DEFAULT_ATR_PERIOD) -> Decimal:
    if len(bars) < period + 1:
        raise ValueError(f"atr requires at least {period + 1} bars")
    trs = _true_ranges(bars)
    atr = sum(trs[:period], _ZERO) / Decimal(period)
    for tr in trs[period:]:
        atr = (atr * Decimal(period - 1) + tr) / Decimal(period)
    return atr


def _adx(bars: Sequence[Bar], period: int = _DEFAULT_ADX_PERIOD) -> Decimal:
    if len(bars) < 2 * period + 1:
        raise ValueError(f"adx requires at least {2 * period + 1} bars")
    plus_dm: list[Decimal] = []
    minus_dm: list[Decimal] = []
    for prev, curr in pairwise(bars):
        up = curr.high - prev.high
        down = prev.low - curr.low
        plus_dm.append(up if up > down and up > _ZERO else _ZERO)
        minus_dm.append(down if down > up and down > _ZERO else _ZERO)
    trs = _true_ranges(bars)
    smoothed_plus = _wilder_smooth(plus_dm, period)
    smoothed_minus = _wilder_smooth(minus_dm, period)
    smoothed_tr = _wilder_smooth(trs, period)
    dx_values: list[Decimal] = []
    for sp, sm, st in zip(smoothed_plus, smoothed_minus, smoothed_tr, strict=False):
        if st == _ZERO:
            dx_values.append(_ZERO)
            continue
        plus_di = _HUNDRED * sp / st
        minus_di = _HUNDRED * sm / st
        denom = plus_di + minus_di
        dx_values.append(_HUNDRED * abs(plus_di - minus_di) / denom if denom else _ZERO)
    if len(dx_values) < period:
        raise ValueError("insufficient DX values for ADX smoothing")
    adx = sum(dx_values[:period], _ZERO) / Decimal(period)
    for dx in dx_values[period:]:
        adx = (adx * Decimal(period - 1) + dx) / Decimal(period)
    return adx


def _bb_width(window: Sequence[Decimal], k: Decimal = _DEFAULT_BB_K) -> Decimal:
    count = Decimal(len(window))
    mean = sum(window, _ZERO) / count
    if mean == _ZERO:
        return _ZERO
    variance = sum((v - mean) ** 2 for v in window) / count
    std = variance.sqrt() if variance > _ZERO else _ZERO
    return (_TWO * k * std) / mean


def _bb_width_percentile(
    closes: Sequence[Decimal],
    period: int = _DEFAULT_BB_PERIOD,
    lookback: int = _DEFAULT_BB_LOOKBACK,
) -> tuple[Decimal, Decimal]:
    if len(closes) < period + lookback - 1:
        raise ValueError(
            f"bb percentile requires at least {period + lookback - 1} closes"
        )
    widths: list[Decimal] = []
    for i in range(lookback):
        end = len(closes) - (lookback - 1 - i)
        window = closes[end - period : end]
        widths.append(_bb_width(window))
    current = widths[-1]
    rank = sum(_ONE for width in widths if width <= current)
    percentile = rank / Decimal(len(widths))
    return current, percentile


def _vwap(bars: Sequence[Bar]) -> Decimal:
    if not bars:
        raise ValueError("vwap requires at least one bar")
    numerator = _ZERO
    denominator = _ZERO
    for bar in bars:
        typical = (bar.high + bar.low + bar.close) / Decimal(3)
        numerator += typical * bar.volume
        denominator += bar.volume
    if denominator == _ZERO:
        return sum((bar.close for bar in bars), _ZERO) / Decimal(len(bars))
    return numerator / denominator


class IndicatorEngine:
    def compute(
        self, symbol: str, bars: Sequence[Bar | Mapping[str, object]]
    ) -> IndicatorSet:
        normalized = _normalize(bars)
        closes = tuple(bar.close for bar in normalized)
        close = closes[-1]
        ema8 = _ema(closes, _DEFAULT_EMA_FAST)
        ema21 = _ema(closes, _DEFAULT_EMA_SLOW)
        rsi14 = _rsi(closes)
        atr14 = _atr(normalized)
        adx14 = _adx(normalized)
        bb_width, bb_pct = _bb_width_percentile(closes)
        vwap = _vwap(normalized)
        vwap_distance = (close - vwap) / vwap if vwap != _ZERO else _ZERO
        return IndicatorSet(
            symbol=symbol,
            as_of=normalized[-1].timestamp,
            close=close,
            rsi14=rsi14,
            ema8=ema8,
            ema21=ema21,
            atr14=atr14,
            adx14=adx14,
            bb_width=bb_width,
            bb_width_pct=bb_pct,
            vwap=vwap,
            vwap_distance=vwap_distance,
        )


__all__ = ["MIN_BARS", "Bar", "IndicatorEngine", "IndicatorSet"]
