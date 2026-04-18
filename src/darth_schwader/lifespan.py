from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from darth_schwader.ai import SignalGenerator
from darth_schwader.ai.llm import build_selector
from darth_schwader.broker.cash_account import CashAccountGuard
from darth_schwader.broker.factory import BrokerFactory
from darth_schwader.broker.schwab.oauth import SchwabOAuthClient
from darth_schwader.config import Settings, get_settings
from darth_schwader.data_sources.polygon.client import PolygonClient
from darth_schwader.data_sources.polygon.ingestion import PolygonIngestion
from darth_schwader.db.models import RiskPolicyOverride
from darth_schwader.db.repositories.cash_ledger import CashLedgerRepository
from darth_schwader.db.repositories.chains import ChainRepository
from darth_schwader.db.repositories.iv_events import IvEventsRepository
from darth_schwader.db.repositories.tokens import TokenRepository
from darth_schwader.db.session import build_engine, build_session_factory, dispose_engine
from darth_schwader.logging import configure_logging
from darth_schwader.market.iv_watcher import IvWatcher
from darth_schwader.quant.features import Features
from darth_schwader.quant.features import compute as compute_features
from darth_schwader.risk.engine import RiskEngine
from darth_schwader.services.account_sync import AccountSyncService
from darth_schwader.services.chain_service import ChainService
from darth_schwader.services.order_service import OrderService
from darth_schwader.services.scheduler import register_jobs
from darth_schwader.services.signal_runner import SignalRunner, empty_feature_provider
from darth_schwader.services.token_watchdog import token_watchdog


class _QuantFeatureAdapter:
    def compute(
        self,
        underlying: str,
        chain_snapshot_rows: Sequence[Mapping[str, object]],
        underlying_ohlcv_rows: Sequence[Mapping[str, object]],
    ) -> Features:
        return compute_features(
            underlying=underlying,
            chain_snapshot_rows=chain_snapshot_rows,
            underlying_ohlcv_rows=underlying_ohlcv_rows,
        )


def _attach_ai_services(
    app: FastAPI,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    selector = build_selector(settings)
    app.state.llm_selector = selector
    app.state.signal_generator = SignalGenerator(
        quant=_QuantFeatureAdapter(),
        selector=selector,
        repos={"session_factory": session_factory},
        settings=settings,
    )


_RUNTIME_OVERRIDE_KEYS: frozenset[str] = frozenset(
    {
        "paper_trading",
        "hitl_required",
        "allow_naked",
        "max_risk_per_trade_pct",
        "preferred_max_risk_per_trade_pct",
        "max_daily_drawdown_pct",
        "max_weekly_drawdown_pct",
        "max_positions",
        "max_underlying_allocation_pct",
        "min_dte_days",
        "max_dte_days",
    }
)


async def _apply_runtime_overrides(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> Settings:
    async with session_factory() as session:
        rows = (await session.scalars(select(RiskPolicyOverride))).all()
    if not rows:
        return settings
    merged = settings.model_dump()
    applied: dict[str, object] = {}
    for row in rows:
        if row.key not in _RUNTIME_OVERRIDE_KEYS:
            continue
        merged[row.key] = row.value
        applied[row.key] = row.value
    if not applied:
        return settings
    return Settings.model_validate(merged)


@asynccontextmanager
async def app_lifespan(app: FastAPI) -> AsyncIterator[None]:  # noqa: PLR0915

    settings = get_settings()
    configure_logging(settings)

    engine = build_engine(settings.database_url)
    session_factory = build_session_factory(engine)

    settings = await _apply_runtime_overrides(settings, session_factory)

    # Scheduler timezone is ET because all market cron jobs are expressed in ET.
    scheduler = AsyncIOScheduler(timezone="America/New_York")

    token_repo = TokenRepository(session_factory, settings)
    cash_ledger_repo = CashLedgerRepository(session_factory)
    chain_repo = ChainRepository(session_factory)
    iv_events_repo = IvEventsRepository(session_factory)

    oauth_client = SchwabOAuthClient(settings, token_repo)
    broker = BrokerFactory.create(settings, token_repo)
    polygon_client = PolygonClient(settings)
    polygon_ingestion = PolygonIngestion(
        session_factory,
        polygon_client,
        settings.watchlist,
        settings.polygon_backfill_days,
    )

    risk_engine = RiskEngine()
    cash_guard = CashAccountGuard(cash_ledger_repo)

    chain_service = ChainService(session_factory, broker, settings)
    account_sync = AccountSyncService(session_factory, broker)
    order_service = OrderService(risk_engine, cash_guard)
    iv_watcher = IvWatcher(
        session_factory=session_factory,
        settings=settings,
        chain_repo=chain_repo,
        iv_events_repo=iv_events_repo,
        on_spike=None,
    )

    app.state.settings = settings
    app.state.db_engine = engine
    app.state.session_factory = session_factory
    app.state.scheduler = scheduler
    app.state.started_at = datetime.now(tz=UTC)
    app.state.bot_state = "ACTIVE"
    app.state.last_scheduler_run = None
    app.state.token_repo = token_repo
    app.state.cash_ledger_repo = cash_ledger_repo
    app.state.chain_repo = chain_repo
    app.state.iv_events_repo = iv_events_repo
    app.state.oauth_client = oauth_client
    app.state.broker = broker
    app.state.risk_engine = risk_engine
    app.state.cash_guard = cash_guard
    app.state.chain_service = chain_service
    app.state.account_sync = account_sync
    app.state.order_service = order_service
    app.state.polygon_client = polygon_client
    app.state.polygon_ingestion = polygon_ingestion
    app.state.iv_watcher = iv_watcher
    _attach_ai_services(app, settings, session_factory)

    signal_runner = SignalRunner(
        session_factory=session_factory,
        signal_generator=app.state.signal_generator,
        feature_provider=empty_feature_provider,
        watchlist=settings.watchlist,
    )
    app.state.signal_runner = signal_runner

    register_jobs(
        scheduler,
        {
            "settings": settings,
            "session_factory": session_factory,
            "account_sync": account_sync,
            "chain_service": chain_service,
            "token_watchdog": lambda: token_watchdog(token_repo, oauth_client),
            "iv_watcher": iv_watcher,
            "signal_runner": signal_runner.run,
            "polygon_backfill": polygon_ingestion.backfill_watchlist,
        },
    )

    scheduler.start(paused=False)
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        await polygon_client.close()
        await broker.close()
        await oauth_client.close()
        await dispose_engine(engine)


__all__ = ["app_lifespan"]
