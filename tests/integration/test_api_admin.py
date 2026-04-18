from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from darth_schwader.api.routers import admin as admin_module
from darth_schwader.db.models import Account, AuditLog, ConfigRef, Order, RiskEvent, Signal
from darth_schwader.domain.enums import (
    AccountType,
    CollateralKind,
    OrderStatus,
    SignalStatus,
    StrategyType,
)


class _RecordingPaperBroker:
    def __init__(self) -> None:
        self.cancel_calls: list[tuple[str, str]] = []

    async def cancel_order(self, account_id: str, broker_order_id: str) -> None:
        self.cancel_calls.append((account_id, broker_order_id))


async def _seed_account_and_order(
    session_factory,
    *,
    broker_order_id: str | None,
    status: OrderStatus,
) -> tuple[int, str]:
    async with session_factory() as session:
        account = await session.scalar(
            select(Account).where(Account.broker_account_id == "123456789")
        )
        if account is None:
            account = Account(
                broker_account_id="123456789",
                account_type=AccountType.MARGIN,
                options_approval_tier=2,
            )
            session.add(account)
            await session.flush()

        signal = Signal(
            signal_id=f"sig-{status.value}",
            source="AI",
            strategy_type=StrategyType.VERTICAL_SPREAD,
            underlying="AAPL",
            expiration_date=(datetime.now(tz=UTC) + timedelta(days=30)).date(),
            direction="bullish",
            thesis="test",
            confidence=Decimal("0.6"),
            proposed_payload={"legs": [], "features_snapshot": {}},
            suggested_quantity=1,
            suggested_max_loss=Decimal("100"),
            preferred_quantity=1,
            ceiling_quantity=2,
            status=SignalStatus.APPROVED_AWAITING_HITL,
        )
        session.add(signal)
        await session.flush()

        risk_event = RiskEvent(
            signal_id=signal.id,
            account_id=account.id,
            decision="APPROVE",
            reason_code="OK",
            reason_text="seeded for test",
            rule_results_json={},
        )
        session.add(risk_event)
        await session.flush()

        client_order_id = f"coid-{status.value}"
        order = Order(
            account_id=account.id,
            signal_id=signal.id,
            risk_event_id=risk_event.id,
            broker_order_id=broker_order_id,
            client_order_id=client_order_id,
            strategy_type=StrategyType.VERTICAL_SPREAD,
            underlying="AAPL",
            order_status=status,
            intent="OPEN",
            price_limit=None,
            quantity=1,
            defined_risk=True,
            is_naked=False,
            required_collateral=0,
            collateral_kind=CollateralKind.NONE,
            max_loss=0,
            order_payload={},
            submitted_at=datetime.now(tz=UTC),
        )
        session.add(order)
        await session.commit()
        return order.id, client_order_id


@pytest.mark.asyncio
async def test_panic_requires_confirm_header(make_app) -> None:
    app = make_app()
    app.state.broker = _RecordingPaperBroker()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/api/v1/admin/panic")
    assert response.status_code == 400
    assert "STOP" in response.json()["detail"]


@pytest.mark.asyncio
async def test_panic_halts_and_cancels_open_orders(make_app, session_factory) -> None:
    order_id, client_order_id = await _seed_account_and_order(
        session_factory, broker_order_id="broker-1", status=OrderStatus.WORKING
    )
    naked_order_id, naked_coid = await _seed_account_and_order(
        session_factory, broker_order_id=None, status=OrderStatus.PENDING_SUBMISSION
    )

    broker = _RecordingPaperBroker()
    app = make_app()
    app.state.broker = broker

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/v1/admin/panic",
            headers={"X-Confirm": "STOP", "X-Actor": "test-operator"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "HALTED"
    assert set(body["cancelled_orders"]) == {client_order_id, naked_coid}
    assert body["errors"] == []
    assert broker.cancel_calls == [("123456789", "broker-1")]

    async with session_factory() as session:
        refreshed = await session.get(Order, order_id)
        naked_refreshed = await session.get(Order, naked_order_id)
        bot_state = await session.get(ConfigRef, "bot_state")
        audit = await session.scalar(
            select(AuditLog).where(AuditLog.event_type == "PANIC")
        )

    assert refreshed is not None and refreshed.order_status == OrderStatus.CANCELLED
    assert naked_refreshed is not None and naked_refreshed.order_status == OrderStatus.CANCELLED
    assert bot_state is not None and bot_state.value == "HALTED"
    assert audit is not None
    assert audit.payload_json["actor"] == "test-operator"
    assert set(audit.payload_json["cancelled"]) == {client_order_id, naked_coid}


@pytest.mark.asyncio
async def test_panic_records_broker_errors_without_aborting(make_app, session_factory) -> None:
    order_id, client_order_id = await _seed_account_and_order(
        session_factory, broker_order_id="broker-42", status=OrderStatus.WORKING
    )

    class _FailingBroker:
        async def cancel_order(self, account_id: str, broker_order_id: str) -> None:
            raise RuntimeError("broker unreachable")

    app = make_app()
    app.state.broker = _FailingBroker()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/api/v1/admin/panic", headers={"X-Confirm": "STOP"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "HALTED"
    assert body["cancelled_orders"] == []
    assert len(body["errors"]) == 1
    assert body["errors"][0]["client_order_id"] == client_order_id
    assert "broker unreachable" in body["errors"][0]["error"]

    async with session_factory() as session:
        refreshed = await session.get(Order, order_id)
    assert refreshed is not None
    assert refreshed.order_status == OrderStatus.WORKING


@pytest.mark.asyncio
async def test_run_ai_now_returns_503_when_signal_runner_missing(make_app) -> None:
    app = make_app()
    if hasattr(app.state, "signal_runner"):
        del app.state.signal_runner
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/api/v1/admin/run-ai-now")
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_run_ai_now_invokes_signal_runner_with_manual_reason(make_app) -> None:
    received: list[str] = []

    async def fake_runner(reason: str) -> int:
        received.append(reason)
        return 3

    admin_module._run_ai_limiter._last_call = 0.0

    app = make_app()
    app.state.signal_runner = fake_runner

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post("/api/v1/admin/run-ai-now")

    assert response.status_code == 200
    assert received == ["MANUAL"]
    body = response.json()
    assert body == {"status": "ok", "reason": "MANUAL", "signals_generated": 3}


@pytest.mark.asyncio
async def test_run_ai_now_rate_limits_second_call_within_cooldown(make_app) -> None:
    call_count = 0

    async def fake_runner(reason: str) -> int:
        nonlocal call_count
        call_count += 1
        return 0

    admin_module._run_ai_limiter._last_call = 0.0
    app = make_app()
    app.state.signal_runner = fake_runner

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        first = await client.post("/api/v1/admin/run-ai-now")
        second = await client.post("/api/v1/admin/run-ai-now")

    assert first.status_code == 200
    assert second.status_code == 429
    assert "retry" in second.json()["detail"].lower()
    assert call_count == 1


_ = (Callable, Awaitable, date)
