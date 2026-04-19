from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol

from darth_schwader.data_sources.polygon.client import PolygonClient
from darth_schwader.market.indicator_engine import Bar


class BarProvider(Protocol):
    async def fetch_daily_bars(self, symbol: str, lookback_days: int) -> Sequence[Bar]:
        ...


class PolygonBarProvider:
    """Adapter that turns Polygon daily aggregates into Bar objects."""

    def __init__(self, client: PolygonClient) -> None:
        self._client = client

    async def fetch_daily_bars(self, symbol: str, lookback_days: int) -> list[Bar]:
        if lookback_days <= 0:
            raise ValueError("lookback_days must be positive")
        end_date = datetime.now(tz=UTC).date()
        start_date = end_date - timedelta(days=lookback_days)
        rows = await self._client.get_daily_ohlc(symbol, start_date, end_date)
        bars: list[Bar] = []
        for row in rows:
            timestamp = _row_timestamp(row)
            bars.append(
                Bar(
                    timestamp=timestamp,
                    open=_decimal(row.get("o")),
                    high=_decimal(row.get("h")),
                    low=_decimal(row.get("l")),
                    close=_decimal(row.get("c")),
                    volume=_decimal(row.get("v")),
                )
            )
        return bars


def _decimal(value: object) -> Decimal:
    if value is None:
        raise ValueError("bar field missing from Polygon response")
    return Decimal(str(value))


def _row_timestamp(row: dict[str, object]) -> datetime:
    raw = row.get("t")
    if not isinstance(raw, (int, float)):
        raise ValueError("Polygon aggregate missing millisecond timestamp 't'")
    return datetime.fromtimestamp(raw / 1000, tz=UTC)


__all__ = ["BarProvider", "PolygonBarProvider"]
