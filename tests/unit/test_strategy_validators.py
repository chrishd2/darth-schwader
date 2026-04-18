from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from darth_schwader.ai.contracts import StrategyLeg, StrategySignal
from darth_schwader.ai.strategies.calendar_spread import CalendarSpreadSpec
from darth_schwader.ai.strategies.cash_secured_put import CashSecuredPutSpec
from darth_schwader.ai.strategies.covered_call import CoveredCallSpec
from darth_schwader.ai.strategies.defined_risk_directional import DefinedRiskDirectionalSpec
from darth_schwader.ai.strategies.iron_condor import IronCondorSpec
from darth_schwader.ai.strategies.vertical_spread import VerticalSpreadSpec
from darth_schwader.domain.enums import StrategyType


def _expiration(offset: int = 30) -> str:
    return (datetime.now(tz=UTC) + timedelta(days=offset)).date().isoformat()


def _signal(strategy_type: StrategyType, legs: list[StrategyLeg], **features: str) -> StrategySignal:
    return StrategySignal(
        signal_id=f"sig-{strategy_type.value}",
        strategy_type=strategy_type,
        underlying="AAPL",
        direction="neutral",
        legs=legs,
        thesis="validator",
        confidence=Decimal("0.5"),
        expiration_date=datetime.fromisoformat(legs[0].expiration).date(),
        suggested_quantity=1,
        suggested_max_loss=Decimal("100"),
        features_snapshot=features,
    )


def test_vertical_spread_validator_and_collateral() -> None:
    spec = VerticalSpreadSpec()
    valid = _signal(
        StrategyType.VERTICAL_SPREAD,
        [
            StrategyLeg("AAPL  260619C00195000", "LONG", 1, Decimal("195"), _expiration(), "CALL"),
            StrategyLeg("AAPL  260619C00200000", "SHORT", 1, Decimal("200"), _expiration(), "CALL"),
        ],
    )
    invalid = _signal(
        StrategyType.VERTICAL_SPREAD,
        [StrategyLeg("AAPL  260619C00195000", "LONG", 1, Decimal("195"), _expiration(), "CALL")],
    )
    assert spec.validate(valid) == []
    assert spec.validate(invalid)
    assert spec.compute_required_collateral(valid, Decimal("195")) == Decimal("500")


def test_iron_condor_validator_and_collateral() -> None:
    spec = IronCondorSpec()
    valid = _signal(
        StrategyType.IRON_CONDOR,
        [
            StrategyLeg("AAPL  260619P00180000", "LONG", 1, Decimal("180"), _expiration(), "PUT"),
            StrategyLeg("AAPL  260619P00185000", "SHORT", 1, Decimal("185"), _expiration(), "PUT"),
            StrategyLeg("AAPL  260619C00205000", "SHORT", 1, Decimal("205"), _expiration(), "CALL"),
            StrategyLeg("AAPL  260619C00210000", "LONG", 1, Decimal("210"), _expiration(), "CALL"),
        ],
    )
    invalid = _signal(
        StrategyType.IRON_CONDOR,
        valid.legs[:3],
    )
    assert spec.validate(valid) == []
    assert spec.validate(invalid)
    assert spec.compute_required_collateral(valid, Decimal("195")) == Decimal("500")


def test_defined_risk_directional_validator_and_collateral() -> None:
    spec = DefinedRiskDirectionalSpec()
    valid = _signal(
        StrategyType.DEFINED_RISK_DIRECTIONAL,
        [
            StrategyLeg("AAPL  260619P00190000", "LONG", 1, Decimal("190"), _expiration(), "PUT"),
            StrategyLeg("AAPL  260619P00185000", "SHORT", 1, Decimal("185"), _expiration(), "PUT"),
        ],
    )
    invalid = _signal(StrategyType.DEFINED_RISK_DIRECTIONAL, valid.legs[:1])
    assert spec.validate(valid) == []
    assert spec.validate(invalid)
    assert spec.compute_required_collateral(valid, Decimal("195")) == Decimal("500")


def test_cash_secured_put_validator_and_collateral() -> None:
    spec = CashSecuredPutSpec()
    valid = _signal(
        StrategyType.CASH_SECURED_PUT,
        [StrategyLeg("AAPL  260619P00195000", "SHORT", 1, Decimal("195"), _expiration(), "PUT")],
    )
    invalid = _signal(
        StrategyType.CASH_SECURED_PUT,
        [StrategyLeg("AAPL  260619C00195000", "SHORT", 1, Decimal("195"), _expiration(), "CALL")],
    )
    assert spec.validate(valid) == []
    assert spec.validate(invalid)
    assert spec.compute_required_collateral(valid, Decimal("195")) == Decimal("19500")


def test_covered_call_validator_and_collateral() -> None:
    spec = CoveredCallSpec()
    valid = _signal(
        StrategyType.COVERED_CALL,
        [StrategyLeg("AAPL  260619C00200000", "SHORT", 1, Decimal("200"), _expiration(), "CALL")],
    )
    invalid = _signal(
        StrategyType.COVERED_CALL,
        [StrategyLeg("AAPL  260619P00200000", "SHORT", 1, Decimal("200"), _expiration(), "PUT")],
    )
    assert spec.validate(valid) == []
    assert spec.validate(invalid)
    assert spec.compute_required_collateral(valid, Decimal("195")) == Decimal("19500")


def test_calendar_spread_validator_and_collateral() -> None:
    spec = CalendarSpreadSpec()
    valid = _signal(
        StrategyType.CALENDAR_SPREAD,
        [
            StrategyLeg("AAPL  260516C00195000", "SHORT", 1, Decimal("195"), _expiration(20), "CALL"),
            StrategyLeg("AAPL  260619C00195000", "LONG", 1, Decimal("195"), _expiration(50), "CALL"),
        ],
        debit_per_contract="2.50",
    )
    invalid = _signal(
        StrategyType.CALENDAR_SPREAD,
        [
            StrategyLeg("AAPL  260516C00195000", "SHORT", 1, Decimal("195"), _expiration(20), "CALL"),
            StrategyLeg("AAPL  260619C00200000", "LONG", 1, Decimal("200"), _expiration(50), "CALL"),
        ],
        debit_per_contract="2.50",
    )
    assert spec.validate(valid) == []
    assert spec.validate(invalid)
    assert spec.compute_required_collateral(valid, Decimal("195")) == Decimal("250")
