from __future__ import annotations

from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from darth_schwader.services.reconciliation import reconcile_end_of_day

MARKET_TZ = ZoneInfo("America/New_York")


def register_jobs(scheduler: AsyncIOScheduler, deps: dict[str, object]) -> None:
    settings = deps["settings"]
    session_factory = deps["session_factory"]
    account_sync = deps["account_sync"]
    chain_service = deps["chain_service"]
    token_watchdog_job = deps["token_watchdog"]
    iv_watcher = deps["iv_watcher"]
    signal_runner = deps.get("signal_runner")
    polygon_backfill = deps.get("polygon_backfill")

    async def _run_token_watchdog() -> None:
        await token_watchdog_job()

    async def _run_reconciliation() -> None:
        await reconcile_end_of_day(session_factory)

    scheduler.add_job(
        _run_token_watchdog,
        trigger=IntervalTrigger(minutes=5),
        id="token_watchdog",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        account_sync.run,
        trigger=CronTrigger(hour="9-16", minute="0,30", timezone=MARKET_TZ),
        id="account_snapshot",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        chain_service.pull_watchlist,
        trigger=CronTrigger(hour=9, minute=35, timezone=MARKET_TZ),
        id="chain_pull_open",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        chain_service.pull_watchlist,
        trigger=CronTrigger(hour=15, minute=30, timezone=MARKET_TZ),
        id="chain_pull_preclose",
        max_instances=1,
        coalesce=True,
    )
    if signal_runner is not None:
        async def _run_signal_open() -> None:
            await signal_runner("SCHEDULED_OPEN")

        async def _run_signal_preclose() -> None:
            await signal_runner("SCHEDULED_PRECLOSE")

        scheduler.add_job(
            _run_signal_open,
            trigger=CronTrigger(hour=9, minute=36, timezone=MARKET_TZ),
            id="signal_run_open",
            max_instances=1,
            coalesce=True,
        )
        scheduler.add_job(
            _run_signal_preclose,
            trigger=CronTrigger(hour=15, minute=31, timezone=MARKET_TZ),
            id="signal_run_preclose",
            max_instances=1,
            coalesce=True,
        )
    scheduler.add_job(
        iv_watcher.scan,
        trigger=CronTrigger(hour="9-15", minute="*/10", timezone=MARKET_TZ),
        id="iv_watcher",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        account_sync.run,
        trigger=CronTrigger(hour="9-15", minute="*/5", timezone=MARKET_TZ),
        id="position_sync",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _run_reconciliation,
        trigger=CronTrigger(hour=16, minute=30, timezone=MARKET_TZ),
        id="eod_reconciliation",
        max_instances=1,
        coalesce=True,
    )
    if settings.polygon_api_key is not None and polygon_backfill is not None:
        scheduler.add_job(
            polygon_backfill,
            trigger=CronTrigger(hour=22, minute=0, timezone=MARKET_TZ),
            id="polygon_nightly_backfill",
            max_instances=1,
            coalesce=True,
        )


__all__ = ["register_jobs"]
