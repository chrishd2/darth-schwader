from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from darth_schwader.ai.contracts import StrategyLeg, StrategySignal
from darth_schwader.domain.enums import StrategyType
from darth_schwader.risk.policies import EffectivePolicy
from darth_schwader.risk.rules import (
    check_dte_bounds,
    check_drawdown_breakers,
    check_liquidity,
    check_naked_gate,
    check_open_positions_cap,
    check_per_trade_cap_hard,
    check_per_trade_cap_preferred,
    check_per_underlying_concentration,
    check_settled_cash_collateral,
    check_strategy_whitelist,
)


def _policy(*, allow_naked: bool = False) -> EffectivePolicy:
    return EffectivePolicy(
        max_risk_per_trade_pct=Decimal("0.25"),
        preferred_max_risk_per_trade_pct=Decimal("0.05"),
        max_daily_drawdown_pct=Decimal("0.05"),
        max_weekly_drawdown_pct=Decimal("0.10"),
        max_positions=5,
        max_underlying_allocation_pct=Decimal("0.20"),
        min_dte_days=14,
        max_dte_days=60,
        allow_naked=allow_naked,
        iv_spike_threshold_pct=Decimal("90"),
        options_approval_tier=3,
    )


def _signal(strategy_type: StrategyType, *, dte_days: int = 30) -> StrategySignal:
    expiration = (datetime.now(tz=UTC) + timedelta(days=dte_days)).date()
    return StrategySignal(
        signal_id="sig-1",
        strategy_type=strategy_type,
        underlying="AAPL",
        direction="bullish",
        legs=[
            StrategyLeg(
                occ_symbol="AAPL  260619C00195000",
                side="LONG",
                quantity=1,
                strike=Decimal("195"),
                expiration=expiration.isoformat(),
                option_type="CALL",
            )
        ],
        thesis="test",
        confidence=Decimal("0.7"),
        expiration_date=expiration,
        suggested_quantity=1,
        suggested_max_loss=Decimal("100"),
        features_snapshot={"per_contract_max_loss": "100"},
    )


def test_strategy_whitelist_accepts_cash_safe_strategy() -> None:
    result = check_strategy_whitelist(_signal(StrategyType.VERTICAL_SPREAD), _policy())
    assert result.passed is True


def test_strategy_whitelist_rejects_naked_when_disabled() -> None:
    result = check_strategy_whitelist(_signal(StrategyType.NAKED_CALL), _policy())
    assert result.passed is False
    assert result.reason_code == "STRATEGY_NOT_ALLOWED"


def test_naked_gate_respects_allow_naked_flag() -> None:
    rejected = check_naked_gate(_signal(StrategyType.NAKED_PUT), _policy(allow_naked=False))
    allowed = check_naked_gate(_signal(StrategyType.NAKED_PUT), _policy(allow_naked=True))
    assert rejected.passed is False
    assert allowed.passed is True


def test_dte_bounds_enforce_min_and_max() -> None:
    too_short = check_dte_bounds(_signal(StrategyType.VERTICAL_SPREAD, dte_days=5), _policy())
    too_long = check_dte_bounds(_signal(StrategyType.VERTICAL_SPREAD, dte_days=90), _policy())
    assert too_short.passed is False
    assert too_long.passed is False


def test_per_trade_cap_hard_rejects_above_ceiling() -> None:
    result = check_per_trade_cap_hard(Decimal("2600"), Decimal("10000"), _policy())
    assert result.passed is False
    assert result.reason_code == "HARD_RISK_CEILING_EXCEEDED"


def test_per_trade_cap_preferred_warns_inside_band() -> None:
    result = check_per_trade_cap_preferred(Decimal("800"), Decimal("10000"), _policy())
    assert result.passed is True
    assert result.reason_code == "PREFERRED_RISK_EXCEEDED"


def test_concentration_rejects_when_existing_plus_new_exceeds_limit() -> None:
    result = check_per_underlying_concentration(
        _signal(StrategyType.VERTICAL_SPREAD),
        Decimal("1900"),
        Decimal("10000"),
        _policy(),
        Decimal("200"),
    )
    assert result.passed is False


def test_open_positions_cap_rejects_at_limit() -> None:
    result = check_open_positions_cap(5, _policy())
    assert result.passed is False


def test_drawdown_breakers_reject_on_daily_or_weekly_limit() -> None:
    daily = check_drawdown_breakers(Decimal("-0.06"), Decimal("0"), _policy())
    weekly = check_drawdown_breakers(Decimal("0"), Decimal("-0.11"), _policy())
    assert daily.passed is False
    assert weekly.passed is False


def test_settled_cash_collateral_rejects_when_short() -> None:
    signal = _signal(StrategyType.CASH_SECURED_PUT)
    result = check_settled_cash_collateral(signal, Decimal("5000"), Decimal("2000"))
    assert result.passed is False
    assert result.reason_code == "INSUFFICIENT_SETTLED_CASH"


def test_liquidity_rejects_missing_quotes() -> None:
    result = check_liquidity(_signal(StrategyType.VERTICAL_SPREAD), {})
    assert result.passed is False
    assert result.reason_code == "MISSING_LEG_QUOTES"
