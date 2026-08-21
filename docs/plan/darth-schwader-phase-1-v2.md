# Implementation Plan: Darth Schwader — Phase 1 (v2, post-clarification)

> Single-tenant, web-based automated options trading bot.
> Phase 1 = repo scaffold, Schwab OAuth + chain fetch, SQLite schema, deterministic risk skeleton, FastAPI app, minimal HTMX dashboard, Phase-2 hooks for hybrid Quant+LLM AI engine.
> Live order submission stays behind `paper_trading=True` until the user explicitly flips it.
>
> v2 changes from v1 (driven by user clarification):
> - Hybrid AI: Quant/ML pricing+direction module + LLM strategy/sizing module (Phase-2 implementation; Phase-1 wires the contracts).
> - Scheduled cadence (open + 30 min pre-close) + IV-spike event detector. No 5-min polling.
> - Universe: SPY, QQQ, IWM, AAPL, NVDA, TSLA, MSFT, META.
> - Strategies expanded: + Cash Secured Puts, Covered Calls, Calendar Spreads.
> - Risk caps: editable in settings; naked options behind a feature flag (default OFF).
> - HITL non-negotiable: every approved-by-risk signal still requires a human click.
> - Cash account, under $25k → no PDT, no margin; track settled vs unsettled funds (T+1).
> - Polygon.io historical data ingestion plan.
> - Schwab Developer registration walkthrough included.
> - Always-on local Mac/server hosting; keys + DB stay local.

---

## Task Type
- [x] Backend (Codex authority)
- [x] Frontend (Gemini authority)
- [x] Fullstack (parallel)

---

## Architecture Decision (v2)

**Stack** (unchanged from v1)
- Python 3.12, **FastAPI**, Pydantic v2 + `pydantic-settings`
- **SQLAlchemy 2.x async + Alembic** over **SQLite (WAL, foreign_keys=ON)**
- **APScheduler `AsyncIOScheduler`** for scheduled jobs + IV spike watcher
- **httpx + respx**
- **UI: FastAPI + Jinja2 + HTMX** (Streamlit and React/Vite rejected — see v1 rationale)
- Modular monolith, single SQLite file under `data/`

**New for v2**
- **`quant/` module**: pure deterministic feature engineering (IV rank, IV percentile, term-structure slope, skew, realized-vs-implied vol spread, momentum/regime features). No I/O.
- **`ai/llm/` submodule**: Anthropic Claude or OpenAI client wrapped behind `LLMStrategySelector` Protocol. Consumes quant features + chain context, emits `StrategySignal[]`. Provider behind a flag, default Claude.
- **`market/iv_watcher.py`**: monitors IV percentile per underlying; when `current_iv_pct > settings.iv_spike_threshold` (default 90th percentile), enqueues an event signal-generation run.
- **`broker/cash_account.py`**: tracks `settled_cash`, `unsettled_cash` (per T+1 settlement), and `csp_collateral_locked` so CSPs don't double-spend cash.
- **Strategy validators per cash-account semantics** (see "Cash Account & Naked Options" below).

**Hard invariants (v2-revised)**
1. **Defined-risk by default, naked allowed only when `settings.allow_naked=True`** AND the specific strategy template is on the allowed list. Schema enforces flag at write time.
2. Every order references an approving `risk_event` row (FK NOT NULL).
3. Idempotent submission via deterministic `client_order_id`.
4. AI never submits orders. AI emits `StrategySignal`s. Risk engine approves. **Human clicks. Then** order_service submits. (HITL is now codified, not optional.)
5. Token material encrypted at rest, never logged.
6. Restart recovery rebuilds state from broker truth + local audit log.
7. Paper-trading default ON.
8. **Cash collateral check is mandatory** for any CSP, Covered Call, or strategy requiring upfront cash/shares. Risk engine rejects if `settled_cash < required_collateral`.

---

## Cash Account & Naked Options (new section)

