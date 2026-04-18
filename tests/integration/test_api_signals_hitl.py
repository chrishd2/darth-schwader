from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select

from darth_schwader.broker.cash_account import CashAccountGuard
from darth_schwader.broker.schwab.client import SchwabApiClient
from darth_schwader.broker.schwab.endpoints import ORDERS_URL
from darth_schwader.db.models import Account, AccountSnapshot, ChainSnapshot, Order, RiskEvent, Signal
from darth_schwader.db.repositories.cash_ledger import CashLedgerRepository
from darth_schwader.db.repositories.tokens import TokenRepository
from darth_schwader.domain.enums import AccountType, CashLedgerReason, SignalStatus, StrategyType
from darth_schwader.risk.engine import RiskEngine
from darth_schwader.services.order_service import OrderService


@pytest.mark.asyncio
async def test_signal_submit_transitions_to_executed_and_is_not_idempotent(
    make_app,
    settings,
    session_factory,
    session,
    respx_mock,
) -> None:
    account = Account(
        broker_account_id=settings.schwab_account_number,
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
            net_liquidation_value=Decimal("10000"),
            cash_balance=Decimal("10000"),
            buying_power=Decimal("10000"),
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
            expiration_date=(datetime.now(tz=UTC) + timedelta(days=30)).date(),
            option_type="CALL",
            strike=Decimal("195"),
            bid=Decimal("1.00"),
            ask=Decimal("1.10"),
            last=Decimal("1.05"),
            mark=Decimal("1.05"),
            implied_volatility=Decimal("0.25"),
            delta=Decimal("0.30"),
            gamma=Decimal("0.02"),
            theta=Decimal("-0.01"),
            vega=Decimal("0.05"),
            rho=Decimal("0.01"),
            open_interest=100,
            volume=25,
            in_the_money=False,
            data_source="SCHWAB",
            raw_payload={"source": "test"},
        )
    )
    signal = Signal(
        signal_id="sig-hitl",
        source="MANUAL",
        strategy_type=StrategyType.VERTICAL_SPREAD,
        underlying="AAPL",
        expiration_date=(datetime.now(tz=UTC) + timedelta(days=30)).date(),
        direction="bullish",
        thesis="submit me",
        confidence=Decimal("0.9"),
        proposed_payload={
            "legs": [
                {
                    "occ_symbol": "AAPL  260619C00195000",
                    "side": "LONG",
                    "quantity": 1,
                    "strike": "195",
                    "expiration": (datetime.now(tz=UTC) + timedelta(days=30)).date().isoformat(),
                    "option_type": "CALL",
                }
            ],
            "features_snapshot": {
                "per_contract_max_loss": "100",
                "required_collateral_per_contract": "100",
            },
        },
        suggested_quantity=1,
        suggested_max_loss=Decimal("100"),
        preferred_quantity=1,
        ceiling_quantity=25,
        status=SignalStatus.APPROVED_AWAITING_HITL,
    )
    session.add(signal)
    await session.commit()
    await session.refresh(signal)

    cash_repo = CashLedgerRepository(session_factory)
    await cash_repo.append_delta(
        account.id,
        Decimal("5000"),
        CashLedgerReason.MANUAL_ADJUSTMENT,
        datetime.now(tz=UTC).date(),
    )

    token_repo = TokenRepository(session_factory, settings)
    await token_repo.upsert_tokens(
        provider="schwab",
        access_token=SecretStr("access-token"),
        refresh_token=SecretStr("refresh-token"),
        access_token_expires_at=datetime.now(tz=UTC) + timedelta(minutes=30),
        refresh_token_expires_at=datetime.now(tz=UTC) + timedelta(days=7),
    )

    respx_mock.post(ORDERS_URL.format(account_id=settings.schwab_account_number)).mock(
        return_value=httpx.Response(200, json={"orderId": "broker-123", "status": "SUBMITTED"})
    )

    broker = SchwabApiClient(settings, token_repo, client=httpx.AsyncClient())
    app = make_app()
    app.state.broker = broker
    app.state.order_service = OrderService(RiskEngine(), CashAccountGuard(cash_repo))

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.post(f"/api/v1/signals/{signal.id}/submit", json={"override_quantity": 2})
            assert response.status_code == 200

            second = await client.post(f"/api/v1/signals/{signal.id}/submit", json={"override_quantity": 2})
            assert second.status_code == 422

        async with session_factory() as verify:
            refreshed_signal = await verify.get(Signal, signal.id)
            order = await verify.scalar(select(Order).where(Order.signal_id == signal.id))
            risk_event = await verify.scalar(select(RiskEvent).where(RiskEvent.signal_id == signal.id))

        assert refreshed_signal is not None
        assert refreshed_signal.status == SignalStatus.EXECUTED
        assert risk_event is not None
        assert order is not None
        assert order.risk_event_id == risk_event.id
        assert order.client_order_id
        assert risk_event.approved_quantity == 2
        assert order.quantity == 2
    finally:
        await broker.close()
