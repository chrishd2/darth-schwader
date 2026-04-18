from __future__ import annotations

from decimal import Decimal

from darth_schwader.ai.contracts import StrategySignal
from darth_schwader.ai.strategies import ValidationError


class IronCondorSpec:
    def validate(self, signal: StrategySignal) -> list[ValidationError]:
        if len(signal.legs) != 4:
            return [ValidationError("legs", "iron condor requires four legs")]
        return []

    def compute_required_collateral(self, signal: StrategySignal, underlying_price: Decimal) -> Decimal:
        calls = sorted(leg.strike for leg in signal.legs if leg.option_type == "CALL")
        puts = sorted(leg.strike for leg in signal.legs if leg.option_type == "PUT")
        return max(calls[-1] - calls[0], puts[-1] - puts[0]) * Decimal("100")


__all__ = ["IronCondorSpec"]