Because the account is **cash, sub-$25k**:
- **PDT rules don't apply** (cash account is exempt; you simply can't trade with unsettled funds).
- **No margin → no margin spreads.** However, defined-risk vertical spreads and iron condors still work in a cash account because **the broker holds the long leg as collateral for the short leg**. Schwab calls this "spread approval level"; you'll need at least Tier/Level 2 options approval.
- **CSPs**: full strike × 100 × contracts in cash must be reserved as collateral.
- **Covered Calls**: 100 shares per contract must be owned (and not pledged elsewhere).
- **Calendars**: defined-risk; debit calendar spreads work in cash accounts.
- **T+1 settlement**: option proceeds are available next business day; the bot must distinguish `settled_cash` from `unsettled_cash` to avoid Good-Faith Violations.

**Required Schwab options approval level**: at least **Tier 2** (long calls/puts, covered calls, CSPs, debit spreads). For iron condors and credit spreads in a cash account, **Tier 3** is typically required. The Schwab walkthrough below covers this.

**Naked options**:
- `allow_naked: bool = False` in settings (default disabled).
- When `True`, additional schema/risk gates allow `naked_call`, `naked_put` strategy types.
- Cash account naked calls are effectively impossible (would need infinite collateral); naked puts in a cash account are just CSPs by another name.
- Recommendation: keep `allow_naked = False` in cash account; revisit when account grows past $25k and migrates to margin.

---

## Repository Structure (v2 deltas marked)

```text
darth-schwader/
├── pyproject.toml
├── README.md
├── .env.example
├── .gitignore
├── alembic.ini
├── alembic/
│   ├── env.py
│   └── versions/
├── data/                                   # SQLite + chain history (gitignored)
├── docs/
│   ├── phase-1-plan.md
│   ├── schwab-developer-setup.md           # NEW: walkthrough
│   ├── polygon-data-plan.md                # NEW: historical ingestion plan
│   └── cash-account-rules.md               # NEW: T+1, settled funds, options tiers
├── src/darth_schwader/
│   ├── main.py
│   ├── config.py                           # CHANGED: editable risk caps, allow_naked flag, account_type
│   ├── logging.py
│   ├── lifespan.py
│   ├── api/
│   │   ├── deps.py
│   │   ├── error_handlers.py
│   │   └── routers/
│   │       ├── health.py
│   │       ├── status.py
│   │       ├── broker.py
│   │       ├── chains.py
│   │       ├── positions.py
│   │       ├── orders.py
│   │       ├── signals.py                  # CHANGED: explicit HITL approve endpoint
│   │       ├── risk.py
│   │       ├── settings.py                 # NEW: read+update risk caps from UI
│   │       └── admin.py
│   ├── ai/
│   │   ├── contracts.py
│   │   ├── service.py                      # SignalGenerator orchestration (Phase-2 plug-in)
│   │   ├── llm/                            # NEW
│   │   │   ├── selector.py                 # LLMStrategySelector Protocol
│   │   │   ├── claude_provider.py
│   │   │   └── prompts/
│   │   │       └── strategy_selection.md
│   │   └── strategies/
│   │       ├── vertical_spread.py
│   │       ├── iron_condor.py
│   │       ├── defined_risk_directional.py
│   │       ├── cash_secured_put.py         # NEW
│   │       ├── covered_call.py             # NEW
│   │       └── calendar_spread.py          # NEW
│   ├── quant/                              # NEW: pure deterministic feature engineering
│   │   ├── iv_metrics.py                   # iv_rank, iv_percentile, term_structure, skew
│   │   ├── direction_model.py              # Phase-2 ML stub interface (XGBoost/LightGBM)
│   │   ├── regime.py                       # vol regime classification
│   │   └── features.py                     # feature pipeline
│   ├── market/                             # NEW
│   │   ├── iv_watcher.py                   # event detector for IV spikes
│   │   └── universe.py                     # watchlist constants + validation
│   ├── broker/
│   │   ├── base.py
│   │   ├── exceptions.py
│   │   ├── models.py
│   │   ├── cash_account.py                 # NEW: settled vs unsettled, CSP collateral
│   │   └── schwab/
│   │       ├── oauth.py
│   │       ├── client.py
│   │       ├── mappers.py
│   │       └── endpoints.py
│   ├── domain/
│   │   ├── enums.py                        # CHANGED: expanded StrategyType enum
│   │   ├── ids.py
│   │   └── types.py
│   ├── db/
│   │   ├── base.py
│   │   ├── session.py
│   │   ├── models.py                       # CHANGED: defined_risk no longer hard-1
│   │   └── repositories/
│   │       ├── tokens.py
│   │       ├── accounts.py
│   │       ├── positions.py
│   │       ├── orders.py
│   │       ├── fills.py
│   │       ├── signals.py
│   │       ├── risk_events.py
│   │       ├── audit.py
│   │       ├── chains.py
│   │       └── cash_ledger.py              # NEW: settled funds tracking
│   ├── risk/
│   │   ├── engine.py
│   │   ├── rules.py                        # CHANGED: cash-account rules + naked gate
│   │   ├── policies.py                     # CHANGED: caps loaded from settings + DB
│   │   └── models.py
│   ├── services/
│   │   ├── account_sync.py
│   │   ├── chain_service.py
│   │   ├── order_service.py
│   │   ├── portfolio_service.py
│   │   ├── reconciliation.py
│   │   ├── scheduler.py                    # CHANGED: scheduled + event triggers, no 5-min loop
│   │   ├── token_watchdog.py
│   │   └── settled_funds.py                # NEW: T+1 ledger updater
│   ├── data_sources/                       # NEW
│   │   ├── polygon/
│   │   │   ├── client.py                   # Polygon.io REST client
│   │   │   ├── ingestion.py                # historical chain backfill
│   │   │   └── mappers.py
│   │   └── schwab_market.py
│   └── ui/
│       ├── routes.py
│       ├── templates/
│       │   ├── base.html
│       │   ├── dashboard.html
│       │   ├── _status_header.html
│       │   ├── _positions_table.html
│       │   ├── _signals_queue.html         # CHANGED: explicit Approve/Reject buttons
│       │   ├── _risk_log.html
│       │   ├── _equity_sparkline.html
│       │   ├── _chain_grid.html
│       │   ├── _settings_form.html         # NEW: edit risk caps from UI
│       │   └── _cash_ledger.html           # NEW: settled vs unsettled
│       └── static/
│           ├── css/app.css
│           └── js/htmx.min.js
├── scripts/
│   ├── bootstrap_local.sh
│   ├── run_dev.sh
│   ├── schwab_oauth_login.py
│   ├── reconcile_now.py
│   └── polygon_backfill.py                 # NEW
└── tests/
    ├── conftest.py
    ├── unit/
    │   ├── test_risk_rules.py              # CHANGED: cash collateral, naked gate, DTE bounds
    │   ├── test_chain_normalization.py
    │   ├── test_client_order_id.py
    │   ├── test_schwab_retry_refresh.py
    │   ├── test_iv_metrics.py              # NEW
    │   ├── test_iv_watcher.py              # NEW
    │   └── test_settled_funds.py           # NEW
    ├── integration/
    │   ├── test_api_status.py
    │   ├── test_api_signals_hitl.py        # NEW
    │   ├── test_api_settings_update.py     # NEW
    │   ├── test_scheduler_jobs.py
    │   └── test_reconciliation.py
    └── fixtures/{schwab,polygon}/
```

