from __future__ import annotations

import pytest

from darth_schwader.db.repositories.watchlist import WatchlistRepository
from darth_schwader.domain.asset_types import AssetType


@pytest.mark.asyncio
async def test_create_normalizes_symbol_to_uppercase(session_factory) -> None:
    repo = WatchlistRepository(session_factory)
    entry = await repo.create(
        symbol="aapl",
        asset_type=AssetType.EQUITY,
        strategies=["VERTICAL_SPREAD"],
    )
    assert entry.symbol == "AAPL"


@pytest.mark.asyncio
async def test_find_uses_uppercase_symbol(session_factory) -> None:
    repo = WatchlistRepository(session_factory)
    await repo.create(
        symbol="AAPL",
        asset_type=AssetType.EQUITY,
        strategies=[],
    )
    found = await repo.find("aapl", AssetType.EQUITY)
    assert found is not None
    assert found.symbol == "AAPL"


@pytest.mark.asyncio
async def test_list_orders_by_symbol_and_asset_type(session_factory) -> None:
    repo = WatchlistRepository(session_factory)
    await repo.create(symbol="MSFT", asset_type=AssetType.EQUITY, strategies=[])
    await repo.create(symbol="AAPL", asset_type=AssetType.EQUITY, strategies=[])
    await repo.create(symbol="AAPL", asset_type=AssetType.ETF, strategies=[])

    rows = await repo.list_all()
    symbols_and_types = [(row.symbol, row.asset_type) for row in rows]
    assert symbols_and_types == [
        ("AAPL", AssetType.EQUITY),
        ("AAPL", AssetType.ETF),
        ("MSFT", AssetType.EQUITY),
    ]


@pytest.mark.asyncio
async def test_list_active_only_filters_inactive(session_factory) -> None:
    repo = WatchlistRepository(session_factory)
    await repo.create(symbol="A", asset_type=AssetType.EQUITY, strategies=[])
    await repo.create(
        symbol="B",
        asset_type=AssetType.EQUITY,
        strategies=[],
        active=False,
    )
    rows = await repo.list_all(active_only=True)
    assert [row.symbol for row in rows] == ["A"]


@pytest.mark.asyncio
async def test_update_only_touches_provided_fields(session_factory) -> None:
    repo = WatchlistRepository(session_factory)
    entry = await repo.create(
        symbol="NVDA",
        asset_type=AssetType.EQUITY,
        strategies=["VERTICAL_SPREAD"],
        notes="initial",
    )
    updated = await repo.update(entry.id, active=False)
    assert updated is not None
    assert updated.active is False
    assert updated.strategies == ["VERTICAL_SPREAD"]
    assert updated.notes == "initial"


@pytest.mark.asyncio
async def test_update_missing_entry_returns_none(session_factory) -> None:
    repo = WatchlistRepository(session_factory)
    result = await repo.update(999, active=False)
    assert result is None


@pytest.mark.asyncio
async def test_delete_returns_false_when_missing(session_factory) -> None:
    repo = WatchlistRepository(session_factory)
    assert await repo.delete(999) is False


@pytest.mark.asyncio
async def test_delete_returns_true_and_removes_entry(session_factory) -> None:
    repo = WatchlistRepository(session_factory)
    entry = await repo.create(symbol="SPY", asset_type=AssetType.ETF, strategies=[])
    assert await repo.delete(entry.id) is True
    assert await repo.get(entry.id) is None
