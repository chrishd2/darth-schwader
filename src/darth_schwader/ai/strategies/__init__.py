from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from darth_schwader.ai.contracts import StrategySignal
from darth_schwader.domain.enums import StrategyType

from .calendar_spread import CalendarSpreadSpec
from .cash_secured_put import CashSecuredPutSpec
from .covered_call import CoveredCallSpec
from .defined_risk_directional import DefinedRiskDirectionalSpec
from .iron_condor import IronCondorSpec
from .vertical_spread import VerticalSpreadSpec


@dataclass(frozen=True, slots=True)
class ValidationError:
    field: str
    message: str


class StrategySpec(Protocol):
    def validate(self, signal: StrategySignal) -> list[ValidationError]:
        ...

    def compute_required_collateral(self, signal: StrategySignal, underlying_price: Decimal) -> Decimal:
        ...


STRATEGY_VALIDATORS: dict[StrategyType, StrategySpec] = {
    StrategyType.VERTICAL_SPREAD: VerticalSpreadSpec(),
    StrategyType.IRON_CONDOR: IronCondorSpec(),
    StrategyType.DEFINED_RISK_DIRECTIONAL: DefinedRiskDirectionalSpec(),
    StrategyType.CASH_SECURED_PUT: CashSecuredPutSpec(),
    StrategyType.COVERED_CALL: CoveredCallSpec(),
    StrategyType.CALENDAR_SPREAD: CalendarSpreadSpec(),
}


__all__ = ["STRATEGY_VALIDATORS", "StrategySpec", "ValidationError"]
