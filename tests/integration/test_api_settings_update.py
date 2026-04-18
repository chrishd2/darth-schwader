from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from darth_schwader.db.models import AuditLog, RiskPolicyOverride


@pytest.mark.asyncio
async def test_allow_naked_requires_confirmation(make_app, session_factory) -> None:
    app = make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.put("/api/v1/settings", json={"allow_naked": True})
    assert response.status_code == 400
    assert "CONFIRM" in response.json()["detail"]


@pytest.mark.asyncio
async def test_settings_update_persists_override_with_confirmation(
    make_app, session_factory
) -> None:
    app = make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.put(
            "/api/v1/settings",
            headers={"X-Confirm": "CONFIRM"},
            json={"allow_naked": True},
        )
    assert response.status_code == 200

    async with session_factory() as session:
        stmt = select(RiskPolicyOverride).where(RiskPolicyOverride.key == "allow_naked")
        row = await session.scalar(stmt)
    assert row is not None
    assert row.value == "True"


@pytest.mark.asyncio
async def test_settings_update_rejects_preferred_above_hard(make_app) -> None:
    app = make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.put(
            "/api/v1/settings",
            json={
                "preferred_max_risk_per_trade_pct": "0.40",
                "max_risk_per_trade_pct": "0.20",
            },
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_paper_trading_toggle_requires_switch_mode_confirmation(make_app) -> None:
    app = make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.put(
            "/api/v1/settings",
            json={"paper_trading": False},
        )
    assert response.status_code == 400
    assert "SWITCH_MODE" in response.json()["detail"]


@pytest.mark.asyncio
async def test_paper_trading_toggle_succeeds_with_switch_mode_header(
    make_app, session_factory
) -> None:
    app = make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.put(
            "/api/v1/settings",
            headers={"X-Confirm": "SWITCH_MODE"},
            json={"paper_trading": False},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["restart_required"] == "true"

    async with session_factory() as session:
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.event_type == "MODE_CHANGE_REQUESTED")
        )
    assert audit is not None
    assert audit.payload_json["from"] is True
    assert audit.payload_json["to"] is False


@pytest.mark.asyncio
async def test_paper_trading_unchanged_does_not_require_switch_mode(
    make_app, session_factory
) -> None:
    app = make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.put(
            "/api/v1/settings",
            json={"paper_trading": True},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["restart_required"] == "false"

    async with session_factory() as session:
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.event_type == "MODE_CHANGE_REQUESTED")
        )
    assert audit is None


@pytest.mark.asyncio
async def test_paper_trading_coerces_string_booleans(make_app) -> None:
    """htmx-json-enc serializes radio values as strings; backend must coerce."""
    app = make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.put(
            "/api/v1/settings",
            headers={"X-Confirm": "SWITCH_MODE"},
            json={"paper_trading": "false"},
        )
    assert response.status_code == 200
    assert response.json()["restart_required"] == "true"


@pytest.mark.asyncio
async def test_settings_get_includes_paper_trading_and_hitl(make_app) -> None:
    app = make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/api/v1/settings")
    assert response.status_code == 200
    body = response.json()
    assert "paper_trading" in body
    assert "hitl_required" in body
