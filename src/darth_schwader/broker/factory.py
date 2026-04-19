from __future__ import annotations

from typing import Final

from darth_schwader.broker.base import BrokerCapabilities, BrokerClient
from darth_schwader.broker.paper import PaperBrokerClient, PriceSource, StaticPriceSource
from darth_schwader.broker.schwab.client import SchwabApiClient
from darth_schwader.config import Settings
from darth_schwader.db.repositories.tokens import TokenRepository
from darth_schwader.logging import get_logger

_logger = get_logger(__name__)

LIVE_BROKER_CAPABILITIES: Final[BrokerCapabilities] = BrokerCapabilities(
    supports_options=True,
    supports_equities=True,
    supports_futures=False,
    is_paper=False,
)


class BrokerFactory:
    @staticmethod
    def create(
        settings: Settings,
        token_repo: TokenRepository,
        *,
        price_source: PriceSource | None = None,
    ) -> BrokerClient:
        if settings.paper_trading:
            _logger.info(
                "broker_factory_paper_client",
                starting_cash=str(settings.paper_initial_cash),
                slippage_bps=settings.paper_slippage_bps,
                session_penalty_bps=settings.paper_session_penalty_bps,
            )
            return PaperBrokerClient(
                starting_cash=settings.paper_initial_cash,
                slippage_bps=settings.paper_slippage_bps,
                session_penalty_bps=settings.paper_session_penalty_bps,
                price_source=price_source or StaticPriceSource({}),
                account_type=settings.account_type,
            )

        _logger.info("broker_factory_schwab_client")
        return SchwabApiClient(settings, token_repo)


__all__ = ["LIVE_BROKER_CAPABILITIES", "BrokerFactory"]
