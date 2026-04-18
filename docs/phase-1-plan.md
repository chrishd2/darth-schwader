# Phase 1 Plan

This document is the condensed Phase 1 plan as shipped across Batches 1, 2, and 3. It restates the v2 baseline plus the v3 sizing delta and points to the modules that implement each slice.

## Foundation

- App entry and lifecycle:
  - `src/darth_schwader/main.py`
  - `src/darth_schwader/lifespan.py`
  - `src/darth_schwader/config.py`
  - `src/darth_schwader/logging.py`
- Persistence:
  - `src/darth_schwader/db/models.py`
  - `src/darth_schwader/db/session.py`
  - `src/darth_schwader/db/repositories/`
  - `alembic/versions/0001_init.py`
- Schwab integration:
  - `src/darth_schwader/broker/schwab/oauth.py`
  - `src/darth_schwader/broker/schwab/client.py`
  - `src/darth_schwader/broker/schwab/mappers.py`
  - `scripts/schwab_oauth_login.py`

## Core rules

- Single-user, single-tenant deployment.
- Cash-account semantics first.
- Human approval remains required before execution.
- Tokens are encrypted at rest with Fernet.
- Money and risk values are `Decimal` in the domain and test layers.

## Quant and market detection

- Deterministic feature engineering lives under `src/darth_schwader/quant/`.
- IV spike detection and watchlist enforcement live under `src/darth_schwader/market/`.
- Historical chain ingestion hooks live under `src/darth_schwader/data_sources/`.

## Risk engine

Primary modules:

- `src/darth_schwader/risk/models.py`
- `src/darth_schwader/risk/policies.py`
- `src/darth_schwader/risk/rules.py`
- `src/darth_schwader/risk/engine.py`
- `src/darth_schwader/risk/context.py`

Evaluation order:

1. Bot halted check.
2. Strategy whitelist.
3. Naked gate.
4. DTE bounds.
5. Account type compatibility.
6. Options tier requirement.
7. Defined-risk math.
8. Hard per-trade ceiling.
9. Preferred sizing warning.
10. Underlying concentration.
11. Open positions cap.
12. Daily and weekly drawdown breakers.
13. Settled-cash collateral gate.
14. Liquidity gate.

v3 sizing model:

- `preferred_max_risk_per_trade_pct` is the AI target.
- `max_risk_per_trade_pct` is the hard ceiling.
- Trades between preferred and hard are allowed with warnings.
- Overrides above the ceiling are rejected.
- Final execution always persists a fresh `risk_events` row for the actual quantity submitted.

## Services and scheduler

- Services:
  - `src/darth_schwader/services/account_sync.py`
  - `src/darth_schwader/services/chain_service.py`
  - `src/darth_schwader/services/order_service.py`
  - `src/darth_schwader/services/reconciliation.py`
  - `src/darth_schwader/services/settled_funds.py`
  - `src/darth_schwader/services/token_watchdog.py`
  - `src/darth_schwader/services/scheduler.py`
- Scheduled jobs:
  - `token_watchdog`
  - `account_snapshot`
  - `chain_pull_open`
  - `chain_pull_preclose`
  - `signal_run_open`
  - `signal_run_preclose`
  - `iv_watcher`
  - `position_sync`
  - `eod_reconciliation`
  - `polygon_nightly_backfill`

## AI contracts

- Provider-agnostic contracts live under `src/darth_schwader/ai/contracts.py`.
- LLM strategy selection remains a Phase 2 plug-in point under `src/darth_schwader/ai/llm/`.
- Strategy validation and collateral formulas live under `src/darth_schwader/ai/strategies/`.

## API surface

- Routers live under `src/darth_schwader/api/routers/`.
- Settings writes persist `risk_policy_overrides`.
- `/api/v1/signals/{id}/submit` is the HITL submission path.
- `/api/v1/settings` enforces `0 < preferred <= hard <= 0.50`.

## Batch 3 additions

- Polygon historical ingestion:
  - `src/darth_schwader/data_sources/polygon/`
  - `scripts/polygon_backfill.py`
- Automated verification:
  - `tests/unit/`
  - `tests/integration/`
- Operator docs:
  - `docs/schwab-developer-setup.md`
  - `docs/polygon-data-plan.md`
  - `docs/cash-account-rules.md`
