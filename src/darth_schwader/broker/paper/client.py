from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Literal, Protocol

from darth_schwader.broker.base import BrokerCapabilities, BrokerClient
from darth_schwader.broker.exceptions import BrokerError, OrderRejectedError
from darth_schwader.broker.models import (
    Account,
    OptionChain,
    OrderLeg,
    OrderRequest,
    OrderResponse,
    Position,
    PositionLeg,
)
from darth_schwader.domain.enums import OrderStatus, StrategyType
from darth_schwader.logging import get_logger

from .fills import (
    BUY_INSTRUCTIONS,
    SUPPORTED_INSTRUCTIONS,
    FillSimulator,
    MarketSession,
)

SUPPORTED_ASSET_TYPES: frozenset[str] = frozenset({"OPTION", "EQUITY", "FUTURE"})

LONG_OPEN_INSTRUCTIONS: frozenset[str] = frozenset({"BUY", "BUY_TO_OPEN"})
SHORT_OPEN_INSTRUCTIONS: frozenset[str] = frozenset({"SELL_TO_OPEN"})
LONG_CLOSE_INSTRUCTIONS: frozenset[str] = frozenset({"SELL", "SELL_TO_CLOSE"})
SHORT_CLOSE_INSTRUCTIONS: frozenset[str] = frozenset({"BUY_TO_CLOSE"})

_OPTION_MULTIPLIER = Decimal("100")
_EQUITY_MULTIPLIER = Decimal("1")
_FUTURE_MULTIPLIER = Decimal("1")

_AVG_COST_QUANTUM = Decimal("0.0001")


def _quantize_avg_cost(value: Decimal) -> Decimal:
    return value.quantize(_AVG_COST_QUANTUM)


class PriceSource(Protocol):
    async def get_mark(self, symbol: str, asset_type: str) -> Decimal | None:
        ...


class StaticPriceSource:
    def __init__(self, prices: dict[str, Decimal]) -> None:
        self._prices = dict(prices)

    async def get_mark(self, symbol: str, asset_type: str) -> Decimal | None:
        del asset_type
        return self._prices.get(symbol)


@dataclass(frozen=True)
class _PaperPosition:
    symbol: str
    asset_type: str
    quantity: int
    avg_cost: Decimal
    realized_pnl: Decimal
    strategy_type: StrategyType


