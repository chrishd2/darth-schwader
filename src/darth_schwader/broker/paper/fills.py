from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from uuid import NAMESPACE_URL, uuid5

from darth_schwader.broker.models import Fill, OrderLeg

BUY_INSTRUCTIONS: frozenset[str] = frozenset(
    {"BUY", "BUY_TO_OPEN", "BUY_TO_CLOSE"},
)
SELL_INSTRUCTIONS: frozenset[str] = frozenset(
    {"SELL", "SELL_TO_OPEN", "SELL_TO_CLOSE"},
)
SUPPORTED_INSTRUCTIONS: frozenset[str] = BUY_INSTRUCTIONS | SELL_INSTRUCTIONS

_BPS_DIVISOR = Decimal("10000")
_PRICE_QUANTUM = Decimal("0.01")


class MarketSession(StrEnum):
    REGULAR = "REGULAR"
    PREMARKET = "PREMARKET"
    POSTMARKET = "POSTMARKET"
    CLOSED = "CLOSED"


@dataclass(frozen=True)
class FillSimulator:
    slippage_bps: int
    session_penalty_bps: int

    def simulate(
        self,
        leg: OrderLeg,
        ref_price: Decimal,
        session: MarketSession,
        now: datetime | None = None,
    ) -> Fill:
        if leg.instruction not in SUPPORTED_INSTRUCTIONS:
            raise ValueError(f"unsupported fill instruction: {leg.instruction}")

        occurred_at = now or datetime.now(tz=UTC)
        total_bps = Decimal(self.slippage_bps) / _BPS_DIVISOR
        if session is not MarketSession.REGULAR:
            total_bps += Decimal(self.session_penalty_bps) / _BPS_DIVISOR

        side = Decimal("1") if leg.instruction in BUY_INSTRUCTIONS else Decimal("-1")
        price = ref_price * (Decimal("1") + side * total_bps)
        quantized = price.quantize(_PRICE_QUANTUM, rounding=ROUND_HALF_UP)

        fill_id = uuid5(
            NAMESPACE_URL,
            (
                f"{leg.instrument_symbol}|{leg.asset_type}|{leg.instruction}|"
                f"{leg.quantity}|{ref_price}|{session.value}|{occurred_at.isoformat()}"
            ),
        )
        return Fill(
            broker_fill_id=str(fill_id),
            quantity=leg.quantity,
            price=quantized,
            occurred_at=occurred_at,
        )


__all__ = [
    "BUY_INSTRUCTIONS",
    "SELL_INSTRUCTIONS",
    "SUPPORTED_INSTRUCTIONS",
    "FillSimulator",
    "MarketSession",
]
