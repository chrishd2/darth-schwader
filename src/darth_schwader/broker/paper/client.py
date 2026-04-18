from __future__ import annotations

import asyncio
from collections.abc import Callable
from decimal import Decimal
from typing import Protocol

from darth_schwader.broker.base import BrokerCapabilities, BrokerClient
from darth_schwader.broker.exceptions import BrokerError, OrderRejectedError
from darth_schwader.broker.models import (
    Account,
    OptionChain,
    OrderLeg,
    OrderRequest,
    OrderResponse,
    Position,
)
from darth_schwader.domain.enums import OrderStatus
from darth_schwader.logging import get_logger

from .fills import (
    BUY_INSTRUCTIONS,
    SUPPORTED_INSTRUCTIONS,
    FillSimulator,
    MarketSession,
)

SUPPORTED_ASSET_TYPES: frozenset[str] = frozenset({"OPTION", "EQUITY", "FUTURE"})

_OPTION_MULTIPLIER = Decimal("100")
_EQUITY_MULTIPLIER = Decimal("1")
_FUTURE_MULTIPLIER = Decimal("1")


class PriceSource(Protocol):
    async def get_mark(self, symbol: str, asset_type: str) -> Decimal | None:
        ...


class StaticPriceSource:
    def __init__(self, prices: dict[str, Decimal]) -> None:
        self._prices = dict(prices)

    async def get_mark(self, symbol: str, asset_type: str) -> Decimal | None:
        del asset_type
        return self._prices.get(symbol)


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
            return [
                Account(
                    broker_account_id=self._account_id,
                    account_type=self._account_type,
                    net_liquidation_value=self._cash,
                    cash_balance=self._cash,
                    buying_power=self._cash,
                    raw={"broker": "paper"},
                )
            ]

    async def get_positions(self, account_id: str) -> list[Position]:
        self._validate_account_id(account_id)
        return []

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
            for leg in request.legs:
                self._validate_leg(leg)
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

            resulting_cash = self._cash + cash_delta
            if resulting_cash < Decimal("0"):
                raise OrderRejectedError("insufficient paper cash")

            self._cash = resulting_cash
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


__all__ = ["SUPPORTED_ASSET_TYPES", "PaperBrokerClient", "PriceSource", "StaticPriceSource"]
