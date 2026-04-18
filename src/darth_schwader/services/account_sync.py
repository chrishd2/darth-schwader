from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from darth_schwader.broker.base import BrokerClient
from darth_schwader.db.models import Account, AccountSnapshot, Position


class AccountSyncService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        broker: BrokerClient,
    ) -> None:
        self._session_factory = session_factory
        self._broker = broker

    async def run(self) -> None:
        accounts = await self._broker.get_accounts()
        async with self._session_factory() as session:
            for broker_account in accounts:
                account = await session.scalar(
                    select(Account).where(Account.broker_account_id == broker_account.broker_account_id)
                )
                if account is None:
                    account = Account(
                        broker_account_id=broker_account.broker_account_id,
                        account_type=broker_account.account_type,
                        options_approval_tier=broker_account.options_approval_tier or 2,
                    )
                    session.add(account)
                    await session.flush()
                else:
                    account.account_type = broker_account.account_type
                    account.options_approval_tier = broker_account.options_approval_tier or account.options_approval_tier

                snapshot = AccountSnapshot(
                    account_id=account.id,
                    as_of=datetime.now(tz=UTC),
                    net_liquidation_value=broker_account.net_liquidation_value,
                    cash_balance=broker_account.cash_balance,
                    buying_power=broker_account.buying_power,
                    maintenance_requirement=Decimal("0"),
                    day_pnl=Decimal("0"),
                    week_pnl=Decimal("0"),
                    raw_payload=broker_account.raw,
                )
                session.add(snapshot)

                positions = await self._broker.get_positions(broker_account.broker_account_id)
                await session.execute(delete(Position).where(Position.account_id == account.id))
                for broker_position in positions:
                    session.add(
                        Position(
                            account_id=account.id,
                            broker_position_id=broker_position.broker_position_id,
                            underlying=broker_position.underlying,
                            strategy_type=broker_position.strategy_type,
                            status="OPEN",
                            opened_at=datetime.now(tz=UTC),
                            quantity=broker_position.quantity,
                            entry_cost=broker_position.entry_cost,
                            current_mark=broker_position.current_mark,
                            max_profit=Decimal("0"),
                            max_loss=broker_position.max_loss,
                            defined_risk=broker_position.defined_risk,
                            is_naked=broker_position.is_naked,
                            collateral_amount=broker_position.collateral_amount,
                            collateral_kind=broker_position.collateral_kind,
                            legs_json=[leg.model_dump(mode="json") for leg in broker_position.legs],
                            last_reconciled_at=datetime.now(tz=UTC),
                        )
                    )
            await session.commit()


__all__ = ["AccountSyncService"]
