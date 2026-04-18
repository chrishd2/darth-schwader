from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from darth_schwader.api.deps import get_session
from darth_schwader.broker.base import BrokerClient
from darth_schwader.db.models import Account, AuditLog, ConfigRef, Order
from darth_schwader.domain.enums import OrderStatus
from darth_schwader.logging import get_logger
from darth_schwader.services.reconciliation import reconcile_end_of_day

router = APIRouter(tags=["admin"])

_logger = get_logger(__name__)

_RUN_AI_COOLDOWN_SECONDS = 60.0
_CANCELLABLE_ORDER_STATUSES = (
    OrderStatus.PENDING_SUBMISSION,
    OrderStatus.SUBMITTED,
    OrderStatus.WORKING,
    OrderStatus.PARTIALLY_FILLED,
)


class _RateLimiter:
    def __init__(self, cooldown_seconds: float) -> None:
        self._cooldown = cooldown_seconds
        self._last_call: float = 0.0
        self._lock = asyncio.Lock()

    async def check_and_record(self) -> float:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call
            if elapsed < self._cooldown:
                return self._cooldown - elapsed
            self._last_call = now
            return 0.0


_run_ai_limiter = _RateLimiter(_RUN_AI_COOLDOWN_SECONDS)


async def _resolve_broker_account_id(
    broker: BrokerClient, session: AsyncSession
) -> str | None:
    try:
        accounts = await broker.get_accounts()
    except Exception as exc:
        _logger.warning("panic_broker_get_accounts_failed", error=str(exc))
        accounts = []
    if accounts:
        return accounts[0].broker_account_id
    account = await session.scalar(select(Account).limit(1))
    if account is not None:
        return account.broker_account_id
    return None


@router.post("/admin/reconcile")
async def reconcile(request: Request) -> dict[str, str]:
    await reconcile_end_of_day(request.app.state.session_factory)
    request.app.state.last_scheduler_run = "reconcile"
    return {"status": "ok"}


@router.post("/admin/halt")
async def halt(
    request: Request, session: AsyncSession = Depends(get_session)
) -> dict[str, str]:
    row = await session.get(ConfigRef, "bot_state")
    if row is None:
        row = ConfigRef(key="bot_state", value="HALTED", description="runtime bot state")
        session.add(row)
    else:
        row.value = "HALTED"
    request.app.state.bot_state = "HALTED"
    await session.commit()
    return {"status": "HALTED"}


@router.post("/admin/resume")
async def resume(
    request: Request, session: AsyncSession = Depends(get_session)
) -> dict[str, str]:
    row = await session.get(ConfigRef, "bot_state")
    if row is None:
        row = ConfigRef(key="bot_state", value="ACTIVE", description="runtime bot state")
        session.add(row)
    else:
        row.value = "ACTIVE"
    request.app.state.bot_state = "ACTIVE"
    await session.commit()
    return {"status": "ACTIVE"}


@router.post("/admin/panic")
async def panic(
    request: Request, session: AsyncSession = Depends(get_session)
) -> dict[str, object]:
    confirm = request.headers.get("X-Confirm")
    if confirm != "STOP":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Confirm: STOP is required to trigger the kill switch",
        )

    row = await session.get(ConfigRef, "bot_state")
    if row is None:
        row = ConfigRef(
            key="bot_state", value="HALTED", description="runtime bot state"
        )
        session.add(row)
    else:
        row.value = "HALTED"
    request.app.state.bot_state = "HALTED"

    broker: BrokerClient = request.app.state.broker
    account_broker_id = await _resolve_broker_account_id(broker, session)

    cancelled: list[str] = []
    errors: list[dict[str, str]] = []
    active_orders = await session.scalars(
        select(Order).where(Order.order_status.in_(_CANCELLABLE_ORDER_STATUSES))
    )
    for order in active_orders:
        if order.broker_order_id is None or account_broker_id is None:
            order.order_status = OrderStatus.CANCELLED
            cancelled.append(order.client_order_id)
            continue
        try:
            await broker.cancel_order(account_broker_id, order.broker_order_id)
            order.order_status = OrderStatus.CANCELLED
            cancelled.append(order.client_order_id)
        except Exception as exc:
            _logger.warning(
                "panic_cancel_failed",
                client_order_id=order.client_order_id,
                broker_order_id=order.broker_order_id,
                error=str(exc),
            )
            errors.append(
                {
                    "client_order_id": order.client_order_id,
                    "error": str(exc),
                }
            )

    session.add(
        AuditLog(
            event_type="PANIC",
            entity_type="system",
            entity_id="panic",
            correlation_id=None,
            payload_json={
                "cancelled": cancelled,
                "errors": errors,
                "actor": request.headers.get("X-Actor", "operator"),
            },
        )
    )
    await session.commit()

    _logger.warning(
        "panic_triggered",
        cancelled=len(cancelled),
        errors=len(errors),
    )
    return {
        "status": "HALTED",
        "cancelled_orders": cancelled,
        "errors": errors,
    }


@router.post("/admin/run-ai-now")
async def run_ai_now(request: Request) -> dict[str, object]:
    wait_seconds = await _run_ai_limiter.check_and_record()
    if wait_seconds > 0:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"rate limited; retry in {wait_seconds:.1f}s",
        )

    signal_runner: Callable[[str], Awaitable[int]] | None = getattr(
        request.app.state, "signal_runner", None
    )
    if signal_runner is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="signal_runner is not initialized",
        )

    runner_callable = (
        signal_runner.run if hasattr(signal_runner, "run") else signal_runner
    )
    count = await runner_callable("MANUAL")
    request.app.state.last_scheduler_run = "manual_ai"
    return {"status": "ok", "reason": "MANUAL", "signals_generated": count}


__all__ = ["router"]
