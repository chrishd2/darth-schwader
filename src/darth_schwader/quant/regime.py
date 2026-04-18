from __future__ import annotations

from decimal import Decimal
from enum import IntEnum


class VolRegime(IntEnum):
    LOW = 1
    NORMAL = 2
    ELEVATED = 3
    EXTREME = 4


def classify_regime(rank: Decimal) -> VolRegime:
    value = Decimal(rank)
    if value < Decimal("0") or value > Decimal("100"):
        raise ValueError("iv_rank must be between 0 and 100")
    if value < Decimal("20"):
        return VolRegime.LOW
    if value < Decimal("50"):
        return VolRegime.NORMAL
    if value < Decimal("80"):
        return VolRegime.ELEVATED
    return VolRegime.EXTREME


__all__ = ["VolRegime", "classify_regime"]
