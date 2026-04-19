from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Literal

from darth_schwader.domain.enums import BracketRole, StrategyType

Direction = Literal["LONG", "SHORT"]

DEFAULT_ATR_STOP_MULT = Decimal("1.5")
DEFAULT_RISK_REWARD = Decimal("2.0")
PRICE_QUANTUM = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class BracketLeg:
    role: BracketRole
    price: Decimal


@dataclass(frozen=True, slots=True)
class BracketOrder:
    strategy_type: StrategyType
    direction: Direction
    quantity: int
    entry: BracketLeg
    stop: BracketLeg
    target: BracketLeg

    @property
    def risk_per_unit(self) -> Decimal:
        return (self.entry.price - self.stop.price).copy_abs()

    @property
    def reward_per_unit(self) -> Decimal:
        return (self.target.price - self.entry.price).copy_abs()

    @property
    def total_risk(self) -> Decimal:
        return self.risk_per_unit * Decimal(self.quantity)


@dataclass(frozen=True, slots=True)
class BracketOrderBuilder:
    atr_stop_mult: Decimal = DEFAULT_ATR_STOP_MULT
    risk_reward: Decimal = DEFAULT_RISK_REWARD

    def build(
        self,
        *,
        strategy_type: StrategyType,
        direction: Direction,
        entry_price: Decimal,
        atr: Decimal,
        equity: Decimal,
        max_risk_per_trade_pct: Decimal,
    ) -> BracketOrder:
        if entry_price <= 0:
            raise ValueError("entry_price must be greater than zero")
        if atr <= 0:
            raise ValueError("atr must be greater than zero")
        if equity <= 0:
            raise ValueError("equity must be greater than zero")
        if max_risk_per_trade_pct <= 0:
            raise ValueError("max_risk_per_trade_pct must be greater than zero")

        stop_offset = (atr * self.atr_stop_mult).quantize(PRICE_QUANTUM, rounding=ROUND_HALF_UP)
        if stop_offset <= 0:
            raise ValueError("computed stop offset is not positive; increase atr or atr_stop_mult")

        target_offset = (stop_offset * self.risk_reward).quantize(
            PRICE_QUANTUM, rounding=ROUND_HALF_UP
        )

        if direction == "LONG":
            stop_price = entry_price - stop_offset
            target_price = entry_price + target_offset
        else:
            stop_price = entry_price + stop_offset
            target_price = entry_price - target_offset

        if stop_price <= 0 or target_price <= 0:
            raise ValueError(
                "computed stop/target price is not positive; verify entry_price vs. atr inputs"
            )

        risk_budget = (equity * max_risk_per_trade_pct).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        )
        quantity_raw = risk_budget / stop_offset
        quantity = int(quantity_raw.to_integral_value(rounding=ROUND_FLOOR))
        if quantity <= 0:
            raise ValueError(
                "risk budget too small for the computed stop distance; no contracts to size"
            )

        return BracketOrder(
            strategy_type=strategy_type,
            direction=direction,
            quantity=quantity,
            entry=BracketLeg(role=BracketRole.ENTRY, price=entry_price),
            stop=BracketLeg(role=BracketRole.STOP, price=stop_price),
            target=BracketLeg(role=BracketRole.TARGET, price=target_price),
        )


__all__ = [
    "DEFAULT_ATR_STOP_MULT",
    "DEFAULT_RISK_REWARD",
    "BracketLeg",
    "BracketOrder",
    "BracketOrderBuilder",
    "Direction",
]
