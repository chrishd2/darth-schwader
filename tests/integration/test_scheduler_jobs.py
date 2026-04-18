from __future__ import annotations

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from darth_schwader.services.scheduler import register_jobs


async def _noop() -> None:
    return None


async def _noop_signal_runner(reason: str) -> int:
    del reason
    return 0


def _deps(settings, polygon_backfill) -> dict[str, object]:
    class _AccountSync:
        async def run(self) -> None:
            return None

    class _ChainService:
        async def pull_watchlist(self) -> None:
            return None

    class _IvWatcher:
        async def scan(self) -> None:
            return None

    return {
        "settings": settings,
        "session_factory": object(),
        "account_sync": _AccountSync(),
        "chain_service": _ChainService(),
        "token_watchdog": _noop,
        "iv_watcher": _IvWatcher(),
        "signal_runner": _noop_signal_runner,
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


def test_scheduler_registers_signal_run_jobs(settings) -> None:
    scheduler = AsyncIOScheduler()
    register_jobs(scheduler, _deps(settings, _noop))
    job_ids = {job.id for job in scheduler.get_jobs()}
    assert "signal_run_open" in job_ids
    assert "signal_run_preclose" in job_ids


def test_scheduler_requires_signal_runner(settings) -> None:
    deps = _deps(settings, _noop)
    deps["signal_runner"] = None
    scheduler = AsyncIOScheduler()
    with pytest.raises(ValueError, match="signal_runner is required"):
        register_jobs(scheduler, deps)