---

## SQLite Schema (v2 — diffs from v1)

Most tables unchanged. Diffs only:

```sql
-- accounts: add account_type semantics
ALTER TABLE accounts ADD COLUMN options_approval_tier INTEGER;       -- 1, 2, 3
-- (account_type already existed; values now constrained to CASH | MARGIN | PORTFOLIO_MARGIN)

-- NEW: cash ledger for T+1 settlement tracking
CREATE TABLE cash_ledger (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    occurred_at TEXT NOT NULL,
    settles_on TEXT NOT NULL,                -- T+1 for options proceeds
    delta_amount REAL NOT NULL,              -- positive = inflow, negative = outflow
    reason TEXT NOT NULL,                    -- ORDER_FILL, COLLATERAL_LOCK, COLLATERAL_RELEASE, ...
    related_order_id INTEGER REFERENCES orders(id),
    related_fill_id INTEGER REFERENCES fills(id),
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_cash_ledger_account_settles ON cash_ledger (account_id, settles_on);

-- orders: relax defined_risk; add explicit naked flag + collateral
DROP CHECK on orders.defined_risk;            -- (recreate via migration as below)
-- New columns:
ALTER TABLE orders ADD COLUMN is_naked INTEGER NOT NULL DEFAULT 0
    CHECK (is_naked IN (0,1));
ALTER TABLE orders ADD COLUMN required_collateral REAL NOT NULL DEFAULT 0
    CHECK (required_collateral >= 0);
ALTER TABLE orders ADD COLUMN collateral_kind TEXT
    CHECK (collateral_kind IN ('CASH','SHARES','LONG_OPTION','NONE'));
-- Replace defined_risk CHECK:
-- defined_risk INTEGER NOT NULL CHECK (defined_risk IN (0,1))
-- (write-time guard in repository: if defined_risk=0, settings.allow_naked must be True)

-- positions: same shape changes as orders
ALTER TABLE positions ADD COLUMN is_naked INTEGER NOT NULL DEFAULT 0
    CHECK (is_naked IN (0,1));
ALTER TABLE positions ADD COLUMN collateral_amount REAL NOT NULL DEFAULT 0
    CHECK (collateral_amount >= 0);
ALTER TABLE positions ADD COLUMN collateral_kind TEXT
    CHECK (collateral_kind IN ('CASH','SHARES','LONG_OPTION','NONE'));

-- signals: expand strategy_type domain
-- New allowed values:
--   VERTICAL_SPREAD, IRON_CONDOR, DEFINED_RISK_DIRECTIONAL,
--   CASH_SECURED_PUT, COVERED_CALL, CALENDAR_SPREAD,
--   NAKED_PUT, NAKED_CALL    (the last two only when allow_naked=True)

-- NEW: editable runtime risk policy overrides (UI-driven)
CREATE TABLE risk_policy_overrides (
    id INTEGER PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    value TEXT NOT NULL,                     -- stringified Decimal/int/bool
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_by TEXT NOT NULL DEFAULT 'ui'
);

-- NEW: persist IV-spike events that triggered signal generation
CREATE TABLE iv_spike_events (
    id INTEGER PRIMARY KEY,
    underlying TEXT NOT NULL,
    iv_percentile REAL NOT NULL,
    iv_rank REAL,
    triggered_at TEXT NOT NULL,
    threshold_used REAL NOT NULL,
    signal_run_id TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_iv_events_underlying_time ON iv_spike_events (underlying, triggered_at);
```

