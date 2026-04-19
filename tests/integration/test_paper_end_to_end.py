from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from darth_schwader.broker.cash_account import CashAccountGuard
from darth_schwader.broker.paper import PaperBrokerClient, StaticPriceSource
from darth_schwader.db.models import (
    Account,
    AccountSnapshot,
    ChainSnapshot,
    Fill,
    Order,
    Position,
    RiskEvent,
    Signal,
)
from darth_schwader.db.repositories.cash_ledger import CashLedgerRepository
from darth_schwader.domain.enums import (
    AccountType,
    CashLedgerReason,
    OrderStatus,
    SignalStatus,
    StrategyType,
)
from darth_schwader.risk.engine import RiskEngine
from darth_schwader.services.account_sync import AccountSyncService
from darth_schwader.services.order_service import OrderService


_PAPER_ACCOUNT_ID = "PAPER-TEST-001"
_OCC_SYMBOL = "AAPL  260619C00195000"
_REF_PRICE = Decimal("2.00")
_STARTING_CASH = Decimal("50000")


@pytest.mark.asyncio
async def test_paper_signal_fills_and_dashboard_reflects_position(
    make_app,
    settings,
    session_factory,
    session,
) -> None:
    expiration = (datetime.now(tz=UTC) + timedelta(days=30)).date()

    account = Account(
        broker_account_id=_PAPER_ACCOUNT_ID,
        account_type=AccountType.CASH,
        options_approval_tier=3,
    )
    session.add(account)
    await session.commit()
    await session.refresh(account)

    session.add(
        AccountSnapshot(
            account_id=account.id,
            as_of=datetime.now(tz=UTC),
            net_liquidation_value=_STARTING_CASH,
            cash_balance=_STARTING_CASH,
            buying_power=_STARTING_CASH,
            maintenance_requirement=Decimal("0"),
            day_pnl=Decimal("0"),
            week_pnl=Decimal("0"),
            raw_payload={"source": "test"},
        )
    )
    session.add(
        ChainSnapshot(
            underlying="AAPL",
            quote_time=datetime.now(tz=UTC),
            expiration_date=expiration,
            option_type="CALL",
            strike=Decimal("195"),
            bid=Decimal("1.95"),
            ask=Decimal("2.05"),
            last=Decimal("2.00"),
            mark=Decimal("2.00"),
            implied_volatility=Decimal("0.25"),
            delta=Decimal("0.45"),
            gamma=Decimal("0.02"),
            theta=Decimal("-0.01"),
            vega=Decimal("0.05"),
            rho=Decimal("0.01"),
            open_interest=500,
            volume=100,
            in_the_money=False,
            data_source="SCHWAB",
            raw_payload={"source": "test"},
        )
    )
    signal = Signal(
        signal_id="sig-paper-e2e",
        source="AI",
        strategy_type=StrategyType.DEFINED_RISK_DIRECTIONAL,
        underlying="AAPL",
        expiration_date=expiration,
        direction="bullish",
        thesis="paper end-to-end",
        confidence=Decimal("0.9"),
        proposed_payload={
            "legs": [
                {
                    "occ_symbol": _OCC_SYMBOL,
                    "side": "LONG",
                    "quantity": 1,
                    "strike": "195",
                    "expiration": expiration.isoformat(),
                    "option_type": "CALL",
                }
            ],
            "features_snapshot": {
                "per_contract_max_loss": "200",
                "required_collateral_per_contract": "200",
            },
        },
        suggested_quantity=1,
        suggested_max_loss=Decimal("200"),
        preferred_quantity=1,
        ceiling_quantity=10,
        status=SignalStatus.APPROVED_AWAITING_HITL,
    )
    session.add(signal)
    await session.commit()
    await session.refresh(signal)

    cash_repo = CashLedgerRepository(session_factory)
    await cash_repo.append_delta(
        account.id,
        _STARTING_CASH,
        CashLedgerReason.MANUAL_ADJUSTMENT,
        datetime.now(tz=UTC).date(),
    )

    broker = PaperBrokerClient(
        starting_cash=_STARTING_CASH,
        slippage_bps=settings.paper_slippage_bps,
        session_penalty_bps=settings.paper_session_penalty_bps,
        price_source=StaticPriceSource({_OCC_SYMBOL: _REF_PRICE}),
        account_id=_PAPER_ACCOUNT_ID,
        account_type=AccountType.CASH,
    )

    app = make_app()
    app.state.broker = broker
    app.state.order_service = OrderService(RiskEngine(), CashAccountGuard(cash_repo))

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            submit_response = await client.post(
                f"/api/v1/signals/{signal.id}/submit",
                json={},
            )
            assert submit_response.status_code == 200, submit_response.text
            submit_body = submit_response.json()
            assert submit_body["status"] == OrderStatus.FILLED

            await AccountSyncService(session_factory, broker).run()

            positions_response = await client.get("/api/v1/positions")
            assert positions_response.status_code == 200
            positions_payload = positions_response.json()
            assert len(positions_payload) == 1
            position_row = positions_payload[0]
            assert position_row["underlying"] == "AAPL"
            assert position_row["strategy_type"] == StrategyType.DEFINED_RISK_DIRECTIONAL
            assert position_row["quantity"] == 1
            assert Decimal(position_row["entry_cost"]) == _REF_PRICE
            assert position_row["status"] == "OPEN"

            broker_accounts_response = await client.get("/api/v1/broker/accounts")
            assert broker_accounts_response.status_code == 200
            broker_accounts_payload = broker_accounts_response.json()
            assert len(broker_accounts_payload) == 1
            broker_account = broker_accounts_payload[0]
            assert broker_account["broker_account_id"] == _PAPER_ACCOUNT_ID
            expected_cash_balance = _STARTING_CASH - (_REF_PRICE * Decimal("100"))
            assert Decimal(broker_account["cash_balance"]) == expected_cash_balance
            expected_market_value = _REF_PRICE * Decimal("100")
            assert (
                Decimal(broker_account["net_liquidation_value"])
                == expected_cash_balance + expected_market_value
            )

        async with session_factory() as verify:
            refreshed_signal = await verify.get(Signal, signal.id)
            order = await verify.scalar(select(Order).where(Order.signal_id == signal.id))
            risk_event = await verify.scalar(
                select(RiskEvent).where(RiskEvent.signal_id == signal.id)
            )
            fill = (
                await verify.scalar(select(Fill).where(Fill.order_id == order.id))
                if order is not None
                else None
            )
            persisted_position = await verify.scalar(
                select(Position).where(
                    Position.account_id == account.id,
                    Position.underlying == "AAPL",
                )
            )

        assert refreshed_signal is not None
        assert refreshed_signal.status == SignalStatus.EXECUTED
        assert order is not None
        assert order.order_status == OrderStatus.FILLED
        assert order.broker_order_id is not None
        assert order.broker_order_id.startswith("PAPER-")
        assert order.quantity == 1
        assert risk_event is not None
        assert order.risk_event_id == risk_event.id
        assert risk_event.approved_quantity == 1
        assert fill is None
        assert persisted_position is not None
        assert persisted_position.status == "OPEN"
        assert persisted_position.quantity == 1
    finally:
        await broker.close()
