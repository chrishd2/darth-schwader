from __future__ import annotations

from decimal import Decimal

from darth_schwader.ai.contracts import StrategySignal
from darth_schwader.ai.strategies import ValidationError


class CalendarSpreadSpec:
    def validate(self, signal: StrategySignal) -> list[ValidationError]:
        if len(signal.legs) != 2:
            return [ValidationError("legs", "calendar spread requires two legs")]
        if signal.legs[0].strike != signal.legs[1].strike:
            return [ValidationError("legs", "calendar spread strikes must match")]
        if signal.legs[0].expiration == signal.legs[1].expiration:
            return [ValidationError("legs", "calendar spread expirations must differ")]
        return []

    def compute_required_collateral(self, signal: StrategySignal, underlying_price: Decimal) -> Decimal:
        debit = Decimal(str(signal.features_snapshot.get("debit_per_contract", "0")))
        return max(debit, Decimal("0")) * Decimal("100")


__all__ = ["CalendarSpreadSpec"]
