from __future__ import annotations

from decimal import Decimal
from typing import cast

import pytest

from darth_schwader.broker import BrokerFactory, PaperBrokerClient
from darth_schwader.broker.schwab.client import SchwabApiClient
from darth_schwader.config import Settings
from darth_schwader.db.repositories.tokens import TokenRepository


def test_broker_factory_returns_paper_client_when_paper_trading_enabled(
    settings: Settings,
) -> None:
    paper_settings = settings.model_copy(update={"paper_trading": True})
    token_repo = cast(TokenRepository, object())

    broker = BrokerFactory.create(paper_settings, token_repo)

    assert isinstance(broker, PaperBrokerClient)


@pytest.mark.asyncio
async def test_broker_factory_propagates_paper_settings_to_client(
    settings: Settings,
) -> None:
    paper_settings = settings.model_copy(
        update={
            "paper_trading": True,
            "paper_initial_cash": Decimal("250000"),
            "paper_slippage_bps": 7,
            "paper_session_penalty_bps": 15,
        }
    )
    token_repo = cast(TokenRepository, object())

    broker = BrokerFactory.create(paper_settings, token_repo)

    assert isinstance(broker, PaperBrokerClient)
    accounts = await broker.get_accounts()
    assert accounts[0].cash_balance == Decimal("250000")


@pytest.mark.asyncio
async def test_broker_factory_returns_schwab_client_when_paper_disabled(
    settings: Settings,
) -> None:
    live_settings = settings.model_copy(update={"paper_trading": False})
    token_repo = cast(TokenRepository, object())

    broker = BrokerFactory.create(live_settings, token_repo)

    try:
        assert isinstance(broker, SchwabApiClient)
    finally:
        await broker.close()