All other v1 tables (`broker_tokens`, `chain_snapshots`, `risk_events`, `fills`, `audit_log`, `account_snapshots`, `config_refs`) unchanged.

---

## Configuration (v2)

```python
class Settings(BaseSettings):
    env: Literal["dev","test","prod"] = "dev"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    database_url: str = "sqlite+aiosqlite:///./data/darth_schwader.db"
    log_level: str = "INFO"

    # Schwab
    schwab_client_id: str
    schwab_client_secret: SecretStr
    schwab_redirect_uri: AnyHttpUrl = "https://127.0.0.1:8000/api/v1/broker/oauth/callback"
    schwab_account_number: str
    token_encryption_key: SecretStr

    # Account semantics
    account_type: Literal["CASH","MARGIN","PORTFOLIO_MARGIN"] = "CASH"
    options_approval_tier: int = 2           # request Tier 3 from Schwab to enable iron condors

    # Universe
    watchlist: list[str] = ["SPY","QQQ","IWM","AAPL","NVDA","TSLA","MSFT","META"]

    # Trading mode
    paper_trading: bool = True               # default ON
    hitl_required: bool = True               # non-negotiable per user; gate, do not remove
    allow_naked: bool = False                # off in cash account

    # Risk caps (UI-editable; settings = defaults, risk_policy_overrides table = live values)
    max_risk_per_trade_pct: Decimal = Decimal("0.25")    # USER-SPECIFIED (see Risk Register #1)
    max_daily_drawdown_pct:  Decimal = Decimal("0.05")
    max_weekly_drawdown_pct: Decimal = Decimal("0.10")
    max_positions: int = 5
    max_underlying_allocation_pct: Decimal = Decimal("0.20")
    min_dte_days: int = 14
    max_dte_days: int = 60

    # AI / signal generation
    ai_provider: Literal["claude","openai","none"] = "claude"
    anthropic_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    iv_spike_threshold_pct: Decimal = Decimal("90")     # 90th percentile

    # Polygon historical data (Phase 2)
    polygon_api_key: SecretStr | None = None
    polygon_backfill_days: int = 365
```

