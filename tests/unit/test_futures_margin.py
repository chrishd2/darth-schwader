from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from darth_schwader.risk.futures import (
    DefaultGlobexSchedule,
    FuturesAccountSnapshot,
    FuturesMarginCalc,
)

ET = ZoneInfo("America/New_York")


def _et(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=ET).astimezone(UTC)


def test_margin_headroom_passes_when_post_trade_exceeds_buffer() -> None:
    calc = FuturesMarginCalc()
    account = FuturesAccountSnapshot(
        net_liquidation_value=Decimal("100000"),
        excess_liquidity=Decimal("50000"),
    )

    result = calc.check_margin_headroom(
        account=account,
        proposed_initial_margin=Decimal("20000"),
        buffer_pct=Decimal("0.30"),
    )

    assert result.passed
    assert result.reason_code == "FUTURES_MARGIN_HEADROOM_OK"
    assert result.evidence["post_trade_excess"] == "30000"


def test_margin_headroom_rejects_when_post_trade_below_required_buffer() -> None:
    calc = FuturesMarginCalc()
    account = FuturesAccountSnapshot(
        net_liquidation_value=Decimal("100000"),
        excess_liquidity=Decimal("50000"),
    )

    result = calc.check_margin_headroom(
        account=account,
        proposed_initial_margin=Decimal("40000"),
        buffer_pct=Decimal("0.30"),
    )

    assert not result.passed
    assert result.reason_code == "FUTURES_MARGIN_HEADROOM_BREACH"
    assert result.evidence["required_buffer"] == "15000.00"


def test_margin_headroom_rejects_zero_excess_liquidity() -> None:
    calc = FuturesMarginCalc()
    account = FuturesAccountSnapshot(
        net_liquidation_value=Decimal("50000"),
        excess_liquidity=Decimal("0"),
    )

    result = calc.check_margin_headroom(
        account=account,
        proposed_initial_margin=Decimal("5000"),
        buffer_pct=Decimal("0.30"),
    )

    assert not result.passed
    assert result.reason_code == "NO_EXCESS_LIQUIDITY"


@pytest.mark.parametrize(
    ("proposed", "buffer", "code"),
    [
        (Decimal("-1"), Decimal("0.30"), "INVALID_MARGIN"),
        (Decimal("1"), Decimal("-0.1"), "INVALID_BUFFER"),
        (Decimal("1"), Decimal("1"), "INVALID_BUFFER"),
    ],
)
def test_margin_headroom_rejects_invalid_inputs(
    proposed: Decimal, buffer: Decimal, code: str
) -> None:
    calc = FuturesMarginCalc()
    account = FuturesAccountSnapshot(
        net_liquidation_value=Decimal("100000"),
        excess_liquidity=Decimal("50000"),
    )
    result = calc.check_margin_headroom(
        account=account, proposed_initial_margin=proposed, buffer_pct=buffer
    )
    assert not result.passed
    assert result.reason_code == code


def test_contract_limit_passes_below_cap() -> None:
    calc = FuturesMarginCalc()
    result = calc.check_contract_limit(
        current_contracts=0, additional_contracts=2, max_concurrent=2
    )
    assert result.passed
    assert result.reason_code == "FUTURES_CONTRACT_LIMIT_OK"


def test_contract_limit_rejects_at_cap() -> None:
    calc = FuturesMarginCalc()
    result = calc.check_contract_limit(
        current_contracts=1, additional_contracts=2, max_concurrent=2
    )
    assert not result.passed
    assert result.reason_code == "FUTURES_CONTRACT_LIMIT_EXCEEDED"
    assert result.evidence == {"post_trade": 3, "max_concurrent": 2}


def test_contract_limit_rejects_when_futures_disabled() -> None:
    calc = FuturesMarginCalc()
    result = calc.check_contract_limit(
        current_contracts=0, additional_contracts=1, max_concurrent=0
    )
    assert not result.passed
    assert result.reason_code == "FUTURES_DISABLED"


