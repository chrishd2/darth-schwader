from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from darth_schwader.ai.contracts import StrategyLeg, StrategySignal
from darth_schwader.domain.enums import StrategyType
from darth_schwader.risk.engine import RiskEngine
from darth_schwader.risk.models import RiskContext
from darth_schwader.risk.policies import EffectivePolicy


def _policy() -> EffectivePolicy:
    return EffectivePolicy(
        max_risk_per_trade_pct=Decimal("0.25"),
        preferred_max_risk_per_trade_pct=Decimal("0.05"),
        max_daily_drawdown_pct=Decimal("0.05"),
        max_weekly_drawdown_pct=Decimal("0.10"),
        max_positions=5,
        max_underlying_allocation_pct=Decimal("0.20"),
        min_dte_days=14,
        max_dte_days=60,
        allow_naked=False,
        iv_spike_threshold_pct=Decimal("90"),
        options_approval_tier=3,
    )


def _signal(quantity: int = 8) -> StrategySignal:
    expiration = (datetime.now(tz=UTC) + timedelta(days=30)).date()
    return StrategySignal(
        signal_id="sig-v3",
        strategy_type=StrategyType.VERTICAL_SPREAD,
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
        thesis="v3 sizing",
        confidence=Decimal("0.8"),
        expiration_date=expiration,
        suggested_quantity=quantity,
        suggested_max_loss=Decimal("800"),
        features_snapshot={"per_contract_max_loss": "100", "required_collateral_per_contract": "100"},
    )


def _context() -> RiskContext:
    return RiskContext(
        policy=_policy(),
        account_type="CASH",
        nlv=Decimal("10000"),
        day_pnl_pct=Decimal("0"),
        week_pnl_pct=Decimal("0"),
        existing_exposure=Decimal("0"),
        open_positions_count=0,
        settled_cash=Decimal("10000"),
        state="ACTIVE",
        leg_quotes={"AAPL  260619C00195000": {"bid": Decimal("1.00"), "ask": Decimal("1.10"), "open_interest": Decimal("100")}},
        options_approval_tier=3,
    )


def test_engine_warns_between_preferred_and_hard_ceiling() -> None:
    decision = RiskEngine().evaluate(_signal(quantity=8), _context())
    assert decision.decision == "APPROVE"
    assert decision.approved_quantity == 8
    assert decision.preferred_quantity == 5
    assert decision.ceiling_quantity == 25
    assert [warning.reason_code for warning in decision.warnings] == ["PREFERRED_RISK_EXCEEDED"]


def test_engine_rejects_override_above_ceiling() -> None:
    decision = RiskEngine().evaluate(_signal(quantity=8), _context(), override_quantity=26)
    assert decision.decision == "REJECT"
    assert decision.reason_code == "OVERRIDE_EXCEEDS_CEILING"