The runtime values are: **DB override (if present) → settings default → bail**. Updates from `/api/v1/settings` write to `risk_policy_overrides`; restart not required.

---

## Scheduler (v2)

| Job | Cadence | Purpose |
|---|---|---|
| `token_watchdog` | every 5 min | refresh proactively if access expires < 10 min |
| `account_snapshot` | every 30 min during market hours; once after close | persist `account_snapshots`; recompute settled cash |
| `chain_pull_open` | 09:35 ET (market open + 5 min) | pull chains for full watchlist |
| `chain_pull_preclose` | 15:30 ET | pull chains for full watchlist |
| `signal_run_open` | 09:36 ET | quant features → LLM strategy selection → signals enqueued |
| `signal_run_preclose` | 15:31 ET | second scheduled run |
| `iv_watcher` | every 10 min during market hours | check IV percentile per underlying; if > threshold, log `iv_spike_events` row + trigger event-driven `signal_run` |
| `position_sync` | every 5 min during market hours | reconcile `positions` against broker truth |
| `eod_reconciliation` | 16:30 ET | fills, equity, expire stale signals, settle cash deltas |
| `polygon_nightly_backfill` | 22:00 ET | append yesterday's chain snapshots from Polygon (Phase 2) |

All jobs `max_instances=1`, `coalesce=True`, wrapped with audit + timeout.

---

## Risk Engine Rules (v2 — pure functions)

In evaluation order (any reject short-circuits):

1. **Strategy whitelist**: must be in {VERTICAL_SPREAD, IRON_CONDOR, DEFINED_RISK_DIRECTIONAL, CASH_SECURED_PUT, COVERED_CALL, CALENDAR_SPREAD} OR (NAKED_PUT/NAKED_CALL AND `settings.allow_naked`).
2. **Naked gate**: `is_naked == True` requires `settings.allow_naked == True`. Reject otherwise.
3. **DTE bounds**: every leg's expiration ∈ [`min_dte_days`, `max_dte_days`]. Reject otherwise.
4. **Account type compatibility**: CASH account → reject any strategy using `MARGIN` collateral.
5. **Tier check**: strategies requiring Tier 3 (e.g. iron condor in cash account) reject if `options_approval_tier < 3`.
6. **Defined-risk math**: compute `max_loss` from leg prices × multiplier × quantity. For undefined-risk (only when allow_naked), compute `theoretical_max_loss` from underlying-to-zero or 2×IV expected move.
7. **Per-trade cap**: `max_loss <= max_risk_per_trade_pct * current_nlv`.
8. **Per-underlying concentration**: existing exposure (Σ open `max_loss` for same underlying) + this trade's `max_loss` ≤ `max_underlying_allocation_pct * current_nlv`.
9. **Open positions cap**: `count(open_positions) < max_positions`.
10. **Daily / weekly drawdown breakers**: if `day_pnl_pct <= -max_daily_drawdown_pct` OR `week_pnl_pct <= -max_weekly_drawdown_pct` → bot enters HALTED, all signal evaluations reject with `DRAWDOWN_BREAKER_ACTIVE`.
11. **Settled-cash collateral**: for CSP/CC/calendar/debit-spread paid in cash, required collateral ≤ `settled_cash`. Pending unsettled cash CANNOT be used (avoids Good-Faith Violations). Reject with `INSUFFICIENT_SETTLED_CASH`.
12. **Liquidity gate**: bid-ask spread on each leg ≤ X% of mid AND open interest ≥ Y. (Configurable; sensible defaults ship.)

Each rule returns a `RuleResult(passed: bool, reason_code: str, reason_text: str, evidence: dict)`. The full list is persisted to `risk_events.rule_results_json` for audit.

---

## HITL Flow (codified)

