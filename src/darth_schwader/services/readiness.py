from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from darth_schwader.broker.base import BrokerCapabilities
from darth_schwader.config import Settings
from darth_schwader.db.models import AuditLog, BrokerToken, WatchlistEntry
from darth_schwader.domain.asset_types import AssetType

READINESS_TOKEN_EXPIRY_BUFFER: timedelta = timedelta(minutes=10)
READINESS_PAPER_ACTIVITY_WINDOW: timedelta = timedelta(days=7)
READINESS_MAX_RISK_PER_TRADE_HARD_CAP: Decimal = Decimal("0.02")
READINESS_PAPER_ACTIVITY_EVENTS: frozenset[str] = frozenset({"PAPER_FILL", "ORDER_SUBMITTED"})
SCHWAB_TOKEN_PROVIDER: str = "schwab"


@dataclass(frozen=True, slots=True)
class ReadinessCheck:
    name: str
    passed: bool
    reason_code: str
    reason_text: str
    evidence: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    passed: bool
    checks: tuple[ReadinessCheck, ...]

    @property
    def failing(self) -> tuple[ReadinessCheck, ...]:
        return tuple(check for check in self.checks if not check.passed)


class ReadinessError(RuntimeError):
    def __init__(self, report: ReadinessReport) -> None:
        self.report = report
        codes = [check.reason_code for check in report.failing]
        super().__init__(f"live readiness failed: {codes}")


class _Clock(Protocol):
    def __call__(self) -> datetime: ...


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


async def evaluate_live_readiness(
    *,
    session: AsyncSession,
    settings: Settings,
    live_capabilities: BrokerCapabilities,
    clock: _Clock = _utcnow,
) -> ReadinessReport:
    now = clock()
    checks: tuple[ReadinessCheck, ...] = (
        _check_risk_caps(settings),
        await _check_schwab_token(session, now),
        await _check_watchlist_capabilities(session, live_capabilities),
        await _check_recent_paper_activity(session, now),
    )
    return ReadinessReport(passed=all(check.passed for check in checks), checks=checks)


async def assert_live_readiness(
    *,
    session: AsyncSession,
    settings: Settings,
    live_capabilities: BrokerCapabilities,
    clock: _Clock = _utcnow,
) -> ReadinessReport:
    report = await evaluate_live_readiness(
        session=session,
        settings=settings,
        live_capabilities=live_capabilities,
        clock=clock,
    )
    if not report.passed:
        raise ReadinessError(report)
    return report


def _check_risk_caps(settings: Settings) -> ReadinessCheck:
    cap = READINESS_MAX_RISK_PER_TRADE_HARD_CAP
    risk = settings.max_risk_per_trade_pct
    evidence: dict[str, object] = {
        "max_risk_per_trade_pct": str(risk),
        "live_ceiling": str(cap),
    }
    if risk > cap:
        return ReadinessCheck(
            name="risk_caps",
            passed=False,
            reason_code="RISK_CAP_TOO_HIGH",
            reason_text=(
                f"max_risk_per_trade_pct={risk} exceeds live ceiling {cap}; "
                "tighten before flipping to live."
            ),
            evidence=evidence,
        )
    return ReadinessCheck(
        name="risk_caps",
        passed=True,
        reason_code="RISK_CAP_OK",
        reason_text="risk caps within live ceiling",
        evidence=evidence,
    )


