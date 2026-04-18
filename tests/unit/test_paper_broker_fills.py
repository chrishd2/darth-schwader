from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

import pytest

from darth_schwader.broker.exceptions import BrokerError, OrderRejectedError
from darth_schwader.broker.models import OrderLeg, OrderRequest
from darth_schwader.broker.paper import (
    FillSimulator,
    MarketSession,
    PaperBrokerClient,
    StaticPriceSource,
)
from darth_schwader.domain.enums import OrderStatus, StrategyType


def _leg(
    *,
    instruction: str,
    symbol: str = "AAPL  260619C00195000",
    quantity: int = 1,
    asset_type: Literal["OPTION", "EQUITY", "FUTURE"] = "OPTION",
) -> OrderLeg:
    return OrderLeg(
        instruction=instruction,
        quantity=quantity,
        instrument_symbol=symbol,
        asset_type=asset_type,
    )


def _order(leg: OrderLeg, *, client_order_id: str = "client-1") -> OrderRequest:
    return OrderRequest(
        client_order_id=client_order_id,
        strategy_type=StrategyType.DEFINED_RISK_DIRECTIONAL,
        quantity=leg.quantity,
        max_loss=Decimal("500"),
        legs=[leg],
    )


def test_fill_simulator_applies_positive_slippage_on_buy() -> None:
    simulator = FillSimulator(slippage_bps=10, session_penalty_bps=0)
    fill = simulator.simulate(
        _leg(instruction="BUY_TO_OPEN"),
        ref_price=Decimal("10.00"),
        session=MarketSession.REGULAR,
        now=datetime(2026, 4, 18, 14, tzinfo=UTC),
    )
    assert fill.price == Decimal("10.01")


def test_fill_simulator_applies_negative_slippage_on_sell() -> None:
    simulator = FillSimulator(slippage_bps=10, session_penalty_bps=0)
    fill = simulator.simulate(
        _leg(instruction="SELL_TO_OPEN"),
        ref_price=Decimal("10.00"),
        session=MarketSession.REGULAR,
        now=datetime(2026, 4, 18, 14, tzinfo=UTC),
    )
    assert fill.price == Decimal("9.99")


def test_fill_simulator_adds_session_penalty_outside_regular_hours() -> None:
    simulator = FillSimulator(slippage_bps=10, session_penalty_bps=20)
    fill = simulator.simulate(
        _leg(instruction="BUY_TO_OPEN"),
        ref_price=Decimal("10.00"),
        session=MarketSession.PREMARKET,
        now=datetime(2026, 4, 18, 9, tzinfo=UTC),
    )
    assert fill.price == Decimal("10.03")


def test_fill_simulator_rejects_unknown_instruction() -> None:
    simulator = FillSimulator(slippage_bps=0, session_penalty_bps=0)
    leg = OrderLeg.model_construct(
        instruction="UNKNOWN",
        quantity=1,
        instrument_symbol="AAPL",
        asset_type="EQUITY",
    )
    with pytest.raises(ValueError, match="unsupported fill instruction"):
        simulator.simulate(leg, Decimal("10.00"), MarketSession.REGULAR)


@pytest.mark.asyncio
async def test_paper_broker_buy_option_debits_cash_with_multiplier() -> None:
    client = PaperBrokerClient(
        starting_cash=Decimal("10000"),
        slippage_bps=0,
        session_penalty_bps=0,
        price_source=StaticPriceSource({"AAPL  260619C00195000": Decimal("2.50")}),
    )
    request = _order(_leg(instruction="BUY_TO_OPEN", quantity=2))

    response = await client.submit_order("PAPER-ACCOUNT", request)

    assert response.status is OrderStatus.FILLED
    assert response.broker_order_id == "PAPER-00000001"
    accounts = await client.get_accounts()
    assert accounts[0].cash_balance == Decimal("9500.00")


@pytest.mark.asyncio
async def test_paper_broker_equity_buy_then_sell_round_trip_is_cash_neutral() -> None:
    client = PaperBrokerClient(
        starting_cash=Decimal("1000"),
        slippage_bps=0,
        session_penalty_bps=0,
        price_source=StaticPriceSource({"AAPL": Decimal("150.00")}),
    )

    buy = await client.submit_order(
        "PAPER-ACCOUNT",
        _order(
            _leg(instruction="BUY", symbol="AAPL", quantity=3, asset_type="EQUITY"),
            client_order_id="buy-1",
        ),
    )
    sell = await client.submit_order(
        "PAPER-ACCOUNT",
        _order(
            _leg(instruction="SELL", symbol="AAPL", quantity=3, asset_type="EQUITY"),
            client_order_id="sell-1",
        ),
    )

    assert buy.status is OrderStatus.FILLED
    assert sell.status is OrderStatus.FILLED
    accounts = await client.get_accounts()
    assert accounts[0].cash_balance == Decimal("1000.00")