```
[Scheduler/IV-Watcher]
       │
       ▼
[ai.SignalGenerator]  ── quant features + LLM selector ──►  Signal(status=PENDING)
       │
       ▼  (immediately on creation)
[RiskEngine.evaluate_signal] ──► RiskDecision persisted to risk_events
       │                              │
       │                              └─ if REJECT → signal.status = REJECTED, surfaced in UI Risk Log
       │
       ▼  (if APPROVE)
Signal.status = APPROVED_AWAITING_HITL    ◄── shown in Signal Queue with green "Submit" button
       │
       ▼  (only on human click in /api/v1/signals/{id}/submit)
[order_service.submit_signal_for_execution]
       │
       └─► broker.submit_order  →  orders + fills + cash_ledger
```

`hitl_required` is a config flag for forward compatibility but the Phase-1/2 code path treats it as effectively always-true; even a setting flip cannot bypass the human-click route in Phase 1.

The signal status enum is therefore: `PENDING → APPROVED_AWAITING_HITL → EXECUTED` or `REJECTED` or `EXPIRED`.

---

## UI Changes (v2)

- **Signal Queue partial**: each row now shows quant features (IV rank, IV pct, regime), LLM-generated thesis, the `RiskDecision`, and an explicit `[Submit]` button (only visible on `APPROVED_AWAITING_HITL`).
  - `[Submit]` uses `hx-confirm="Submit ${strategy_type} on ${underlying} for max loss $${max_loss}?"` plus a 1.5s hold-to-confirm.
  - `[Reject]` (always available) writes a manual rejection.
- **New: Settings panel** (`_settings_form.html`) — edit all risk caps inline, posts to `/api/v1/settings`, validates server-side, writes to `risk_policy_overrides`. Changing `allow_naked` requires typing the word `CONFIRM` (cash account safety).
- **New: Cash Ledger panel** (`_cash_ledger.html`) — shows `Settled`, `Unsettled`, `Locked as Collateral`, `Available for New Trades`. Sticky beside the Positions table because in a cash account this is *the* binding constraint.
- **Status header**: now also shows `PAPER`/`LIVE` badge and `HITL` badge prominently.

---

## API Contract (v2 additions)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/settings` | current effective risk caps + flags |
| PUT | `/api/v1/settings` | upsert overrides (validated) |
| POST | `/api/v1/signals/{id}/submit` | **HITL submission** — only path that triggers a real order |
| POST | `/api/v1/signals/{id}/reject` | manual reject with reason |
| GET | `/api/v1/cash-ledger` | settled, unsettled, locked, available |
| GET | `/api/v1/iv-events?since=` | IV spike history |
| GET | `/api/v1/quant/features/{symbol}` | latest computed features (debug + UI) |

---

## Schwab Developer Setup Walkthrough (`docs/schwab-developer-setup.md`)

This is required before Phase-1 code can authenticate. The `schwab_oauth_login.py` script automates the rest, but Schwab requires a one-time manual app registration.

### Step 1 — Create a Schwab Developer account
1. Go to <https://developer.schwab.com>.
2. Click **Register** in the top-right. Use the same email tied to your brokerage account.
3. Verify email + complete profile.
4. Log in. You'll land on the Developer Portal dashboard.

### Step 2 — Create an App
1. From the dashboard, click **Dashboard → Create App**.
2. Fill in:
   - **App Name**: `darth-schwader-local` (any name; this is for your reference)
   - **Description**: "Personal automated options trading bot — local single-user use."
   - **Callback URL** (this matches our config): `https://127.0.0.1:8000/api/v1/broker/oauth/callback`
   - **API Products**: select **Accounts and Trading Production** AND **Market Data Production**.
   - **Order Limit**: start at the lowest (typically 120 req/min). You can request more later.
3. Submit.

### Step 3 — Wait for app approval
- Approval is **manual** by Schwab and typically takes **1–3 business days**.
- App status will move from `Approved Pending` → `Ready For Use`.
- You'll get an email; or check the dashboard.

### Step 4 — Capture credentials
Once `Ready For Use`:
1. Open your app from the dashboard.
2. Copy **App Key** → this is `SCHWAB_CLIENT_ID`.
3. Copy **Secret** → this is `SCHWAB_CLIENT_SECRET`. (Treat like a password.)
4. Note your **Callback URL** matches the one in `.env.example`.

### Step 5 — Confirm options approval level on the brokerage side (separate from developer portal)
1. Log in to schwab.com → Service → Account Settings → Options Approval.
2. Confirm you have **at least Tier 2** (CSPs, covered calls, debit spreads, long calls/puts).
3. **Request Tier 3** if you want iron condors / credit spreads in this cash account. Requires an application that asks about your experience and net worth.
4. Tier 3 approval can take 1–5 business days.

