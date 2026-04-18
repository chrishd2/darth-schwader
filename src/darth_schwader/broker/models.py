from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from darth_schwader.domain.enums import CollateralKind, OrderStatus, StrategyType


class Account(BaseModel):
    model_config = ConfigDict(frozen=True)

    broker_account_id: str
    account_type: str
    net_liquidation_value: Decimal
    cash_balance: Decimal
    buying_power: Decimal | None = None
    options_approval_tier: int | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class PositionLeg(BaseModel):
    model_config = ConfigDict(frozen=True)

    symbol: str
    quantity: int
    side: Literal["LONG", "SHORT"]
    strike: Decimal | None = None
    expiration_date: str | None = None
    option_type: Literal["CALL", "PUT"] | None = None


class Position(BaseModel):
    model_config = ConfigDict(frozen=True)

    broker_position_id: str | None = None
    underlying: str
    strategy_type: StrategyType
    quantity: int
    entry_cost: Decimal | None = None
    current_mark: Decimal | None = None
    max_loss: Decimal
    defined_risk: bool
    is_naked: bool = False
    collateral_amount: Decimal = Decimal("0")
    collateral_kind: CollateralKind = CollateralKind.NONE
    legs: list[PositionLeg]
    raw: dict[str, Any] = Field(default_factory=dict)


class OptionContract(BaseModel):
    model_config = ConfigDict(frozen=True)

    occ_symbol: str
    underlying: str
    expiration_date: str
    strike: Decimal
    option_type: Literal["CALL", "PUT"]
    bid: Decimal | None = None
    ask: Decimal | None = None
    last: Decimal | None = None
    mark: Decimal | None = None
    implied_volatility: Decimal | None = None
    delta: Decimal | None = None
    gamma: Decimal | None = None
    theta: Decimal | None = None
    vega: Decimal | None = None
    rho: Decimal | None = None
    open_interest: int | None = None
    volume: int | None = None
    in_the_money: bool | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class OptionChain(BaseModel):
    model_config = ConfigDict(frozen=True)

    underlying: str
    quote_time: datetime
    underlying_mark: Decimal | None = None
    contracts: list[OptionContract]
    raw: dict[str, Any] = Field(default_factory=dict)


class OrderLeg(BaseModel):
    model_config = ConfigDict(frozen=True)

    instruction: str
    quantity: int
    instrument_symbol: str
    asset_type: Literal["OPTION", "EQUITY", "FUTURE"] = "OPTION"


class OrderRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    client_order_id: str
    strategy_type: StrategyType
    quantity: int
    price_limit: Decimal | None = None
    defined_risk: bool = True
    is_naked: bool = False
    required_collateral: Decimal = Decimal("0")
    collateral_kind: CollateralKind = CollateralKind.NONE
    max_loss: Decimal
    legs: list[OrderLeg]
    metadata: dict[str, Any] = Field(default_factory=dict)


class Fill(BaseModel):
    model_config = ConfigDict(frozen=True)

    broker_fill_id: str
    quantity: int
    price: Decimal
    occurred_at: datetime


class OrderResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    broker_order_id: str | None = None
    status: OrderStatus
    raw: dict[str, Any] = Field(default_factory=dict)
