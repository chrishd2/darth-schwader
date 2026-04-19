from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from darth_schwader.broker.models import (
    Account,
    OptionChain,
    OrderRequest,
    OrderResponse,
    Position,
)


@dataclass(frozen=True)
class BrokerCapabilities:
    supports_options: bool
    supports_equities: bool
    supports_futures: bool
    is_paper: bool


class BrokerClient(Protocol):
    async def get_accounts(self) -> list[Account]:
        ...

    async def get_positions(self, account_id: str) -> list[Position]:
        ...

    async def get_chain(self, symbol: str) -> OptionChain:
        ...

    async def submit_order(
        self,
        account_id: str,
        request: OrderRequest,
        *,
        session: AsyncSession | None = None,
    ) -> OrderResponse:
        ...

    async def get_order_status(self, account_id: str, broker_order_id: str) -> OrderResponse:
        ...

    async def cancel_order(self, account_id: str, broker_order_id: str) -> None:
        ...

    async def capabilities(self) -> BrokerCapabilities:
        ...

    async def close(self) -> None:
        ...


__all__ = ["BrokerCapabilities", "BrokerClient"]