### Step 6 — Local HTTPS for the callback
Schwab requires `https://`. Three local options:
- **Recommended**: `mkcert` to issue a locally-trusted cert for `127.0.0.1`. The bot's uvicorn loads it for the OAuth callback only.
- Alternative: use `127.0.0.1` with a self-signed cert and accept the browser warning during the one-time auth dance.
- Setup commands ship in `scripts/bootstrap_local.sh` (mkcert install + cert generation).

### Step 7 — Run the OAuth bootstrap
```bash
# After app status is Ready For Use and .env has CLIENT_ID/CLIENT_SECRET
python scripts/schwab_oauth_login.py
# Opens browser → Schwab login → consent → callback persists encrypted tokens to SQLite.
# You only do this once; refresh tokens are then rotated automatically.
```

If anything errors, the script prints the redacted request/response so we can debug. Refresh tokens last ~7 days; the watchdog rotates them every cycle.

---

## Polygon.io Historical Data Plan (`docs/polygon-data-plan.md`)

Schwab's market-data API is great for live chains but limited for historical option chains. Polygon fills the gap.

### Plan tier
- **Options Starter** (~$29/mo) gives end-of-day chain snapshots, Greeks, IV, plus 2 years of historicals. Enough for backtesting through Phase-2.
- **Options Advanced** (~$79/mo) adds intraday OHLC if you want minute-bar backtests later. Defer.

### What we ingest
For each underlying in the watchlist:
- Daily option chain snapshots (all strikes, all expirations within 90 DTE) for the last 365 days (configurable via `polygon_backfill_days`).
- Underlying daily OHLCV for the same period (used by `quant.iv_metrics` to compute IV rank vs realized vol).
- Schedule: nightly incremental at 22:00 ET (`polygon_nightly_backfill` job).

### Where it lives
- Reuses the `chain_snapshots` table (Polygon and Schwab payloads normalized identically).
- New `data_source` column added: `'SCHWAB' | 'POLYGON'`.
- Backtest harness consumes `chain_snapshots` directly; does not care about source.

### Phase-1 scope
- Wire the Polygon client + `polygon_backfill.py` script.
- Do **not** run nightly backfill until you have a Polygon API key. Job is registered but skipped if `polygon_api_key is None`.

### Phase-2 use
- Backtest each strategy template against historical chains.
- Compute per-strategy edge before allowing it through risk in live mode.

---

## Updated File Build Order

| # | File | Operation | Description |
|---|---|---|---|
| 1 | `pyproject.toml`, `.env.example`, `Makefile` | Create | scaffold |
| 2 | `src/darth_schwader/main.py`, `config.py`, `logging.py` | Create | app entry + settings |
| 3 | `src/darth_schwader/db/models.py` + `alembic/versions/0001_init.py` | Create | full v2 schema |
| 4 | `src/darth_schwader/db/repositories/tokens.py` + `cash_ledger.py` | Create | encrypted tokens, settled-funds ledger |
| 5 | `src/darth_schwader/broker/schwab/{oauth,client,mappers}.py` | Create | Schwab integration with retry-once-on-401 |
| 6 | `scripts/schwab_oauth_login.py` + `bootstrap_local.sh` | Create | one-shot OAuth + mkcert |
| 7 | `src/darth_schwader/quant/{iv_metrics,features,regime}.py` | Create | pure feature engineering |
| 8 | `src/darth_schwader/market/{iv_watcher,universe}.py` | Create | event detector |
| 9 | `src/darth_schwader/risk/{engine,rules,policies,models}.py` | Create | deterministic rules incl. cash + naked gate |
| 10 | `src/darth_schwader/services/{settled_funds,order_service,reconciliation,scheduler}.py` | Create | order pipeline + jobs |
| 11 | `src/darth_schwader/ai/contracts.py` + `service.py` + `llm/selector.py` (stub) | Create | Phase-2 plug-in points |
| 12 | `src/darth_schwader/api/routers/*.py` | Create | HTTP surface incl. `/settings`, `/signals/{id}/submit` |
| 13 | `src/darth_schwader/ui/templates/*.html` + `static/css/app.css` | Create | HTMX dashboard incl. settings + cash ledger |
| 14 | `src/darth_schwader/data_sources/polygon/{client,ingestion}.py` + `scripts/polygon_backfill.py` | Create | historical pipeline (key-gated) |
| 15 | `tests/unit/*.py` and `tests/integration/*.py` | Create | per testing strategy |
| 16 | `docs/{phase-1-plan,schwab-developer-setup,polygon-data-plan,cash-account-rules}.md` | Create | onboarding |