@pytest.mark.parametrize(
    ("current", "additional"),
    [(-1, 1), (0, 0), (0, -1)],
)
def test_contract_limit_rejects_invalid_counts(current: int, additional: int) -> None:
    calc = FuturesMarginCalc()
    result = calc.check_contract_limit(
        current_contracts=current, additional_contracts=additional, max_concurrent=2
    )
    assert not result.passed
    assert result.reason_code == "INVALID_CONTRACT_COUNT"


def test_session_cutoff_passes_well_before_close() -> None:
    calc = FuturesMarginCalc()
    now = _et(2026, 4, 20, 10, 0)

    result = calc.check_session_cutoff(now_utc=now, cutoff_minutes=15)

    assert result.passed
    assert result.reason_code == "FUTURES_SESSION_OK"
    assert result.evidence["minutes_until_close"] == 7 * 60


def test_session_cutoff_rejects_within_window() -> None:
    calc = FuturesMarginCalc()
    now = _et(2026, 4, 20, 16, 50)

    result = calc.check_session_cutoff(now_utc=now, cutoff_minutes=15)

    assert not result.passed
    assert result.reason_code == "FUTURES_SESSION_CUTOFF"
    assert result.evidence["minutes_until_close"] == 10


def test_session_cutoff_rejects_on_saturday() -> None:
    calc = FuturesMarginCalc()
    now = _et(2026, 4, 25, 10, 0)

    result = calc.check_session_cutoff(now_utc=now, cutoff_minutes=15)

    assert not result.passed
    assert result.reason_code == "FUTURES_MARKET_CLOSED"


def test_session_cutoff_rejects_sunday_before_reopen() -> None:
    calc = FuturesMarginCalc()
    now = _et(2026, 4, 26, 12, 0)

    result = calc.check_session_cutoff(now_utc=now, cutoff_minutes=15)

    assert not result.passed
    assert result.reason_code == "FUTURES_MARKET_CLOSED"


def test_session_cutoff_rejects_during_weekday_maintenance() -> None:
    calc = FuturesMarginCalc()
    now = _et(2026, 4, 20, 17, 30)

    result = calc.check_session_cutoff(now_utc=now, cutoff_minutes=15)

    assert not result.passed
    assert result.reason_code == "FUTURES_MARKET_CLOSED"


def test_session_cutoff_rejects_friday_after_close() -> None:
    calc = FuturesMarginCalc()
    now = _et(2026, 4, 24, 18, 0)

    result = calc.check_session_cutoff(now_utc=now, cutoff_minutes=15)

    assert not result.passed
    assert result.reason_code == "FUTURES_MARKET_CLOSED"


def test_session_cutoff_passes_sunday_after_reopen() -> None:
    calc = FuturesMarginCalc()
    now = _et(2026, 4, 26, 20, 0)

    result = calc.check_session_cutoff(now_utc=now, cutoff_minutes=15)

    assert result.passed
    assert result.reason_code == "FUTURES_SESSION_OK"


def test_session_cutoff_rejects_negative_cutoff() -> None:
    calc = FuturesMarginCalc()
    result = calc.check_session_cutoff(
        now_utc=_et(2026, 4, 20, 10, 0), cutoff_minutes=-1
    )
    assert not result.passed
    assert result.reason_code == "INVALID_CUTOFF"


def test_default_schedule_requires_timezone_aware_datetime() -> None:
    schedule = DefaultGlobexSchedule()
    with pytest.raises(ValueError, match="timezone-aware"):
        schedule.minutes_until_close(datetime(2026, 4, 20, 10, 0))  # noqa: DTZ001


def test_custom_schedule_can_be_injected() -> None:
    class _AlwaysOpen:
        def minutes_until_close(self, now_utc: datetime) -> int | None:
            return 60

    calc = FuturesMarginCalc(schedule=_AlwaysOpen())
    result = calc.check_session_cutoff(
        now_utc=datetime(2026, 4, 25, 10, 0, tzinfo=UTC),
        cutoff_minutes=15,
    )
    assert result.passed
