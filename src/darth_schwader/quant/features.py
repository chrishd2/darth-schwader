from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from darth_schwader.quant.iv_metrics import (
    iv_percentile,
    iv_rank,
    realized_vs_implied,
    skew_25_delta,
    term_structure_slope,
)
from darth_schwader.quant.regime import VolRegime, classify_regime


@dataclass(frozen=True, slots=True)
class Features:
    underlying: str
    iv_rank: Decimal
    iv_percentile: Decimal
    term_slope: Decimal
    skew: Decimal
    rv_iv_spread: Decimal
    regime: VolRegime
    momentum_5d: Decimal
    momentum_20d: Decimal
    as_of: datetime


def _dec(row: Mapping[str, object], key: str) -> Decimal:
    value = row.get(key)
    if value is None:
        raise ValueError(f"missing required key: {key}")
    return Decimal(str(value))


def _momentum(closes: Sequence[Decimal], window: int) -> Decimal:
    if len(closes) <= window:
        raise ValueError(f"need more than {window} closes")
    start = closes[-window - 1]
    if start == Decimal("0"):
        raise ValueError("starting close must be non-zero")
    return (closes[-1] - start) / start


def _realized_vol(closes: Sequence[Decimal], window: int) -> Decimal:
    if len(closes) <= window:
        raise ValueError(f"need more than {window} closes for realized volatility")
    returns: list[Decimal] = []
    subset = closes[-window - 1 :]
    for left, right in zip(subset, subset[1:], strict=False):
        if left == Decimal("0"):
            raise ValueError("close must be non-zero")
        returns.append((right - left) / left)
    mean = sum(returns, Decimal("0")) / Decimal(len(returns))
    variance = sum((value - mean) ** 2 for value in returns) / Decimal(len(returns))
    return variance.sqrt() * Decimal("15.874507866387544")


def compute(
    underlying: str,
    chain_snapshot_rows: Sequence[Mapping[str, object]],
    underlying_ohlcv_rows: Sequence[Mapping[str, object]],
) -> Features:
    if not chain_snapshot_rows:
        raise ValueError("chain_snapshot_rows must not be empty")
    if len(underlying_ohlcv_rows) < 21:
        raise ValueError("underlying_ohlcv_rows must contain at least 21 rows")

    sorted_chain = sorted(chain_snapshot_rows, key=lambda row: str(row.get("quote_time", "")))
    latest = sorted_chain[-1]
    latest_iv = _dec(latest, "implied_volatility")
    iv_series = tuple(_dec(row, "implied_volatility") for row in sorted_chain)

    front_rows = [row for row in sorted_chain if str(row.get("expiration_date")) == str(latest["expiration_date"])]
    back_rows = [row for row in sorted_chain if str(row.get("expiration_date")) != str(latest["expiration_date"])]
    back_reference = back_rows[0] if back_rows else latest

    close_series = tuple(Decimal(str(row["close"])) for row in underlying_ohlcv_rows)
    rv_20d = _realized_vol(close_series, 20)
    as_of_raw = latest.get("quote_time")
    as_of = (
        datetime.fromisoformat(str(as_of_raw).replace("Z", "+00:00")).astimezone(UTC)
        if as_of_raw
        else datetime.now(tz=UTC)
    )

    rank = iv_rank(latest_iv, iv_series)
    percentile = iv_percentile(latest_iv, iv_series)
    slope = term_structure_slope(latest_iv, _dec(back_reference, "implied_volatility"))
    skew = skew_25_delta(
        _dec(front_rows[0] if front_rows else latest, "call_iv_25d"),
        _dec(front_rows[0] if front_rows else latest, "put_iv_25d"),
    )

    return Features(
        underlying=underlying,
        iv_rank=rank,
        iv_percentile=percentile,
        term_slope=slope,
        skew=skew,
        rv_iv_spread=realized_vs_implied(rv_20d, latest_iv),
        regime=classify_regime(rank),
        momentum_5d=_momentum(close_series, 5),
        momentum_20d=_momentum(close_series, 20),
        as_of=as_of,
    )


__all__ = ["Features", "compute"]
