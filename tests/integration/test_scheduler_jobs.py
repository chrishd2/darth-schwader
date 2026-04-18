from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from darth_schwader.services.scheduler import register_jobs


async def _noop() -> None:
    return None


def _deps(settings, polygon_backfill) -> dict[str, object]:
    class _Runner:
        async def run(self) -> None:
            return None

    return {
        "settings": settings,
        "session_factory": object(),
        "account_sync": _Runner(),
        "chain_service": _Runner(),
        "token_watchdog": _noop,
        "iv_watcher": _Runner(),
        "signal_runner": None,
        "polygon_backfill": polygon_backfill,
    }


def test_scheduler_skips_polygon_job_without_key(settings) -> None:
    settings.polygon_api_key = None
    scheduler = AsyncIOScheduler()
    register_jobs(scheduler, _deps(settings, _noop))
    assert "polygon_nightly_backfill" not in {job.id for job in scheduler.get_jobs()}


def test_scheduler_registers_polygon_job_with_key(settings) -> None:
    scheduler = AsyncIOScheduler()
    register_jobs(scheduler, _deps(settings, _noop))
    job_ids = {job.id for job in scheduler.get_jobs()}
    assert "polygon_nightly_backfill" in job_ids
    assert "token_watchdog" in job_ids
    assert "chain_pull_open" in job_ids
