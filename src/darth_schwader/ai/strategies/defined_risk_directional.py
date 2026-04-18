from __future__ import annotations

from decimal import Decimal

from darth_schwader.ai.contracts import StrategySignal
from darth_schwader.ai.strategies import ValidationError


class DefinedRiskDirectionalSpec:
    def validate(self, signal: StrategySignal) -> list[ValidationError]:
        if len(signal.legs) != 2:
            return [ValidationError("legs", "defined-risk directional trade requires two legs")]
        return []

    def compute_required_collateral(self, signal: StrategySignal, underlying_price: Decimal) -> Decimal:
        strikes = sorted(leg.strike for leg in signal.legs)
        return (strikes[-1] - strikes[0]) * Decimal("100")


__all__ = ["DefinedRiskDirectionalSpec"]
