from __future__ import annotations

import argparse
import asyncio

from darth_schwader.config import get_settings
from darth_schwader.data_sources.polygon.client import PolygonClient
from darth_schwader.data_sources.polygon.ingestion import PolygonIngestion
from darth_schwader.db.session import build_engine, build_session_factory, dispose_engine
from darth_schwader.logging import configure_logging, get_logger


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill Polygon option-chain history.")
    parser.add_argument(
        "--underlyings",
        default="",
        help="Comma-separated symbols. Defaults to settings.watchlist.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=0,
        help="Days of history to backfill. Defaults to settings.polygon_backfill_days.",
    )
    return parser.parse_args()


async def main() -> None:
    settings = get_settings()
    configure_logging(settings)
    logger = get_logger(__name__)

    if settings.polygon_api_key is None:
        logger.info("polygon_backfill_skipped", reason="polygon_api_key is not set")
        return

    args = parse_args()
    underlyings = (
        [symbol.strip().upper() for symbol in args.underlyings.split(",") if symbol.strip()]
        if args.underlyings
        else settings.watchlist
    )
    days = args.days or settings.polygon_backfill_days

    engine = build_engine(settings.database_url)
    session_factory = build_session_factory(engine)
    client = PolygonClient(settings)
    ingestion = PolygonIngestion(session_factory, client, underlyings)

    try:
        for underlying in underlyings:
            count = await ingestion.backfill(underlying, days)
            logger.info("polygon_backfill_complete", underlying=underlying, inserted=count, days=days)
    finally:
        await client.close()
        await dispose_engine(engine)


if __name__ == "__main__":
    asyncio.run(main())
