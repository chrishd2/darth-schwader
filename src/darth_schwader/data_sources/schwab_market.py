from __future__ import annotations

from collections.abc import Iterable

from darth_schwader.broker.base import BrokerClient
from darth_schwader.broker.models import OptionChain


class SchwabMarketDataSource:
    def __init__(self, broker: BrokerClient) -> None:
        self._broker = broker

    async def get_option_chain(self, underlying: str) -> OptionChain:
        return await self._broker.get_chain(underlying.upper())

    async def pull_watchlist(self, underlyings: Iterable[str]) -> dict[str, OptionChain]:
        chains: dict[str, OptionChain] = {}
        for underlying in underlyings:
            symbol = underlying.upper()
            chains[symbol] = await self.get_option_chain(symbol)
        return chains


__all__ = ["SchwabMarketDataSource"]
