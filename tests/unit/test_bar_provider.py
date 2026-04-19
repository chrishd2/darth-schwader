from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from darth_schwader.market.bar_provider import PolygonBarProvider


class _StubPolygonClient:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.calls: list[tuple[str, object, object]] = []

    async def get_daily_ohlc(self, symbol: str, date_from: object, date_to: object) -> list[
        dict[str, Any]
    ]:
        self.calls.append((symbol, date_from, date_to))
        return list(self._rows)


@pytest.mark.asyncio
async def test_polygon_bar_provider_maps_fields_to_bar() -> None:
    ts_ms = int(datetime(2026, 1, 2, tzinfo=UTC).timestamp() * 1000)
    client = _StubPolygonClient(
        [
            {"t": ts_ms, "o": 100.0, "h": 101.0, "l": 99.0, "c": 100.5, "v": 1000},
        ]
    )
    provider = PolygonBarProvider(client)  # type: ignore[arg-type]

    bars = await provider.fetch_daily_bars("AAPL", lookback_days=30)

    assert len(bars) == 1
    bar = bars[0]
    assert bar.open == Decimal("100.0")
    assert bar.high == Decimal("101.0")
    assert bar.low == Decimal("99.0")
    assert bar.close == Decimal("100.5")
    assert bar.volume == Decimal("1000")
    assert bar.timestamp.tzinfo is UTC
    assert client.calls[0][0] == "AAPL"


@pytest.mark.asyncio
async def test_polygon_bar_provider_rejects_missing_fields() -> None:
    ts_ms = int(datetime(2026, 1, 2, tzinfo=UTC).timestamp() * 1000)
    client = _StubPolygonClient([{"t": ts_ms, "o": 100.0}])
    provider = PolygonBarProvider(client)  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        await provider.fetch_daily_bars("AAPL", lookback_days=30)


@pytest.mark.asyncio
async def test_polygon_bar_provider_rejects_non_positive_lookback() -> None:
    provider = PolygonBarProvider(_StubPolygonClient([]))  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        await provider.fetch_daily_bars("AAPL", lookback_days=0)
