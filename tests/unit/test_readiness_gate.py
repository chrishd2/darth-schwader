from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from darth_schwader.broker.base import BrokerCapabilities
from darth_schwader.config import Settings
from darth_schwader.db.models import AuditLog, BrokerToken, WatchlistEntry
from darth_schwader.domain.asset_types import AssetType
from darth_schwader.services.readiness import (
    READINESS_MAX_RISK_PER_TRADE_HARD_CAP,
    SCHWAB_TOKEN_PROVIDER,
    ReadinessError,
    assert_live_readiness,
    evaluate_live_readiness,
)

pytestmark = pytest.mark.asyncio


LIVE_CAPS = BrokerCapabilities(
    supports_options=True,
    supports_equities=True,
    supports_futures=False,
    is_paper=False,
)


def _frozen_clock(now: datetime):
    def _clock() -> datetime:
        return now

    return _clock


async def _seed_schwab_token(
    session_factory: async_sessionmaker, *, expires_at: datetime
) -> None:
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
    session_factory: async_sessionmaker, *, created_at: datetime, event_type: str = "PAPER_FILL"
) -> None:
    async with session_factory() as session:
        session.add(
            AuditLog(
                event_type=event_type,
                entity_type="order",
                entity_id="1",
                correlation_id=None,
                payload_json={"note": "seeded"},
                created_at=created_at,
            )
        )
        await session.commit()


