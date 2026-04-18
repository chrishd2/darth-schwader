# Polygon.io Historical Data Plan

Schwab's market-data API is strong for live chains but limited for historical option chains. Polygon fills the gap.

## Plan tier

- **Options Starter** gives end-of-day chain snapshots, Greeks, IV, and multi-year history. That is enough for Phase 2 backtesting.
- **Options Advanced** adds intraday OHLC if minute-bar backtests become necessary later.

## What we ingest

For each underlying in the watchlist:

- Daily option-chain snapshots for expirations inside the configured historical window.
- Underlying daily OHLC for the same span.
- Nightly incremental backfill scheduled at `22:00 ET` through `polygon_nightly_backfill`.

## Where it lives

- Historical snapshots are normalized into `chain_snapshots`.
- `data_source` distinguishes `SCHWAB` from `POLYGON`.
- Consumers read normalized rows without caring about the vendor.

## Phase 1 scope

- Wire the Polygon client and `scripts/polygon_backfill.py`.
- Skip nightly ingestion when `polygon_api_key` is not configured.
