from __future__ import annotations

from decimal import Decimal

from darth_schwader.ai.contracts import StrategySignal
from darth_schwader.ai.strategies import ValidationError


class VerticalSpreadSpec:
    def validate(self, signal: StrategySignal) -> list[ValidationError]:
        if len(signal.legs) != 2:
            return [ValidationError("legs", "vertical spread requires exactly two legs")]
        if {leg.option_type for leg in signal.legs} != {signal.legs[0].option_type}:
            return [ValidationError("legs", "vertical spread legs must share option type")]
        return []

    def compute_required_collateral(self, signal: StrategySignal, underlying_price: Decimal) -> Decimal:
        strikes = sorted(leg.strike for leg in signal.legs)
        return (strikes[-1] - strikes[0]) * Decimal("100")


__all__ = ["VerticalSpreadSpec"]
