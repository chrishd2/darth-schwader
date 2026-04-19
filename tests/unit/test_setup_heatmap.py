from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from darth_schwader.domain.asset_types import AssetType
from darth_schwader.market.indicator_engine import MIN_BARS, Bar
from darth_schwader.services.setup_heatmap import (
    HeatmapRow,
    SetupHeatmapService,
    heatmap_row_to_dict,
)


@dataclass
class _FakeEntry:
    symbol: str
    asset_type: AssetType


class _FakeWatchlistRepo:
    def __init__(self, entries: list[_FakeEntry]) -> None:
        self._entries = entries

    async def list_all(self, *, active_only: bool = False) -> list[_FakeEntry]:
        assert active_only is True
        return list(self._entries)


class _StubBarProvider:
    def __init__(self, bars: list[Bar] | Exception) -> None:
        self._bars = bars

    async def fetch_daily_bars(self, symbol: str, lookback_days: int) -> Sequence[Bar]:
        if isinstance(self._bars, Exception):
            raise self._bars
        return self._bars


def _flat_bars(count: int, value: float = 100.0) -> list[Bar]:
    start = datetime(2026, 1, 2, tzinfo=UTC)
    price = Decimal(str(value))
    return [
        Bar(
            timestamp=start + timedelta(days=i),
            open=price,
            high=price + Decimal("0.5"),
            low=price - Decimal("0.5"),
            close=price,
            volume=Decimal("1000"),
        )
        for i in range(count)
    ]


@pytest.mark.asyncio
async def test_snapshot_returns_rows_for_each_active_entry() -> None:
    service = SetupHeatmapService(
        watchlist_repo=_FakeWatchlistRepo(
            [
                _FakeEntry("AAPL", AssetType.EQUITY),
                _FakeEntry("SPY", AssetType.ETF),
            ]
        ),
        bar_provider=_StubBarProvider(_flat_bars(MIN_BARS)),
    )

    rows = await service.snapshot()

    assert [row.symbol for row in rows] == ["AAPL", "SPY"]
    assert all(row.error is None for row in rows)
    assert all(row.setup is not None for row in rows)


@pytest.mark.asyncio
async def test_snapshot_degrades_gracefully_on_provider_error() -> None:
    service = SetupHeatmapService(
        watchlist_repo=_FakeWatchlistRepo([_FakeEntry("BAD", AssetType.EQUITY)]),
        bar_provider=_StubBarProvider(RuntimeError("boom")),
    )

    rows = await service.snapshot()

    assert len(rows) == 1
    assert rows[0].indicators is None
    assert rows[0].setup is None
    assert rows[0].error is not None
    assert "boom" in rows[0].error


@pytest.mark.asyncio
async def test_snapshot_flags_insufficient_bars() -> None:
    service = SetupHeatmapService(
        watchlist_repo=_FakeWatchlistRepo([_FakeEntry("AAPL", AssetType.EQUITY)]),
        bar_provider=_StubBarProvider(_flat_bars(MIN_BARS - 5)),
    )

    rows = await service.snapshot()

    assert rows[0].error is not None
    assert "insufficient bars" in rows[0].error
    assert rows[0].indicators is None


def test_heatmap_row_to_dict_handles_missing_data() -> None:
    row = HeatmapRow(
        symbol="XYZ",
        asset_type=AssetType.EQUITY,
        indicators=None,
        setup=None,
        error="nope",
    )

    payload = heatmap_row_to_dict(row)

    assert payload == {
        "symbol": "XYZ",
        "asset_type": "EQUITY",
        "indicators": None,
        "best_setup": None,
        "best_score": "0",
        "scores": {},
        "error": "nope",
    }


@pytest.mark.asyncio
async def test_heatmap_row_to_dict_renders_indicators() -> None:
    service = SetupHeatmapService(
        watchlist_repo=_FakeWatchlistRepo([_FakeEntry("AAPL", AssetType.EQUITY)]),
        bar_provider=_StubBarProvider(_flat_bars(MIN_BARS)),
    )

    rows = await service.snapshot()
    payload = heatmap_row_to_dict(rows[0])

    assert payload["symbol"] == "AAPL"
    assert payload["indicators"] is not None
    assert "rsi14" in payload["indicators"]
    assert payload["scores"].keys() == {"BULL_PULLBACK", "BEAR_BREAKDOWN", "IV_CONTRACTION"}
