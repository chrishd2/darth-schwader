from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from darth_schwader.db.models import AuditLog, BrokerToken, RiskPolicyOverride, WatchlistEntry
from darth_schwader.domain.asset_types import AssetType
from darth_schwader.services.readiness import SCHWAB_TOKEN_PROVIDER


_LIVE_FLIP_BODY: dict[str, object] = {
    "paper_trading": False,
    "live_confirm": "EXECUTE LIVE",
    "max_risk_per_trade_pct": "0.02",
    "preferred_max_risk_per_trade_pct": "0.01",
}
_LIVE_FLIP_HEADERS: dict[str, str] = {"X-Confirm": "SWITCH_MODE"}


async def _seed_schwab_token(session_factory, *, expires_at: datetime) -> None:
    async with session_factory() as session:
        session.add(
            BrokerToken(
                provider=SCHWAB_TOKEN_PROVIDER,
                access_token_ciphertext="ct-access",
                refresh_token_ciphertext="ct-refresh",
                access_token_expires_at=expires_at,
                refresh_token_expires_at=expires_at + timedelta(days=30),
                scope="api",
                token_type="Bearer",
            )
        )
        await session.commit()


async def _seed_paper_activity(
    session_factory, *, created_at: datetime, event_type: str = "PAPER_FILL"
) -> None:
    async with session_factory() as session:
        session.add(
            AuditLog(
                event_type=event_type,
                entity_type="order",
                entity_id="seed",
                correlation_id=None,
                payload_json={"note": "seeded-for-readiness"},
                created_at=created_at,
            )
        )
        await session.commit()


async def _seed_watchlist_entry(
    session_factory,
    *,
    symbol: str,
    asset_type: AssetType,
    active: bool = True,
) -> None:
    async with session_factory() as session:
        session.add(
            WatchlistEntry(
                symbol=symbol,
                asset_type=asset_type,
                strategies=[],
                active=active,
                notes=None,
            )
        )
        await session.commit()


async def _seed_green_readiness(session_factory) -> None:
    now = datetime.now(tz=UTC)
    await _seed_schwab_token(session_factory, expires_at=now + timedelta(hours=2))
    await _seed_paper_activity(session_factory, created_at=now - timedelta(hours=1))


def _failing_codes(detail: dict[str, object]) -> set[str]:
    return {
        check["reason_code"]
        for check in detail["checks"]
        if not check["passed"]
    }


@pytest.mark.asyncio
async def test_live_flip_blocks_with_no_credentials(make_app) -> None:
    app = make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.put(
            "/api/v1/settings",
            headers=_LIVE_FLIP_HEADERS,
            json=_LIVE_FLIP_BODY,
        )

    assert response.status_code == 412, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "READINESS_FAILED"
    assert detail["passed"] is False
    codes = _failing_codes(detail)
    assert "SCHWAB_TOKEN_MISSING" in codes
    assert "NO_RECENT_PAPER_ACTIVITY" in codes


@pytest.mark.asyncio
async def test_live_flip_blocks_when_token_within_expiry_buffer(
    make_app, session_factory
) -> None:
    now = datetime.now(tz=UTC)
    await _seed_schwab_token(session_factory, expires_at=now + timedelta(minutes=5))
    await _seed_paper_activity(session_factory, created_at=now - timedelta(hours=1))

    app = make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.put(
            "/api/v1/settings",
            headers=_LIVE_FLIP_HEADERS,
            json=_LIVE_FLIP_BODY,
        )

    assert response.status_code == 412
    codes = _failing_codes(response.json()["detail"])
    assert "SCHWAB_TOKEN_EXPIRING" in codes


@pytest.mark.asyncio
async def test_live_flip_blocks_when_paper_activity_stale(
    make_app, session_factory
) -> None:
    now = datetime.now(tz=UTC)
    await _seed_schwab_token(session_factory, expires_at=now + timedelta(hours=2))
    await _seed_paper_activity(session_factory, created_at=now - timedelta(days=10))

    app = make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.put(
            "/api/v1/settings",
            headers=_LIVE_FLIP_HEADERS,
            json=_LIVE_FLIP_BODY,
        )

    assert response.status_code == 412
    codes = _failing_codes(response.json()["detail"])
    assert "NO_RECENT_PAPER_ACTIVITY" in codes


