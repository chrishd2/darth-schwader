from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from darth_schwader.db.models import WatchlistEntry
from darth_schwader.domain.asset_types import AssetType


@pytest.mark.asyncio
async def test_list_watchlist_empty(make_app) -> None:
    app = make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/v1/watchlist")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_create_watchlist_entry(make_app, session_factory) -> None:
    app = make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/v1/watchlist",
            json={
                "symbol": "msft",
                "asset_type": "EQUITY",
                "strategies": ["VERTICAL_SPREAD"],
                "notes": "tech",
            },
        )
    assert response.status_code == 201
    body = response.json()
    assert body["symbol"] == "MSFT"
    assert body["asset_type"] == "EQUITY"
    assert body["strategies"] == ["VERTICAL_SPREAD"]
    assert body["active"] is True
    assert body["notes"] == "tech"

    async with session_factory() as session:
        row = await session.scalar(
            select(WatchlistEntry).where(WatchlistEntry.symbol == "MSFT")
        )
    assert row is not None
    assert row.asset_type is AssetType.EQUITY


@pytest.mark.asyncio
async def test_create_watchlist_entry_rejects_duplicate(make_app) -> None:
    app = make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        first = await client.post(
            "/api/v1/watchlist",
            json={"symbol": "QQQ", "asset_type": "ETF"},
        )
        assert first.status_code == 201

        second = await client.post(
            "/api/v1/watchlist",
            json={"symbol": "QQQ", "asset_type": "ETF"},
        )
    assert second.status_code == 409
    assert "already exists" in second.json()["detail"]


@pytest.mark.asyncio
async def test_create_allows_same_symbol_across_asset_types(make_app) -> None:
    app = make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        equity = await client.post(
            "/api/v1/watchlist",
            json={"symbol": "SPY", "asset_type": "EQUITY"},
        )
        etf = await client.post(
            "/api/v1/watchlist",
            json={"symbol": "SPY", "asset_type": "ETF"},
        )
    assert equity.status_code == 201
    assert etf.status_code == 201


@pytest.mark.asyncio
async def test_update_watchlist_entry(make_app) -> None:
    app = make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        created = await client.post(
            "/api/v1/watchlist",
            json={
                "symbol": "NVDA",
                "asset_type": "EQUITY",
                "strategies": ["VERTICAL_SPREAD"],
            },
        )
        entry_id = created.json()["id"]

        updated = await client.patch(
            f"/api/v1/watchlist/{entry_id}",
            json={
                "strategies": ["IRON_CONDOR"],
                "active": False,
                "notes": "paused",
            },
        )
    assert updated.status_code == 200
    body = updated.json()
    assert body["strategies"] == ["IRON_CONDOR"]
    assert body["active"] is False
    assert body["notes"] == "paused"


@pytest.mark.asyncio
async def test_update_watchlist_entry_missing_returns_404(make_app) -> None:
    app = make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.patch(
            "/api/v1/watchlist/99999",
            json={"active": False},
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_delete_watchlist_entry(make_app) -> None:
    app = make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        created = await client.post(
            "/api/v1/watchlist",
            json={"symbol": "TSLA", "asset_type": "EQUITY"},
        )
        entry_id = created.json()["id"]

        deleted = await client.delete(f"/api/v1/watchlist/{entry_id}")
        assert deleted.status_code == 204

        listing = await client.get("/api/v1/watchlist")
    assert listing.status_code == 200
    assert all(row["id"] != entry_id for row in listing.json())


@pytest.mark.asyncio
async def test_delete_watchlist_entry_missing_returns_404(make_app) -> None:
    app = make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.delete("/api/v1/watchlist/99999")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_active_only_filters_inactive(make_app) -> None:
    app = make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        active = await client.post(
            "/api/v1/watchlist",
            json={"symbol": "AMZN", "asset_type": "EQUITY"},
        )
        inactive = await client.post(
            "/api/v1/watchlist",
            json={"symbol": "META", "asset_type": "EQUITY", "active": False},
        )
        assert active.status_code == 201
        assert inactive.status_code == 201

        listing = await client.get("/api/v1/watchlist", params={"active_only": "true"})
    assert listing.status_code == 200
    symbols = [row["symbol"] for row in listing.json()]
    assert "AMZN" in symbols
    assert "META" not in symbols


@pytest.mark.asyncio
async def test_create_rejects_blank_symbol(make_app) -> None:
    app = make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/v1/watchlist",
            json={"symbol": "   ", "asset_type": "EQUITY"},
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_rejects_invalid_asset_type(make_app) -> None:
    app = make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/v1/watchlist",
            json={"symbol": "AAPL", "asset_type": "CRYPTO"},
        )
    assert response.status_code == 422
