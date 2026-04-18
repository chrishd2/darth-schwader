from __future__ import annotations

from decimal import Decimal

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from darth_schwader.broker.base import BrokerClient
from darth_schwader.config import Settings
from darth_schwader.db.models import ChainSnapshot


class ChainService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        broker: BrokerClient,
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._broker = broker
        self._settings = settings

    async def pull(self, underlying: str) -> int:
        chain = await self._broker.get_chain(underlying)
        async with self._session_factory() as session:
            await session.execute(
                delete(ChainSnapshot).where(
                    ChainSnapshot.underlying == underlying,
                    ChainSnapshot.quote_time == chain.quote_time,
                    ChainSnapshot.data_source == "SCHWAB",
                )
            )
            for contract in chain.contracts:
                session.add(
                    ChainSnapshot(
                        underlying=chain.underlying,
                        quote_time=chain.quote_time,
                        expiration_date=contract.expiration_date,
                        option_type=contract.option_type,
                        strike=contract.strike,
                        bid=contract.bid,
                        ask=contract.ask,
                        last=contract.last,
                        mark=contract.mark,
                        implied_volatility=contract.implied_volatility,
                        delta=contract.delta,
                        gamma=contract.gamma,
                        theta=contract.theta,
                        vega=contract.vega,
                        rho=contract.rho,
                        open_interest=contract.open_interest,
                        volume=contract.volume,
                        in_the_money=contract.in_the_money,
                        data_source="SCHWAB",
                        raw_payload=contract.raw,
                    )
                )
            await session.commit()
        return len(chain.contracts)

    async def pull_watchlist(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for underlying in self._settings.watchlist:
            counts[underlying] = await self.pull(underlying)
        return counts


__all__ = ["ChainService"]
