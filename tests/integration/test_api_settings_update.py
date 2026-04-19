from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from darth_schwader.db.models import AuditLog, BrokerToken, RiskPolicyOverride
from darth_schwader.services.readiness import SCHWAB_TOKEN_PROVIDER


async def _seed_live_readiness_fixtures(session_factory) -> None:
    """Seed Schwab token + recent paper activity so live readiness preflight passes."""
    now = datetime.now(tz=UTC)
    async with session_factory() as session:
        session.add(
            BrokerToken(
                provider=SCHWAB_TOKEN_PROVIDER,
                access_token_ciphertext="ct-access",
                refresh_token_ciphertext="ct-refresh",
                access_token_expires_at=now + timedelta(hours=2),
                refresh_token_expires_at=now + timedelta(days=30),
                scope="api",
                token_type="Bearer",
            )
        )
        session.add(
            AuditLog(
                event_type="PAPER_FILL",
                entity_type="order",
                entity_id="seed",
                correlation_id=None,
                payload_json={"note": "seeded-for-readiness"},
                created_at=now - timedelta(hours=1),
            )
        )
        await session.commit()


_LIVE_FLIP_BODY = {
    "paper_trading": False,
    "live_confirm": "EXECUTE LIVE",
    "max_risk_per_trade_pct": "0.02",
    "preferred_max_risk_per_trade_pct": "0.01",
}


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
    await _seed_live_readiness_fixtures(session_factory)
    app = make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.put(
            "/api/v1/settings",
            headers={"X-Confirm": "SWITCH_MODE"},
            json=_LIVE_FLIP_BODY,
        )
    assert response.status_code == 200, response.json()
    body = response.json()
    assert body["restart_required"] == "true"

    async with session_factory() as session:
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.event_type == "MODE_CHANGE_REQUESTED")
        )
    assert audit is not None
    assert audit.payload_json["from"] is True
    assert audit.payload_json["to"] is False

    async with session_factory() as session:
        live_confirm_row = await session.scalar(
            select(RiskPolicyOverride).where(RiskPolicyOverride.key == "live_confirm")
        )
    assert live_confirm_row is None, "live_confirm must not be persisted as a risk override"


@pytest.mark.asyncio
async def test_paper_trading_live_flip_requires_execute_live_field(make_app) -> None:
    app = make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.put(
            "/api/v1/settings",
            headers={"X-Confirm": "SWITCH_MODE"},
            json={"paper_trading": False},
        )
    assert response.status_code == 400
    assert "live_confirm" in response.json()["detail"]
    assert "EXECUTE LIVE" in response.json()["detail"]


@pytest.mark.asyncio
async def test_paper_trading_live_flip_412_when_readiness_fails(make_app) -> None:
    app = make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.put(
            "/api/v1/settings",
            headers={"X-Confirm": "SWITCH_MODE"},
            json=_LIVE_FLIP_BODY,
        )
    assert response.status_code == 412
    detail = response.json()["detail"]
    assert detail["code"] == "READINESS_FAILED"
    assert detail["passed"] is False
    reason_codes = {check["reason_code"] for check in detail["checks"] if not check["passed"]}
    assert "SCHWAB_TOKEN_MISSING" in reason_codes
    assert "NO_RECENT_PAPER_ACTIVITY" in reason_codes


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
async def test_paper_trading_coerces_string_booleans(make_app, session_factory) -> None:
    """htmx-json-enc serializes radio values as strings; backend must coerce."""
    await _seed_live_readiness_fixtures(session_factory)
    app = make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.put(
            "/api/v1/settings",
            headers={"X-Confirm": "SWITCH_MODE"},
            json={**_LIVE_FLIP_BODY, "paper_trading": "false"},
        )
    assert response.status_code == 200, response.json()
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