@pytest.mark.asyncio
async def test_paper_broker_rejects_without_price() -> None:
    client = PaperBrokerClient(
        starting_cash=Decimal("10000"),
        slippage_bps=0,
        session_penalty_bps=0,
        price_source=StaticPriceSource({}),
    )
    request = _order(_leg(instruction="BUY_TO_OPEN"))

    with pytest.raises(OrderRejectedError, match="no paper price"):
        await client.submit_order("PAPER-ACCOUNT", request)


@pytest.mark.asyncio
async def test_paper_broker_rejects_insufficient_cash() -> None:
    client = PaperBrokerClient(
        starting_cash=Decimal("100"),
        slippage_bps=0,
        session_penalty_bps=0,
        price_source=StaticPriceSource({"AAPL  260619C00195000": Decimal("5.00")}),
    )
    request = _order(_leg(instruction="BUY_TO_OPEN"))

    with pytest.raises(OrderRejectedError, match="insufficient paper cash"):
        await client.submit_order("PAPER-ACCOUNT", request)


@pytest.mark.asyncio
async def test_paper_broker_rejects_unsupported_asset_type() -> None:
    client = PaperBrokerClient(
        starting_cash=Decimal("10000"),
        slippage_bps=0,
        session_penalty_bps=0,
        price_source=StaticPriceSource({"AAPL": Decimal("150.00")}),
    )
    leg = OrderLeg.model_construct(
        instruction="BUY",
        quantity=1,
        instrument_symbol="AAPL",
        asset_type="CRYPTO",
    )
    request = _order(leg)

    with pytest.raises(OrderRejectedError, match="unsupported paper asset_type"):
        await client.submit_order("PAPER-ACCOUNT", request)


@pytest.mark.asyncio
async def test_paper_broker_get_order_status_returns_cached_response() -> None:
    client = PaperBrokerClient(
        starting_cash=Decimal("10000"),
        slippage_bps=0,
        session_penalty_bps=0,
        price_source=StaticPriceSource({"AAPL  260619C00195000": Decimal("2.50")}),
    )
    request = _order(_leg(instruction="BUY_TO_OPEN"))
    submitted = await client.submit_order("PAPER-ACCOUNT", request)
    assert submitted.broker_order_id is not None

    fetched = await client.get_order_status("PAPER-ACCOUNT", submitted.broker_order_id)

    assert fetched == submitted


@pytest.mark.asyncio
async def test_paper_broker_cancel_order_raises_on_filled() -> None:
    client = PaperBrokerClient(
        starting_cash=Decimal("10000"),
        slippage_bps=0,
        session_penalty_bps=0,
        price_source=StaticPriceSource({"AAPL  260619C00195000": Decimal("2.50")}),
    )
    submitted = await client.submit_order(
        "PAPER-ACCOUNT", _order(_leg(instruction="BUY_TO_OPEN"))
    )
    assert submitted.broker_order_id is not None

    with pytest.raises(BrokerError, match="cannot cancel filled paper order"):
        await client.cancel_order("PAPER-ACCOUNT", submitted.broker_order_id)


@pytest.mark.asyncio
async def test_paper_broker_rejects_empty_legs() -> None:
    client = PaperBrokerClient(
        starting_cash=Decimal("1000"),
        slippage_bps=0,
        session_penalty_bps=0,
        price_source=StaticPriceSource({}),
    )
    empty = OrderRequest(
        client_order_id="empty-1",
        strategy_type=StrategyType.DEFINED_RISK_DIRECTIONAL,
        quantity=0,
        max_loss=Decimal("0"),
        legs=[],
    )

    with pytest.raises(OrderRejectedError, match="at least one leg"):
        await client.submit_order("PAPER-ACCOUNT", empty)


@pytest.mark.asyncio
async def test_paper_broker_get_order_status_unknown_order_raises() -> None:
    client = PaperBrokerClient(
        starting_cash=Decimal("10000"),
        slippage_bps=0,
        session_penalty_bps=0,
        price_source=StaticPriceSource({}),
    )

    with pytest.raises(BrokerError, match="unknown paper order"):
        await client.get_order_status("PAPER-ACCOUNT", "PAPER-DOES-NOT-EXIST")


@pytest.mark.asyncio
async def test_paper_broker_capabilities_flag_is_paper() -> None:
    client = PaperBrokerClient(
        starting_cash=Decimal("10000"),
        slippage_bps=0,
        session_penalty_bps=0,
        price_source=StaticPriceSource({}),
    )

    caps = await client.capabilities()

    assert caps.is_paper is True
    assert caps.supports_options is True
    assert caps.supports_equities is True
    assert caps.supports_futures is True
