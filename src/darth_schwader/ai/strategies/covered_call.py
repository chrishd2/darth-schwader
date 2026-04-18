from __future__ import annotations

from decimal import Decimal

from darth_schwader.ai.contracts import StrategySignal
from darth_schwader.ai.strategies import ValidationError


class CoveredCallSpec:
    def validate(self, signal: StrategySignal) -> list[ValidationError]:
        if len(signal.legs) != 1:
            return [ValidationError("legs", "covered call requires one short call leg")]
        leg = signal.legs[0]
        if leg.option_type != "CALL" or leg.side != "SHORT":
            return [ValidationError("legs", "covered call requires one short call leg")]
        return []

    def compute_required_collateral(self, signal: StrategySignal, underlying_price: Decimal) -> Decimal:
        return underlying_price * Decimal("100")


__all__ = ["CoveredCallSpec"]
