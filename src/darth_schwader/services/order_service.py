from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from darth_schwader.ai.contracts import StrategyLeg, StrategySignal
from darth_schwader.broker.base import BrokerClient
from darth_schwader.broker.cash_account import CashAccountGuard
from darth_schwader.broker.models import OrderLeg, OrderRequest
from darth_schwader.db.models import Account, AuditLog, Order, Signal
from darth_schwader.domain.enums import CollateralKind, OrderStatus, SignalStatus
from darth_schwader.domain.ids import make_client_order_id
from darth_schwader.risk.engine import RiskEngine
from darth_schwader.risk.models import RiskContext

_INSTRUCTION_BY_ASSET_SIDE: dict[tuple[str, str], str] = {
    ("OPTION", "LONG"): "BUY_TO_OPEN",
    ("OPTION", "SHORT"): "SELL_TO_OPEN",
    ("EQUITY", "LONG"): "BUY",
    ("EQUITY", "SHORT"): "SELL_TO_OPEN",
    ("FUTURE", "LONG"): "BUY",
    ("FUTURE", "SHORT"): "SELL_TO_OPEN",
}


def _instruction_for(asset_type: str, side: str) -> str:
    key = (asset_type, side)
    instruction = _INSTRUCTION_BY_ASSET_SIDE.get(key)
    if instruction is None:
        raise ValueError(f"unsupported asset_type/side combination: {asset_type}/{side}")
    return instruction


class OrderService:
    def __init__(
        self,
        risk_engine: RiskEngine,
        cash_guard: CashAccountGuard,
    ) -> None:
        self._risk_engine = risk_engine
        self._cash_guard = cash_guard

    async def submit_signal(
        self,
        session: AsyncSession,
        signal_id: int,
        override_quantity: int | None,
        broker: BrokerClient,
        context: RiskContext,
    ) -> Order:
        signal = await session.get(Signal, signal_id)
        if signal is None:
            raise ValueError("signal not found")
        if signal.status != SignalStatus.APPROVED_AWAITING_HITL:
            raise ValueError("signal is not awaiting HITL submission")

        account = await session.scalar(select(Account).limit(1))
        if account is None:
            raise ValueError("account not found")

        strategy_signal = self._to_strategy_signal(signal)
        quantity = override_quantity if override_quantity is not None else strategy_signal.suggested_quantity
        decision = self._risk_engine.evaluate(strategy_signal, context, quantity)
        risk_event = await self._risk_engine.persist_decision(session, signal.id, account.id, decision)
        if decision.decision != "APPROVE":
            raise ValueError(decision.reason_text)

        client_order_id = make_client_order_id(signal.signal_id, 1)
        request = self._build_order_request(strategy_signal, quantity, client_order_id)

        try:
            await self._cash_guard.lock_for_order(
                account.id,
                request.required_collateral,
                datetime.now(tz=UTC).date(),
                notes=f"lock for {client_order_id}",
                session=session,
            )
            broker_response = await broker.submit_order(account.broker_account_id, request)
        except Exception:
            await self._cash_guard.release_for_cancel(
                account.id,
                request.required_collateral,
                datetime.now(tz=UTC).date(),
                notes=f"release for {client_order_id}",
                session=session,
            )
            failed = Order(
                account_id=account.id,
                signal_id=signal.id,
                risk_event_id=risk_event.id,
                broker_order_id=None,
                client_order_id=client_order_id,
                strategy_type=strategy_signal.strategy_type,
                underlying=strategy_signal.underlying,
                order_status=OrderStatus.REJECTED,
                intent="OPEN",
                price_limit=None,
                quantity=quantity,
                defined_risk=strategy_signal.strategy_type.name not in {"NAKED_CALL", "NAKED_PUT"},
                is_naked=strategy_signal.strategy_type.name in {"NAKED_CALL", "NAKED_PUT"},
                required_collateral=request.required_collateral,
                collateral_kind=request.collateral_kind,
                max_loss=decision.max_loss,
                order_payload=request.model_dump(mode="json"),
            )
            session.add(failed)
            await session.flush()
            raise

        order = Order(
            account_id=account.id,
            signal_id=signal.id,
            risk_event_id=risk_event.id,
            broker_order_id=broker_response.broker_order_id,
            client_order_id=client_order_id,
            strategy_type=strategy_signal.strategy_type,
            underlying=strategy_signal.underlying,
            order_status=broker_response.status,
            intent="OPEN",
            price_limit=request.price_limit,
            quantity=request.quantity,
            defined_risk=request.defined_risk,
            is_naked=request.is_naked,
            required_collateral=request.required_collateral,
            collateral_kind=request.collateral_kind,
            max_loss=request.max_loss,
            order_payload=request.model_dump(mode="json"),
            submitted_at=datetime.now(tz=UTC),
        )
        signal.status = SignalStatus.EXECUTED
        session.add(order)
        session.add(
            AuditLog(
                event_type="ORDER_SUBMITTED",
                entity_type="signal",
                entity_id=str(signal.id),
                correlation_id=client_order_id,
                payload_json={"order": order.client_order_id, "risk_event_id": risk_event.id},
            )
        )
        await session.flush()
        return order

    def _to_strategy_signal(self, signal: Signal) -> StrategySignal:
        legs = [
            StrategyLeg(
                occ_symbol=leg["occ_symbol"],
                side=leg["side"],
                quantity=int(leg["quantity"]),
                strike=Decimal(str(leg["strike"])),
                expiration=leg["expiration"],
                option_type=leg["option_type"],
                asset_type=leg.get("asset_type", "OPTION"),
            )
            for leg in signal.proposed_payload["legs"]
        ]
        return StrategySignal(
            signal_id=signal.signal_id,
            strategy_type=signal.strategy_type,
            underlying=signal.underlying,
            direction=signal.direction or "neutral",
            legs=legs,
            thesis=signal.thesis or "",
            confidence=signal.confidence or Decimal("0"),
            expiration_date=signal.expiration_date,
            suggested_quantity=signal.suggested_quantity or 1,
            suggested_max_loss=signal.suggested_max_loss,
            features_snapshot=signal.proposed_payload.get("features_snapshot", {}),
        )

    def _build_order_request(
        self,
        signal: StrategySignal,
        quantity: int,
        client_order_id: str,
    ) -> OrderRequest:
        per_contract_max_loss = Decimal(str(signal.features_snapshot["per_contract_max_loss"]))
        required_collateral = Decimal(
            str(signal.features_snapshot.get("required_collateral_per_contract", per_contract_max_loss))
        ) * Decimal(quantity)
        order_legs = [
            OrderLeg(
                instruction=_instruction_for(leg.asset_type, leg.side),
                quantity=quantity,
                instrument_symbol=leg.occ_symbol,
                asset_type=leg.asset_type,
            )
            for leg in signal.legs
        ]
        return OrderRequest(
            client_order_id=client_order_id,
            strategy_type=signal.strategy_type,
            quantity=quantity,
            price_limit=None,
            defined_risk=signal.strategy_type.name not in {"NAKED_CALL", "NAKED_PUT"},
            is_naked=signal.strategy_type.name in {"NAKED_CALL", "NAKED_PUT"},
            required_collateral=required_collateral,
            collateral_kind=CollateralKind.CASH,
            max_loss=per_contract_max_loss * Decimal(quantity),
            legs=order_legs,
            metadata={"signal_id": signal.signal_id},
        )


__all__ = ["OrderService"]