async def _seed_watchlist_entry(
    session_factory: async_sessionmaker,
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


def _make_settings(**overrides) -> Settings:
    base: dict[str, object] = {
        "env": "test",
        "database_url": "sqlite+aiosqlite:///:memory:",
        "schwab_client_id": "client-id",
        "schwab_client_secret": "client-secret",
        "schwab_account_number": "123456789",
        "token_encryption_key": "dGVzdC1rZXktZm9yLXJlYWRpbmVzcy10ZXN0cy0xMjM0NQ==",
        "watchlist": ["AAPL"],
        "max_risk_per_trade_pct": Decimal("0.02"),
        "preferred_max_risk_per_trade_pct": Decimal("0.01"),
    }
    base.update(overrides)
    return Settings(**base)


async def test_all_green_report_passes(session_factory) -> None:
    now = datetime(2026, 4, 19, 12, 0, tzinfo=UTC)
    await _seed_schwab_token(session_factory, expires_at=now + timedelta(hours=2))
    await _seed_paper_activity(session_factory, created_at=now - timedelta(days=1))
    await _seed_watchlist_entry(
        session_factory, symbol="AAPL", asset_type=AssetType.OPTION_UNDERLYING
    )

    async with session_factory() as session:
        report = await evaluate_live_readiness(
            session=session,
            settings=_make_settings(),
            live_capabilities=LIVE_CAPS,
            clock=_frozen_clock(now),
        )

    assert report.passed is True
    assert {check.reason_code for check in report.checks} == {
        "RISK_CAP_OK",
        "SCHWAB_TOKEN_OK",
        "WATCHLIST_CAPABILITIES_OK",
        "PAPER_SMOKE_OK",
    }


async def test_risk_cap_too_high_fails(session_factory) -> None:
    now = datetime(2026, 4, 19, 12, 0, tzinfo=UTC)
    await _seed_schwab_token(session_factory, expires_at=now + timedelta(hours=2))
    await _seed_paper_activity(session_factory, created_at=now - timedelta(days=1))

    too_high = READINESS_MAX_RISK_PER_TRADE_HARD_CAP + Decimal("0.01")
    settings = _make_settings(
        max_risk_per_trade_pct=too_high,
        preferred_max_risk_per_trade_pct=too_high,
    )

    async with session_factory() as session:
        report = await evaluate_live_readiness(
            session=session,
            settings=settings,
            live_capabilities=LIVE_CAPS,
            clock=_frozen_clock(now),
        )

    assert report.passed is False
    failing_codes = {check.reason_code for check in report.failing}
    assert "RISK_CAP_TOO_HIGH" in failing_codes


async def test_missing_schwab_token_fails(session_factory) -> None:
    now = datetime(2026, 4, 19, 12, 0, tzinfo=UTC)
    await _seed_paper_activity(session_factory, created_at=now - timedelta(days=1))

    async with session_factory() as session:
        report = await evaluate_live_readiness(
            session=session,
            settings=_make_settings(),
            live_capabilities=LIVE_CAPS,
            clock=_frozen_clock(now),
        )

    assert report.passed is False
    failing_codes = {check.reason_code for check in report.failing}
    assert "SCHWAB_TOKEN_MISSING" in failing_codes


async def test_schwab_token_within_buffer_fails(session_factory) -> None:
    now = datetime(2026, 4, 19, 12, 0, tzinfo=UTC)
    await _seed_schwab_token(session_factory, expires_at=now + timedelta(minutes=5))
    await _seed_paper_activity(session_factory, created_at=now - timedelta(days=1))

    async with session_factory() as session:
        report = await evaluate_live_readiness(
            session=session,
            settings=_make_settings(),
            live_capabilities=LIVE_CAPS,
            clock=_frozen_clock(now),
        )

    assert report.passed is False
    failing_codes = {check.reason_code for check in report.failing}
    assert "SCHWAB_TOKEN_EXPIRING" in failing_codes


async def test_unsupported_watchlist_asset_fails(session_factory) -> None:
    now = datetime(2026, 4, 19, 12, 0, tzinfo=UTC)
    await _seed_schwab_token(session_factory, expires_at=now + timedelta(hours=2))
    await _seed_paper_activity(session_factory, created_at=now - timedelta(days=1))
    await _seed_watchlist_entry(session_factory, symbol="ES", asset_type=AssetType.FUTURE)

    async with session_factory() as session:
        report = await evaluate_live_readiness(
            session=session,
            settings=_make_settings(),
            live_capabilities=LIVE_CAPS,
            clock=_frozen_clock(now),
        )

    assert report.passed is False
    failing = next(check for check in report.failing if check.name == "watchlist_capabilities")
    assert failing.reason_code == "LIVE_BROKER_MISSING_ENTITLEMENT"
    unsupported = failing.evidence["unsupported"]
    assert {"symbol": "ES", "asset_type": "FUTURE"} in unsupported


async def test_inactive_watchlist_entries_ignored(session_factory) -> None:
    now = datetime(2026, 4, 19, 12, 0, tzinfo=UTC)
    await _seed_schwab_token(session_factory, expires_at=now + timedelta(hours=2))
    await _seed_paper_activity(session_factory, created_at=now - timedelta(days=1))
    await _seed_watchlist_entry(
        session_factory, symbol="ES", asset_type=AssetType.FUTURE, active=False
    )

    async with session_factory() as session:
        report = await evaluate_live_readiness(
            session=session,
            settings=_make_settings(),
            live_capabilities=LIVE_CAPS,
            clock=_frozen_clock(now),
        )

    assert report.passed is True


async def test_stale_paper_activity_fails(session_factory) -> None:
    now = datetime(2026, 4, 19, 12, 0, tzinfo=UTC)
    await _seed_schwab_token(session_factory, expires_at=now + timedelta(hours=2))
    await _seed_paper_activity(session_factory, created_at=now - timedelta(days=10))

    async with session_factory() as session:
        report = await evaluate_live_readiness(
            session=session,
            settings=_make_settings(),
            live_capabilities=LIVE_CAPS,
            clock=_frozen_clock(now),
        )

    assert report.passed is False
    failing_codes = {check.reason_code for check in report.failing}
    assert "NO_RECENT_PAPER_ACTIVITY" in failing_codes


async def test_order_submitted_counts_as_paper_activity(session_factory) -> None:
    now = datetime(2026, 4, 19, 12, 0, tzinfo=UTC)
    await _seed_schwab_token(session_factory, expires_at=now + timedelta(hours=2))
    await _seed_paper_activity(
        session_factory,
        created_at=now - timedelta(hours=1),
        event_type="ORDER_SUBMITTED",
    )

    async with session_factory() as session:
        report = await evaluate_live_readiness(
            session=session,
            settings=_make_settings(),
            live_capabilities=LIVE_CAPS,
            clock=_frozen_clock(now),
        )

    assert report.passed is True


async def test_assert_live_readiness_raises_on_failure(session_factory) -> None:
    now = datetime(2026, 4, 19, 12, 0, tzinfo=UTC)

    async with session_factory() as session:
        with pytest.raises(ReadinessError) as excinfo:
            await assert_live_readiness(
                session=session,
                settings=_make_settings(),
                live_capabilities=LIVE_CAPS,
                clock=_frozen_clock(now),
            )

    assert excinfo.value.report.passed is False
    assert excinfo.value.report.failing


async def test_assert_live_readiness_returns_report_on_success(session_factory) -> None:
    now = datetime(2026, 4, 19, 12, 0, tzinfo=UTC)
    await _seed_schwab_token(session_factory, expires_at=now + timedelta(hours=2))
    await _seed_paper_activity(session_factory, created_at=now - timedelta(days=1))

    async with session_factory() as session:
        report = await assert_live_readiness(
            session=session,
            settings=_make_settings(),
            live_capabilities=LIVE_CAPS,
            clock=_frozen_clock(now),
        )

    assert report.passed is True