---

## Risk Register (v2 — important addition)

| # | Risk | Mitigation / Note |
|---|---|---|
| 1 | **`max_risk_per_trade_pct = 25%` is materially aggressive.** With `max_positions = 5`, theoretical worst-case simultaneous loss is 125% of NLV (capped by reality at 100%). 4 unlucky trades could halve the account before the 5% daily breaker even fires (the breaker measures realized day P&L, not unrealized worst-case). | **Flagged for your awareness — not changing without confirmation.** Three options to consider for v3: (a) keep 25% as the hard ceiling but add a soft "preferred" 5% cap that the AI optimizes against; (b) lower to e.g. 5–10% per trade, raise position count; (c) keep as specified — you own the risk. Recommend we **at minimum** add a UI alert when a single trade's max_loss > 10% of NLV so you see the tail before clicking Submit. The plan ships this UI alert by default. |
| 2 | Schwab app approval delay (1–3 business days) blocks live integration | Phase-1 ships paper-broker first; Schwab integration is testable with `respx` fixtures while approval is pending. |
| 3 | Tier-3 options approval may not be granted on a sub-$25k cash account → no iron condors | Schema + risk rule already gate by `options_approval_tier`. If denied, the AI is restricted to CSPs, covered calls, calendars, defined-risk directional, and debit verticals. |
| 4 | T+1 settlement → Good-Faith Violations if the bot reuses unsettled cash | Hard rule #11 in the engine: only `settled_cash` counts as collateral. Cash Ledger UI panel makes this visible. |
| 5 | Naked options accidentally enabled | Default OFF; toggling requires typing `CONFIRM`; in cash account, naked calls are economically impossible anyway and naked puts collapse to CSPs. |
| 6 | LLM hallucinates a strategy that doesn't actually exist or proposes invalid leg combos | Strategy validators run on every `StrategySignal` before risk engine sees it; invalid → auto-reject with `STRATEGY_VALIDATION_FAILED`. |
| 7 | Polygon API costs creep | Backfill is gated by config; nightly job skipped if no key; you can budget. |
| 8 | Refresh token expires (7 days) while you're away | Watchdog rotates every 5 min; if the bot has been off for >7 days, you re-run `schwab_oauth_login.py`. UI shows "TOKEN_STALE" prominently. |
| 9 | Cash account exempt from PDT but **not from FINRA Rule 2090 know-your-customer / suitability** for Tier-3 strategies | Ensure Tier-3 application reflects your actual options experience. |
| 10 | Local SQLite + always-on Mac → no remote backup | Add `data/` to a Time Machine path or a nightly `cp` to iCloud Drive. Documented in `docs/cash-account-rules.md`. |

---

## Phase 2 Handoff Hooks (v2)

- `quant.features.compute(underlying, chain_snapshot, history) -> Features` — pure, easy to unit test, easy to backtest.
- `ai.llm.selector.LLMStrategySelector.select(features, context) -> list[StrategySignal]` — provider behind a Protocol; swap Claude ↔ OpenAI ↔ rules-only with one config flip.
- `BrokerClient` Protocol — `PaperBrokerClient` for tests/dev/Phase-1, `SchwabApiClient` for live.
- `risk_event_id` FK on `orders` — guarantees AI cannot bypass risk audit.
- `signals.status = APPROVED_AWAITING_HITL` is the only legal predecessor to `EXECUTED` — guarantees HITL.

---

## SESSION_ID (for `/ccg:execute` resume)

- **CODEX_SESSION**: `019da0d7-af38-7642-8491-021060c3c77d`
- **GEMINI_SESSION**: `770af350-d30c-47bf-8347-1be13d22f9c2`