@pytest.mark.asyncio
async def test_live_flip_blocks_when_watchlist_includes_unsupported_asset(
    make_app, session_factory
) -> None:
    await _seed_green_readiness(session_factory)
    await _seed_watchlist_entry(
        session_factory, symbol="ES", asset_type=AssetType.FUTURE
    )

    app = make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.put(
            "/api/v1/settings",
            headers=_LIVE_FLIP_HEADERS,
            json=_LIVE_FLIP_BODY,
        )

    assert response.status_code == 412
    detail = response.json()["detail"]
    codes = _failing_codes(detail)
    assert "LIVE_BROKER_MISSING_ENTITLEMENT" in codes
    watchlist_check = next(
        check for check in detail["checks"] if check["name"] == "watchlist_capabilities"
    )
    assert {"symbol": "ES", "asset_type": "FUTURE"} in watchlist_check["evidence"]["unsupported"]


@pytest.mark.asyncio
async def test_live_flip_blocks_when_risk_cap_above_live_ceiling(
    make_app, session_factory
) -> None:
    await _seed_green_readiness(session_factory)

    too_high_body = {
        **_LIVE_FLIP_BODY,
        "max_risk_per_trade_pct": "0.05",
        "preferred_max_risk_per_trade_pct": "0.03",
    }

    app = make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.put(
            "/api/v1/settings",
            headers=_LIVE_FLIP_HEADERS,
            json=too_high_body,
        )

    assert response.status_code == 412
    codes = _failing_codes(response.json()["detail"])
    assert "RISK_CAP_TOO_HIGH" in codes


@pytest.mark.asyncio
async def test_live_flip_succeeds_when_all_readiness_checks_pass(
    make_app, session_factory
) -> None:
    await _seed_green_readiness(session_factory)
    await _seed_watchlist_entry(
        session_factory, symbol="AAPL", asset_type=AssetType.OPTION_UNDERLYING
    )

    app = make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.put(
            "/api/v1/settings",
            headers=_LIVE_FLIP_HEADERS,
            json=_LIVE_FLIP_BODY,
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "ok"
    assert body["restart_required"] == "true"

    async with session_factory() as session:
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.event_type == "MODE_CHANGE_REQUESTED")
        )
        live_confirm_row = await session.scalar(
            select(RiskPolicyOverride).where(RiskPolicyOverride.key == "live_confirm")
        )
        risk_override = await session.scalar(
            select(RiskPolicyOverride).where(
                RiskPolicyOverride.key == "max_risk_per_trade_pct"
            )
        )

    assert audit is not None
    assert audit.payload_json == {"from": True, "to": False}
    assert live_confirm_row is None, "live_confirm is a one-shot token, never persisted"
    assert risk_override is not None
    assert Decimal(risk_override.value) == Decimal("0.02")


@pytest.mark.asyncio
async def test_live_flip_updates_runtime_settings_without_restart(
    make_app, session_factory
) -> None:
    await _seed_green_readiness(session_factory)

    app = make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.put(
            "/api/v1/settings",
            headers=_LIVE_FLIP_HEADERS,
            json=_LIVE_FLIP_BODY,
        )

    assert response.status_code == 200

    assert app.state.settings.max_risk_per_trade_pct == Decimal("0.02")
    assert app.state.settings.preferred_max_risk_per_trade_pct == Decimal("0.01")


@pytest.mark.asyncio
async def test_live_to_paper_flip_skips_readiness_and_audits(
    make_app, session_factory, settings
) -> None:
    app = make_app()
    app.state.settings = settings.model_copy(update={"paper_trading": False})

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.put(
            "/api/v1/settings",
            headers=_LIVE_FLIP_HEADERS,
            json={"paper_trading": True},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["restart_required"] == "true"

    async with session_factory() as session:
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.event_type == "MODE_CHANGE_REQUESTED")
        )

    assert audit is not None
    assert audit.payload_json == {"from": False, "to": True}
