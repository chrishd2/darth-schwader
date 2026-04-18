from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from darth_schwader.db.models import RiskPolicyOverride


@pytest.mark.asyncio
async def test_allow_naked_requires_confirmation(make_app, session_factory) -> None:
    app = make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.put("/api/v1/settings", json={"allow_naked": True})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_settings_update_persists_override_with_confirmation(make_app, session_factory) -> None:
    app = make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.put(
            "/api/v1/settings",
            headers={"X-Confirm": "CONFIRM"},
            json={"allow_naked": True},
        )
    assert response.status_code == 200

    async with session_factory() as session:
        row = await session.scalar(select(RiskPolicyOverride).where(RiskPolicyOverride.key == "allow_naked"))
    assert row is not None
    assert row.value == "True"


@pytest.mark.asyncio
async def test_settings_update_rejects_preferred_above_hard(make_app) -> None:
    app = make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.put(
            "/api/v1/settings",
            json={
                "preferred_max_risk_per_trade_pct": "0.40",
                "max_risk_per_trade_pct": "0.20",
            },
        )
    assert response.status_code == 422