class PaperBrokerClient(BrokerClient):
    def __init__(
        self,
        *,
        starting_cash: Decimal,
        slippage_bps: int,
        session_penalty_bps: int,
        price_source: PriceSource,
        account_id: str = "PAPER-ACCOUNT",
        account_type: str = "CASH",
        session_provider: Callable[[], MarketSession] | None = None,
    ) -> None:
        self._account_id = account_id
        self._account_type = account_type
        self._cash = starting_cash
        self._orders: dict[str, OrderResponse] = {}
        self._positions: dict[tuple[str, str], _PaperPosition] = {}
        self._closed_realized_pnl: dict[tuple[str, str], Decimal] = {}
        self._order_counter = 0
        self._price_source = price_source
        self._fill_simulator = FillSimulator(
            slippage_bps=slippage_bps,
            session_penalty_bps=session_penalty_bps,
        )
        self._session_provider = session_provider or (lambda: MarketSession.REGULAR)
        self._lock = asyncio.Lock()
        self._logger = get_logger(__name__)

    async def get_accounts(self) -> list[Account]:
        async with self._lock:
            cash = self._cash
            position_snapshot = list(self._positions.values())
            open_realized = sum(
                (pos.realized_pnl for pos in position_snapshot), Decimal("0")
            )
            closed_realized = sum(self._closed_realized_pnl.values(), Decimal("0"))

        market_value = Decimal("0")
        for pos in position_snapshot:
            mark = await self._price_source.get_mark(pos.symbol, pos.asset_type)
            if mark is None:
                continue
            multiplier = self._multiplier_for(pos.asset_type)
            market_value += Decimal(pos.quantity) * multiplier * mark

        net_liquidation = cash + market_value
        total_realized = open_realized + closed_realized
        return [
            Account(
                broker_account_id=self._account_id,
                account_type=self._account_type,
                net_liquidation_value=net_liquidation,
                cash_balance=cash,
                buying_power=cash,
                raw={"broker": "paper", "realized_pnl": str(total_realized)},
            )
        ]

    async def get_positions(self, account_id: str) -> list[Position]:
        self._validate_account_id(account_id)
        async with self._lock:
            snapshot = list(self._positions.values())

        result: list[Position] = []
        for pos in snapshot:
            mark_price = await self._price_source.get_mark(pos.symbol, pos.asset_type)
            qty_abs = abs(pos.quantity)
            side: Literal["LONG", "SHORT"] = "LONG" if pos.quantity > 0 else "SHORT"
            current_mark = mark_price
            underlying = _underlying_from(pos.symbol, pos.asset_type)
            result.append(
                Position(
                    underlying=underlying,
                    strategy_type=pos.strategy_type,
                    quantity=qty_abs,
                    entry_cost=pos.avg_cost,
                    current_mark=current_mark,
                    max_loss=Decimal("0"),
                    defined_risk=True,
                    legs=[
                        PositionLeg(symbol=pos.symbol, quantity=qty_abs, side=side),
                    ],
                    raw={"realized_pnl": str(pos.realized_pnl), "broker": "paper"},
                )
            )
        return result

    async def get_chain(self, symbol: str) -> OptionChain:
        del symbol
        raise NotImplementedError(
            "PaperBrokerClient.get_chain is not supported in Phase A.1; "
            "wire a real MarketDataClient before calling.",
        )

    async def submit_order(self, account_id: str, request: OrderRequest) -> OrderResponse:
        self._validate_account_id(account_id)
        if not request.legs:
            raise OrderRejectedError("paper order must contain at least one leg")
        session = self._session_provider()

        async with self._lock:
            fills = []
            asset_types: list[str] = []
            cash_delta = Decimal("0")
            position_updates: list[tuple[tuple[str, str], _PaperPosition]] = []
            working_positions: dict[tuple[str, str], _PaperPosition] = dict(self._positions)

            for leg in request.legs:
                self._validate_leg(leg)
                position_key: tuple[str, str] = (leg.instrument_symbol, leg.asset_type)
                existing = working_positions.get(position_key)
                self._validate_position_intent(leg, existing)

                ref_price = await self._price_source.get_mark(
                    leg.instrument_symbol,
                    leg.asset_type,
                )
                if ref_price is None:
                    raise OrderRejectedError(
                        f"no paper price available for {leg.instrument_symbol}",
                    )
                fill = self._fill_simulator.simulate(leg, ref_price, session)
                fills.append(fill)
                asset_types.append(leg.asset_type)
                cash_delta += self._cash_effect(leg, fill.price)

                next_position = self._apply_fill_to_position(
                    leg,
                    fill.price,
                    existing,
                    request.strategy_type,
                )
                position_updates.append((position_key, next_position))
                working_positions[position_key] = next_position

            resulting_cash = self._cash + cash_delta
            if resulting_cash < Decimal("0"):
                raise OrderRejectedError("insufficient paper cash")

            self._cash = resulting_cash
            for update_key, update_position in position_updates:
                if update_position.quantity == 0:
                    prior = self._closed_realized_pnl.get(update_key, Decimal("0"))
                    self._closed_realized_pnl[update_key] = (
                        prior + update_position.realized_pnl
                    )
                    self._positions.pop(update_key, None)
                else:
                    self._positions[update_key] = update_position

            self._order_counter += 1
            broker_order_id = f"PAPER-{self._order_counter:08d}"
            response = OrderResponse(
                broker_order_id=broker_order_id,
                status=OrderStatus.FILLED,
                raw={
                    "simulated_fills": [fill.model_dump(mode="json") for fill in fills],
                    "session": session.value,
                    "asset_types": asset_types,
                },
            )
            self._orders[broker_order_id] = response
            self._logger.info(
                "paper_order_filled",
                broker_order_id=broker_order_id,
                client_order_id=request.client_order_id,
                cash_balance=str(self._cash),
                session=session.value,
                legs=len(request.legs),
            )
            return response

    async def get_order_status(self, account_id: str, broker_order_id: str) -> OrderResponse:
        self._validate_account_id(account_id)
        async with self._lock:
            response = self._orders.get(broker_order_id)
            if response is None:
                raise BrokerError(f"unknown paper order: {broker_order_id}")
            return response

    async def cancel_order(self, account_id: str, broker_order_id: str) -> None:
        self._validate_account_id(account_id)
        async with self._lock:
            if broker_order_id not in self._orders:
                raise BrokerError(f"unknown paper order: {broker_order_id}")
            raise BrokerError("cannot cancel filled paper order")

    async def capabilities(self) -> BrokerCapabilities:
        return BrokerCapabilities(
            supports_options=True,
            supports_equities=True,
            supports_futures=True,
            is_paper=True,
        )

    async def close(self) -> None:
        return None

    def _validate_account_id(self, account_id: str) -> None:
        if account_id != self._account_id:
            raise BrokerError(f"unknown paper account: {account_id}")

    def _validate_leg(self, leg: OrderLeg) -> None:
        if leg.asset_type not in SUPPORTED_ASSET_TYPES:
            raise OrderRejectedError(f"unsupported paper asset_type: {leg.asset_type}")
        if leg.instruction not in SUPPORTED_INSTRUCTIONS:
            raise OrderRejectedError(f"unsupported paper instruction: {leg.instruction}")

    def _validate_position_intent(
        self,
        leg: OrderLeg,
        existing: _PaperPosition | None,
    ) -> None:
        if leg.instruction in LONG_OPEN_INSTRUCTIONS:
            if existing is not None and existing.quantity < 0:
                raise OrderRejectedError(
                    f"existing short position in {leg.instrument_symbol}; "
                    "use BUY_TO_CLOSE before opening long",
                )
        elif leg.instruction in SHORT_OPEN_INSTRUCTIONS:
            if existing is not None and existing.quantity > 0:
                raise OrderRejectedError(
                    f"existing long position in {leg.instrument_symbol}; "
                    "use SELL_TO_CLOSE before opening short",
                )
        elif leg.instruction in LONG_CLOSE_INSTRUCTIONS:
            if existing is None or existing.quantity <= 0:
                raise OrderRejectedError(
                    f"no long position to close in {leg.instrument_symbol}",
                )
            if leg.quantity > existing.quantity:
                raise OrderRejectedError(
                    f"insufficient long position in {leg.instrument_symbol}: "
                    f"have {existing.quantity}, trying to close {leg.quantity}",
                )
        elif leg.instruction in SHORT_CLOSE_INSTRUCTIONS:
            if existing is None or existing.quantity >= 0:
                raise OrderRejectedError(
                    f"no short position to close in {leg.instrument_symbol}",
                )
            if leg.quantity > abs(existing.quantity):
                raise OrderRejectedError(
                    f"insufficient short position in {leg.instrument_symbol}: "
                    f"have {abs(existing.quantity)}, trying to cover {leg.quantity}",
                )

    def _apply_fill_to_position(
        self,
        leg: OrderLeg,
        fill_price: Decimal,
        existing: _PaperPosition | None,
        strategy_type: StrategyType,
    ) -> _PaperPosition:
        if leg.instruction in LONG_OPEN_INSTRUCTIONS:
            if existing is None or existing.quantity == 0:
                return _PaperPosition(
                    symbol=leg.instrument_symbol,
                    asset_type=leg.asset_type,
                    quantity=leg.quantity,
                    avg_cost=_quantize_avg_cost(fill_price),
                    realized_pnl=Decimal("0"),
                    strategy_type=strategy_type,
                )
            new_qty = existing.quantity + leg.quantity
            new_avg = _quantize_avg_cost(
                (
                    Decimal(existing.quantity) * existing.avg_cost
                    + Decimal(leg.quantity) * fill_price
                )
                / Decimal(new_qty)
            )
            return replace(existing, quantity=new_qty, avg_cost=new_avg)

        if leg.instruction in SHORT_OPEN_INSTRUCTIONS:
            if existing is None or existing.quantity == 0:
                return _PaperPosition(
                    symbol=leg.instrument_symbol,
                    asset_type=leg.asset_type,
                    quantity=-leg.quantity,
                    avg_cost=_quantize_avg_cost(fill_price),
                    realized_pnl=Decimal("0"),
                    strategy_type=strategy_type,
                )
            existing_abs = abs(existing.quantity)
            new_abs = existing_abs + leg.quantity
            new_avg = _quantize_avg_cost(
                (
                    Decimal(existing_abs) * existing.avg_cost
                    + Decimal(leg.quantity) * fill_price
                )
                / Decimal(new_abs)
            )
            return replace(existing, quantity=-new_abs, avg_cost=new_avg)

        multiplier = self._multiplier_for(leg.asset_type)
        if leg.instruction in LONG_CLOSE_INSTRUCTIONS:
            assert existing is not None
            new_qty = existing.quantity - leg.quantity
            realized = (
                (fill_price - existing.avg_cost) * Decimal(leg.quantity) * multiplier
            )
            new_realized = existing.realized_pnl + realized
            return replace(existing, quantity=new_qty, realized_pnl=new_realized)

        if leg.instruction in SHORT_CLOSE_INSTRUCTIONS:
            assert existing is not None
            new_qty = existing.quantity + leg.quantity
            realized = (
                (existing.avg_cost - fill_price) * Decimal(leg.quantity) * multiplier
            )
            new_realized = existing.realized_pnl + realized
            return replace(existing, quantity=new_qty, realized_pnl=new_realized)

        raise OrderRejectedError(f"unsupported paper instruction: {leg.instruction}")

    def _cash_effect(self, leg: OrderLeg, fill_price: Decimal) -> Decimal:
        multiplier = self._multiplier_for(leg.asset_type)
        gross = Decimal(leg.quantity) * multiplier * fill_price
        if leg.instruction in BUY_INSTRUCTIONS:
            return -gross
        return gross

    def _multiplier_for(self, asset_type: str) -> Decimal:
        if asset_type == "OPTION":
            return _OPTION_MULTIPLIER
        if asset_type == "FUTURE":
            return _FUTURE_MULTIPLIER
        return _EQUITY_MULTIPLIER


def _underlying_from(symbol: str, asset_type: str) -> str:
    if asset_type == "OPTION":
        root = symbol.split(maxsplit=1)[0] if " " in symbol else symbol
        return root.strip()
    return symbol


__all__ = [
    "LONG_CLOSE_INSTRUCTIONS",
    "LONG_OPEN_INSTRUCTIONS",
    "SHORT_CLOSE_INSTRUCTIONS",
    "SHORT_OPEN_INSTRUCTIONS",
    "SUPPORTED_ASSET_TYPES",
    "PaperBrokerClient",
    "PriceSource",
    "StaticPriceSource",
]
