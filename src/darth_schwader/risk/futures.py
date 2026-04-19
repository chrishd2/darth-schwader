from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Protocol
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# CME Globex electronic session pattern (covers /MES, /MNQ, /ES, /NQ):
#   Sun 18:00 ET → Fri 17:00 ET continuous, with a daily 60-minute halt
#   17:00 ET → 18:00 ET Mon-Thu. Saturday is fully closed.
GLOBEX_DAILY_CLOSE_HOUR_ET = 17
GLOBEX_DAILY_REOPEN_HOUR_ET = 18
_MONDAY = 0
_THURSDAY = 3
_FRIDAY = 4
_SATURDAY = 5
_SUNDAY = 6


@dataclass(frozen=True, slots=True)
class FuturesCheckResult:
    passed: bool
    reason_code: str
    reason_text: str
    evidence: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FuturesAccountSnapshot:
    net_liquidation_value: Decimal
    excess_liquidity: Decimal


class GlobexSchedule(Protocol):
    def minutes_until_close(self, now_utc: datetime) -> int | None:
        ...


class DefaultGlobexSchedule:
    def minutes_until_close(self, now_utc: datetime) -> int | None:
        if now_utc.tzinfo is None:
            raise ValueError("now_utc must be timezone-aware")
        local = now_utc.astimezone(ET)
        weekday = local.weekday()
        hour = local.hour

        if weekday == _SATURDAY:
            return None
        if weekday == _SUNDAY and hour < GLOBEX_DAILY_REOPEN_HOUR_ET:
            return None
        if _MONDAY <= weekday <= _THURSDAY and hour == GLOBEX_DAILY_CLOSE_HOUR_ET:
            return None
        if weekday == _FRIDAY and hour >= GLOBEX_DAILY_CLOSE_HOUR_ET:
            return None

        today_close = local.replace(
            hour=GLOBEX_DAILY_CLOSE_HOUR_ET, minute=0, second=0, microsecond=0
        )
        next_close = today_close if local < today_close else today_close + timedelta(days=1)
        delta_seconds = (next_close - local).total_seconds()
        return int(delta_seconds // 60)


DEFAULT_GLOBEX_SCHEDULE: GlobexSchedule = DefaultGlobexSchedule()


@dataclass(frozen=True, slots=True)
class FuturesMarginCalc:
    schedule: GlobexSchedule = DEFAULT_GLOBEX_SCHEDULE

    def check_margin_headroom(
        self,
        *,
        account: FuturesAccountSnapshot,
        proposed_initial_margin: Decimal,
        buffer_pct: Decimal,
    ) -> FuturesCheckResult:
        if proposed_initial_margin < Decimal("0"):
            return FuturesCheckResult(
                passed=False,
                reason_code="INVALID_MARGIN",
                reason_text="proposed initial margin cannot be negative",
            )
        if buffer_pct < Decimal("0") or buffer_pct >= Decimal("1"):
            return FuturesCheckResult(
                passed=False,
                reason_code="INVALID_BUFFER",
                reason_text="buffer_pct must be in [0, 1)",
            )
        if account.excess_liquidity <= Decimal("0"):
            return FuturesCheckResult(
                passed=False,
                reason_code="NO_EXCESS_LIQUIDITY",
                reason_text="account has no excess liquidity for new futures contract",
                evidence={"excess_liquidity": str(account.excess_liquidity)},
            )

        post_trade = account.excess_liquidity - proposed_initial_margin
        required = account.excess_liquidity * buffer_pct
        if post_trade < required:
            return FuturesCheckResult(
                passed=False,
                reason_code="FUTURES_MARGIN_HEADROOM_BREACH",
                reason_text="post-trade excess liquidity below required buffer",
                evidence={
                    "post_trade_excess": str(post_trade),
                    "required_buffer": str(required),
                    "buffer_pct": str(buffer_pct),
                    "proposed_initial_margin": str(proposed_initial_margin),
                },
            )
        return FuturesCheckResult(
            passed=True,
            reason_code="FUTURES_MARGIN_HEADROOM_OK",
            reason_text="futures margin headroom satisfied",
            evidence={"post_trade_excess": str(post_trade)},
        )

    def check_contract_limit(
        self,
        *,
        current_contracts: int,
        additional_contracts: int,
        max_concurrent: int,
    ) -> FuturesCheckResult:
        if current_contracts < 0 or additional_contracts <= 0:
            return FuturesCheckResult(
                passed=False,
                reason_code="INVALID_CONTRACT_COUNT",
                reason_text="current_contracts must be >= 0 and additional_contracts must be > 0",
            )
        if max_concurrent <= 0:
            return FuturesCheckResult(
                passed=False,
                reason_code="FUTURES_DISABLED",
                reason_text="futures contracts are disabled (max_concurrent=0)",
                evidence={"max_concurrent": max_concurrent},
            )

        post_trade = current_contracts + additional_contracts
        if post_trade > max_concurrent:
            return FuturesCheckResult(
                passed=False,
                reason_code="FUTURES_CONTRACT_LIMIT_EXCEEDED",
                reason_text=(
                    f"post-trade futures contracts ({post_trade}) "
                    f"would exceed cap ({max_concurrent})"
                ),
                evidence={"post_trade": post_trade, "max_concurrent": max_concurrent},
            )
        return FuturesCheckResult(
            passed=True,
            reason_code="FUTURES_CONTRACT_LIMIT_OK",
            reason_text="futures contract limit satisfied",
            evidence={"post_trade": post_trade, "max_concurrent": max_concurrent},
        )

    def check_session_cutoff(
        self,
        *,
        now_utc: datetime,
        cutoff_minutes: int,
    ) -> FuturesCheckResult:
        if cutoff_minutes < 0:
            return FuturesCheckResult(
                passed=False,
                reason_code="INVALID_CUTOFF",
                reason_text="cutoff_minutes must be non-negative",
            )

        minutes = self.schedule.minutes_until_close(now_utc)
        if minutes is None:
            return FuturesCheckResult(
                passed=False,
                reason_code="FUTURES_MARKET_CLOSED",
                reason_text="futures market currently closed",
            )
        if minutes <= cutoff_minutes:
            return FuturesCheckResult(
                passed=False,
                reason_code="FUTURES_SESSION_CUTOFF",
                reason_text=f"within {cutoff_minutes} minutes of globex close",
                evidence={
                    "minutes_until_close": minutes,
                    "cutoff_minutes": cutoff_minutes,
                },
            )
        return FuturesCheckResult(
            passed=True,
            reason_code="FUTURES_SESSION_OK",
            reason_text="futures session cutoff satisfied",
            evidence={"minutes_until_close": minutes},
        )


__all__ = [
    "DEFAULT_GLOBEX_SCHEDULE",
    "DefaultGlobexSchedule",
    "FuturesAccountSnapshot",
    "FuturesCheckResult",
    "FuturesMarginCalc",
    "GlobexSchedule",
]
