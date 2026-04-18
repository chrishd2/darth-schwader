from __future__ import annotations

from decimal import Decimal

from darth_schwader.ai.contracts import StrategySignal
from darth_schwader.ai.strategies import ValidationError


class CashSecuredPutSpec:
    def validate(self, signal: StrategySignal) -> list[ValidationError]:
        if len(signal.legs) != 1:
            return [ValidationError("legs", "cash-secured put requires one short put leg")]
        leg = signal.legs[0]
        if leg.option_type != "PUT" or leg.side != "SHORT":
            return [ValidationError("legs", "cash-secured put requires one short put leg")]
        return []

    def compute_required_collateral(self, signal: StrategySignal, underlying_price: Decimal) -> Decimal:
        return signal.legs[0].strike * Decimal("100")


__all__ = ["CashSecuredPutSpec"]