async def _check_schwab_token(session: AsyncSession, now: datetime) -> ReadinessCheck:
    token = await session.scalar(
        select(BrokerToken).where(BrokerToken.provider == SCHWAB_TOKEN_PROVIDER).limit(1)
    )
    if token is None:
        return ReadinessCheck(
            name="schwab_token",
            passed=False,
            reason_code="SCHWAB_TOKEN_MISSING",
            reason_text="no Schwab broker token persisted — complete OAuth before flipping live",
            evidence={},
        )
    expires_at = _ensure_utc(token.access_token_expires_at)
    deadline = now + READINESS_TOKEN_EXPIRY_BUFFER
    evidence: dict[str, object] = {
        "access_token_expires_at": expires_at.isoformat(),
        "expiry_buffer_minutes": int(READINESS_TOKEN_EXPIRY_BUFFER.total_seconds() // 60),
    }
    if expires_at < deadline:
        return ReadinessCheck(
            name="schwab_token",
            passed=False,
            reason_code="SCHWAB_TOKEN_EXPIRING",
            reason_text=(
                f"Schwab access token expires at {expires_at.isoformat()}, "
                "within the 10-minute live-readiness buffer"
            ),
            evidence=evidence,
        )
    return ReadinessCheck(
        name="schwab_token",
        passed=True,
        reason_code="SCHWAB_TOKEN_OK",
        reason_text="Schwab access token valid and not near expiry",
        evidence=evidence,
    )


async def _check_watchlist_capabilities(
    session: AsyncSession, caps: BrokerCapabilities
) -> ReadinessCheck:
    entries = (
        await session.scalars(select(WatchlistEntry).where(WatchlistEntry.active.is_(True)))
    ).all()
    conflicts: list[dict[str, str]] = [
        {"symbol": entry.symbol, "asset_type": entry.asset_type.value}
        for entry in entries
        if not _asset_supported(entry.asset_type, caps)
    ]
    evidence: dict[str, object] = {
        "active_count": len(entries),
        "unsupported": conflicts,
    }
    if conflicts:
        return ReadinessCheck(
            name="watchlist_capabilities",
            passed=False,
            reason_code="LIVE_BROKER_MISSING_ENTITLEMENT",
            reason_text=(
                "live broker does not support asset types in the active watchlist; "
                "disable those entries or add the entitlement before flipping live."
            ),
            evidence=evidence,
        )
    return ReadinessCheck(
        name="watchlist_capabilities",
        passed=True,
        reason_code="WATCHLIST_CAPABILITIES_OK",
        reason_text="live broker supports all active watchlist asset types",
        evidence=evidence,
    )


async def _check_recent_paper_activity(session: AsyncSession, now: datetime) -> ReadinessCheck:
    threshold = now - READINESS_PAPER_ACTIVITY_WINDOW
    count = int(
        await session.scalar(
            select(func.count(AuditLog.id)).where(
                AuditLog.event_type.in_(READINESS_PAPER_ACTIVITY_EVENTS),
                AuditLog.created_at >= threshold,
            )
        )
        or 0
    )
    evidence: dict[str, object] = {
        "window_days": int(READINESS_PAPER_ACTIVITY_WINDOW.days),
        "event_types": sorted(READINESS_PAPER_ACTIVITY_EVENTS),
        "count": count,
    }
    if count == 0:
        return ReadinessCheck(
            name="paper_smoke",
            passed=False,
            reason_code="NO_RECENT_PAPER_ACTIVITY",
            reason_text=(
                "no successful paper runs recorded in the last 7 days — "
                "exercise the paper loop before going live."
            ),
            evidence=evidence,
        )
    return ReadinessCheck(
        name="paper_smoke",
        passed=True,
        reason_code="PAPER_SMOKE_OK",
        reason_text=f"{count} paper activity event(s) in last 7 days",
        evidence=evidence,
    )


def _asset_supported(asset: AssetType, caps: BrokerCapabilities) -> bool:
    if asset is AssetType.FUTURE:
        return caps.supports_futures
    if asset is AssetType.OPTION_UNDERLYING:
        return caps.supports_options
    if asset in (AssetType.EQUITY, AssetType.ETF):
        return caps.supports_equities
    return False


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


__all__ = [
    "READINESS_MAX_RISK_PER_TRADE_HARD_CAP",
    "READINESS_PAPER_ACTIVITY_EVENTS",
    "READINESS_PAPER_ACTIVITY_WINDOW",
    "READINESS_TOKEN_EXPIRY_BUFFER",
    "ReadinessCheck",
    "ReadinessError",
    "ReadinessReport",
    "assert_live_readiness",
    "evaluate_live_readiness",
]
