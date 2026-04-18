# Darth Schwader

Phase 1 foundation for a single-tenant, web-based options trading bot built around FastAPI, SQLite, and Charles Schwab OAuth.

## Scope

- FastAPI application scaffold with lifecycle-managed database engine and scheduler
- SQLite schema and Alembic migration for trading, audit, chain, token, and cash-ledger state
- Schwab OAuth 2.0 with PKCE and encrypted token persistence
- Schwab API client with refresh-on-401 and bounded retry behavior
- Cash-account primitives for settled/unsettled funds and collateral locking

## Status

`Phase-1 scaffold`

## Quickstart

1. Bootstrap the local environment:

   ```bash
   ./scripts/bootstrap_local.sh
   ```

2. Review `.env` and populate:

   - `SCHWAB_CLIENT_ID`
   - `SCHWAB_CLIENT_SECRET`
   - `SCHWAB_ACCOUNT_NUMBER`
   - `TOKEN_ENCRYPTION_KEY`

3. Complete the initial Schwab OAuth login:

   ```bash
   .venv/bin/python scripts/schwab_oauth_login.py
   ```

4. Run the local app:

   ```bash
   .venv/bin/uvicorn darth_schwader.main:create_app --factory --reload
   ```

5. Verify health:

   ```bash
   curl http://127.0.0.1:8000/api/v1/health
   ```

## Notes

- Live order submission remains gated behind `paper_trading=true` until later phases.
- Tokens are encrypted at rest and should never appear in logs.
