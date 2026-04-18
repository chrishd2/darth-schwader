from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")


def _validate_series(series: Sequence[Decimal]) -> tuple[Decimal, ...]:
    if not series:
        raise ValueError("series must not be empty")
    normalized = tuple(Decimal(value) for value in series)
    if any(value < _ZERO for value in normalized):
        raise ValueError("series values must be non-negative")
    return normalized


def iv_rank(current_iv: Decimal, one_year_iv_series: Sequence[Decimal]) -> Decimal:
    series = _validate_series(one_year_iv_series)
    current = Decimal(current_iv)
    min_iv = min(series)
    max_iv = max(series)
    spread = max_iv - min_iv
    if spread <= _ZERO:
        raise ValueError("iv_rank requires a non-degenerate series")
    score = ((current - min_iv) / spread) * _HUNDRED
    return max(_ZERO, min(_HUNDRED, score))


def iv_percentile(current_iv: Decimal, series: Sequence[Decimal]) -> Decimal:
    normalized = _validate_series(series)
    current = Decimal(current_iv)
    below_or_equal = sum(1 for value in normalized if value <= current)
    return (Decimal(below_or_equal) / Decimal(len(normalized))) * _HUNDRED


def term_structure_slope(front_iv: Decimal, back_iv: Decimal) -> Decimal:
    front = Decimal(front_iv)
    back = Decimal(back_iv)
    if front <= _ZERO:
        raise ValueError("front_iv must be greater than zero")
    return (back - front) / front


def skew_25_delta(call_iv_25d: Decimal, put_iv_25d: Decimal) -> Decimal:
    call_iv = Decimal(call_iv_25d)
    put_iv = Decimal(put_iv_25d)
    if call_iv <= _ZERO or put_iv <= _ZERO:
        raise ValueError("25-delta IV inputs must be greater than zero")
    return put_iv - call_iv


def realized_vs_implied(rv_20d: Decimal, iv_current: Decimal) -> Decimal:
    realized = Decimal(rv_20d)
    implied = Decimal(iv_current)
    if realized <= _ZERO or implied <= _ZERO:
        raise ValueError("realized and implied volatility must be greater than zero")
    return implied - realized


__all__ = [
    "iv_percentile",
    "iv_rank",
    "realized_vs_implied",
    "skew_25_delta",
    "term_structure_slope",
]
