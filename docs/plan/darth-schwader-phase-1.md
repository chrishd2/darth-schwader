# Implementation Plan: Darth Schwader — Phase 1 Foundational Framework

> Single-tenant, web-based automated options trading bot.
> Phase 1 = repo scaffold, Schwab OAuth + chain fetch, SQLite schema, deterministic risk skeleton, FastAPI app, minimal HTMX dashboard.
> AI engine and live order submission are explicitly OUT of Phase 1 (interfaces + paper-trading toggle only).

---

## Task Type
- [x] Backend (Codex authority)
- [x] Frontend (Gemini authority)
- [x] Fullstack (parallel)

---

## Architecture Decision (Synthesized)

**Stack**
- Python 3.12, **FastAPI** (HTTP + lifespan), Pydantic v2 + `pydantic-settings`
- **SQLAlchemy 2.x async + Alembic** over **SQLite (WAL mode, foreign_keys=ON)**
- **APScheduler `AsyncIOScheduler`** for chain pulls, token watchdog, EOD reconciliation
- **httpx + respx** for Schwab client + tests
- **UI: FastAPI + Jinja2 + HTMX**, served by the same FastAPI process. No Node toolchain.
  - Streamlit rejected: too restrictive for option-chain grids and HITL signal queues.
  - React/Vite rejected for Phase 1: build chain overhead is unjustified for a single-user local console.
- **Modular monolith**, not microservices. Single binary, single SQLite file under `data/`.

**Hard invariants (non-negotiable, schema- and code-enforced)**
1. **Defined-risk only.** `orders.defined_risk = 1` CHECK constraint; risk engine rejects naked/undefined-risk structures.
2. **Every order references an approving `risk_event` row** (FK NOT NULL). No order can exist without an audit trail of why it was approved.
3. **Idempotent submission** via deterministic `client_order_id`.
4. **AI never submits orders.** AI emits `StrategySignal`s. The deterministic `RiskEngine` is the only path to execution.
5. **Token material is encrypted at rest**, never logged, never returned by any API endpoint.
6. **Restart recovery**: state is rebuilt from broker truth + local audit log on lifespan startup.
7. **Paper-trading default ON** until user explicitly flips `paper_trading = false` in `.env`.

**Rejected alternatives**
- Storing tokens only in `.env` — refresh-token rotation needs durable, versioned storage.
- Letting AI tune risk parameters at runtime — risk caps are deterministic config, not AI inputs.
- Microservices / Postgres / Redis — overkill for single-user local; interfaces preserved so we can graduate later.

---

## Repository Structure

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
├── data/                          # SQLite file lives here (gitignored)
├── docs/
│   └── phase-1-plan.md
├── src/darth_schwader/
│   ├── __init__.py
│   ├── main.py                    # uvicorn entry + create_app()
│   ├── config.py                  # pydantic-settings
│   ├── logging.py                 # structlog + token redaction filter
│   ├── lifespan.py                # startup: migrations, token bootstrap, reconciliation
│   ├── api/
│   │   ├── deps.py                # DI: db session, broker client, risk engine
│   │   ├── error_handlers.py
│   │   └── routers/
│   │       ├── health.py          # GET /api/v1/health
│   │       ├── status.py          # GET /api/v1/status      (UI header)
│   │       ├── broker.py          # GET /api/v1/broker/oauth/start, /callback
│   │       ├── chains.py          # GET /api/v1/chains/{symbol}
│   │       ├── positions.py       # GET /api/v1/positions
│   │       ├── orders.py          # GET /api/v1/orders
│   │       ├── signals.py         # GET /api/v1/signals  POST /{id}/approve|reject
│   │       ├── risk.py            # GET /api/v1/risk/events
│   │       └── admin.py           # POST /api/v1/admin/kill   (kill-switch)
│   ├── ai/
│   │   ├── contracts.py           # StrategySignal, ProposedLeg
│   │   └── service.py             # SignalGenerator stub (Phase 2 plug-in point)
│   ├── broker/
│   │   ├── base.py                # BrokerClient Protocol
│   │   ├── exceptions.py
│   │   ├── models.py              # AccountSummary, NormalizedOptionChain, etc.
│   │   └── schwab/
│   │       ├── oauth.py           # PKCE flow + refresh
│   │       ├── client.py          # SchwabApiClient(BrokerClient)
│   │       ├── mappers.py         # raw -> normalized
│   │       └── endpoints.py
│   ├── domain/
│   │   ├── enums.py
│   │   ├── ids.py                 # client_order_id generator
│   │   └── types.py
│   ├── db/
│   │   ├── base.py                # DeclarativeBase
│   │   ├── session.py             # async session factory
│   │   ├── models.py              # SQLAlchemy ORM
│   │   └── repositories/
│   │       ├── tokens.py          # encrypted token store
│   │       ├── accounts.py
│   │       ├── positions.py
│   │       ├── orders.py
│   │       ├── fills.py
│   │       ├── signals.py
│   │       ├── risk_events.py
│   │       ├── audit.py
│   │       └── chains.py
│   ├── risk/
│   │   ├── engine.py              # RiskEngine
│   │   ├── rules.py               # individual deterministic rules
│   │   ├── policies.py            # caps loaded from settings
│   │   └── models.py              # RiskContext, RiskDecision, RuleResult
│   ├── services/
│   │   ├── account_sync.py
│   │   ├── chain_service.py
│   │   ├── order_service.py       # the only path that writes to orders
│   │   ├── portfolio_service.py
│   │   ├── reconciliation.py
│   │   ├── scheduler.py
│   │   └── token_watchdog.py
│   └── ui/
│       ├── routes.py              # GET /, /chain, /signals (HTML)
│       ├── templates/
│       │   ├── base.html
│       │   ├── dashboard.html
│       │   ├── _status_header.html
│       │   ├── _positions_table.html
│       │   ├── _signals_queue.html
│       │   ├── _risk_log.html
│       │   ├── _equity_sparkline.html
│       │   └── _chain_grid.html
│       └── static/
│           ├── css/app.css        # tabular-nums, profit/loss semantics
│           └── js/htmx.min.js
├── scripts/
│   ├── bootstrap_local.sh
│   ├── run_dev.sh
│   ├── schwab_oauth_login.py      # one-shot interactive PKCE bootstrap
│   └── reconcile_now.py
└── tests/
    ├── conftest.py
    ├── unit/
    │   ├── test_risk_rules.py
    │   ├── test_chain_normalization.py
    │   ├── test_client_order_id.py
    │   └── test_schwab_retry_refresh.py
    ├── integration/
    │   ├── test_api_status.py
    │   ├── test_api_orders.py
    │   ├── test_scheduler_jobs.py
    │   └── test_reconciliation.py
    └── fixtures/schwab/           # captured chain + accounts payloads
```

---

## SQLite Schema (DDL)

```sql
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE config_refs (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    description TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE accounts (
    id INTEGER PRIMARY KEY,
    broker_account_id TEXT NOT NULL UNIQUE,
    account_hash TEXT,                       -- Schwab returns hashed account id for trading endpoints
    account_type TEXT NOT NULL,
    base_currency TEXT NOT NULL DEFAULT 'USD',
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE account_snapshots (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    as_of TEXT NOT NULL,
    net_liquidation_value REAL NOT NULL,
    cash_balance REAL NOT NULL,
    buying_power REAL,
    maintenance_requirement REAL,
    day_pnl REAL,
    week_pnl REAL,
    raw_payload TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(account_id, as_of)
);

CREATE TABLE broker_tokens (
    id INTEGER PRIMARY KEY,
    provider TEXT NOT NULL UNIQUE,           -- 'schwab'
    access_token_ciphertext TEXT NOT NULL,
    refresh_token_ciphertext TEXT NOT NULL,
    access_token_expires_at TEXT NOT NULL,
    refresh_token_expires_at TEXT NOT NULL,
    scope TEXT,
    token_type TEXT NOT NULL DEFAULT 'Bearer',
    rotated_at TEXT,
    last_refresh_attempt_at TEXT,
    last_refresh_success_at TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE chain_snapshots (
    id INTEGER PRIMARY KEY,
    underlying TEXT NOT NULL,
    quote_time TEXT NOT NULL,
    expiration_date TEXT NOT NULL,
    option_type TEXT NOT NULL CHECK (option_type IN ('CALL','PUT')),
    strike REAL NOT NULL,
    bid REAL, ask REAL, last REAL, mark REAL,
    implied_volatility REAL,
    delta REAL, gamma REAL, theta REAL, vega REAL, rho REAL,
    open_interest INTEGER, volume INTEGER,
    in_the_money INTEGER,
    raw_payload TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(underlying, quote_time, expiration_date, option_type, strike)
);
CREATE INDEX idx_chain_lookup ON chain_snapshots (underlying, expiration_date, option_type, strike);
CREATE INDEX idx_chain_quote_time ON chain_snapshots (underlying, quote_time);

CREATE TABLE signals (
    id INTEGER PRIMARY KEY,
    signal_id TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL CHECK (source IN ('AI','RULE','MANUAL')),
    strategy_type TEXT NOT NULL,             -- VERTICAL_SPREAD | IRON_CONDOR | DEFINED_RISK_DIRECTIONAL
    underlying TEXT NOT NULL,
    expiration_date TEXT NOT NULL,
    direction TEXT,
    thesis TEXT,
    confidence REAL,
    proposed_payload TEXT NOT NULL,          -- JSON: legs, target debit/credit, etc.
    status TEXT NOT NULL CHECK (status IN ('PENDING','APPROVED','REJECTED','EXPIRED','EXECUTED')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE risk_events (
    id INTEGER PRIMARY KEY,
    signal_id INTEGER REFERENCES signals(id),
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    decision TEXT NOT NULL CHECK (decision IN ('APPROVE','REJECT')),
    reason_code TEXT NOT NULL,               -- e.g. NAKED_FORBIDDEN, MAX_LOSS_EXCEEDED, DAILY_DD_BREAKER
    reason_text TEXT NOT NULL,
    rule_results_json TEXT NOT NULL,         -- per-rule pass/fail snapshot
    max_loss REAL,
    position_size_limit REAL,
    approved_quantity INTEGER,
    correlation_bucket TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_risk_events_account_time ON risk_events (account_id, created_at);

CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    signal_id INTEGER REFERENCES signals(id),
    risk_event_id INTEGER NOT NULL REFERENCES risk_events(id),  -- NOT NULL on purpose
    broker_order_id TEXT UNIQUE,
    client_order_id TEXT NOT NULL UNIQUE,    -- idempotency key
    strategy_type TEXT NOT NULL,
    underlying TEXT NOT NULL,
    order_status TEXT NOT NULL,              -- PENDING_SUBMISSION, WORKING, FILLED, CANCELED, REJECTED, EXPIRED
    intent TEXT NOT NULL CHECK (intent IN ('OPEN','CLOSE','ADJUST')),
    price_limit REAL,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    defined_risk INTEGER NOT NULL CHECK (defined_risk = 1),     -- hard schema-level guarantee
    max_loss REAL NOT NULL CHECK (max_loss >= 0),
    order_payload TEXT NOT NULL,
    submitted_at TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_orders_account_status ON orders (account_id, order_status);

CREATE TABLE fills (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    broker_fill_id TEXT NOT NULL UNIQUE,
    filled_quantity INTEGER NOT NULL,
    fill_price REAL NOT NULL,
    occurred_at TEXT NOT NULL,
    raw_payload TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE positions (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    broker_position_id TEXT,
    underlying TEXT NOT NULL,
    strategy_type TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('OPEN','CLOSED','PENDING_CLOSE')),
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    entry_cost REAL,
    current_mark REAL,
    max_profit REAL,
    max_loss REAL NOT NULL CHECK (max_loss >= 0),
    defined_risk INTEGER NOT NULL CHECK (defined_risk = 1),
    legs_json TEXT NOT NULL,
    last_reconciled_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_positions_account_status ON positions (account_id, status);

CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY,
    event_type TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT,
    correlation_id TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_audit_log_correlation ON audit_log (correlation_id, created_at);
```

---

## Core Contracts (pseudo-code)

```python
# broker/base.py
class BrokerClient(Protocol):
    async def get_accounts(self) -> list[AccountSummary]: ...
    async def get_account_snapshot(self, account_hash: str) -> AccountSnapshot: ...
    async def get_positions(self, account_hash: str) -> list[BrokerPosition]: ...
    async def get_option_chain(self, req: OptionChainRequest) -> NormalizedOptionChain: ...
    async def submit_order(self, req: OrderSubmission) -> BrokerOrderAck: ...
    async def get_order(self, account_hash: str, broker_order_id: str) -> BrokerOrderStatus: ...
    async def cancel_order(self, account_hash: str, broker_order_id: str) -> None: ...

# broker/schwab/oauth.py
class SchwabOAuthClient:
    AUTHORIZE_URL = "https://api.schwabapi.com/v1/oauth/authorize"
    TOKEN_URL     = "https://api.schwabapi.com/v1/oauth/token"
    async def build_pkce_authorize_url(self, state: str) -> tuple[str, str]: ...   # returns (url, code_verifier)
    async def exchange_code_for_tokens(self, code: str, redirect_uri: str, verifier: str) -> TokenBundle: ...
    async def refresh_tokens(self, refresh_token: SecretStr) -> TokenBundle: ...

# broker/schwab/client.py
class SchwabApiClient(BrokerClient):
    async def _request(self, method, path, *, retry_on_401=True, **kwargs):
        # 1. attach Bearer access token
        # 2. send via httpx.AsyncClient
        # 3. on 401 + retry_on_401:
        #      acquire single-flight refresh lock
        #      refresh tokens, persist new bundle
        #      retry exactly once with retry_on_401=False
        # 4. on non-2xx -> BrokerHttpError(status, redacted_body, correlation_id)

    async def get_option_chain(self, req):
        # GET /marketdata/v1/chains
        # params: symbol, contractType=ALL, includeUnderlyingQuote=TRUE,
        #         strategy=SINGLE, fromDate, toDate, strikeCount
        return mappers.normalize_chain(raw)

# risk/engine.py
class RiskEngine:
    def __init__(self, rules: list[RiskRule], policies: RiskPolicies): ...
    def evaluate_signal(self, ctx: RiskContext) -> RiskDecision:
        # Pure deterministic. No I/O. Reject if ANY of:
        #   - structure not in {VERTICAL_SPREAD, IRON_CONDOR, DEFINED_RISK_DIRECTIONAL}
        #   - any leg short without a defining long leg in same expiry/underlying
        #   - max_loss > policies.max_risk_per_trade_pct * account.nlv
        #   - daily P&L drawdown breaker active
        #   - weekly drawdown breaker active
        #   - open positions count >= policies.max_positions
        #   - per-underlying allocation > policies.max_underlying_allocation_pct
        # Otherwise approve with bounded quantity, attach RuleResult[] for audit.

# services/order_service.py
async def submit_signal_for_execution(signal, account, broker, risk_engine, repo) -> OrderRecord:
    decision = risk_engine.evaluate_signal(build_context(signal, account, repo))
    risk_event = await repo.risk_events.persist(decision, signal, account)
    if decision.decision == "REJECT":
        await repo.signals.mark_rejected(signal.id, risk_event.id)
        return None
    coid = make_client_order_id(signal, decision)        # deterministic, idempotent
    order = await repo.orders.create_pending(signal, decision, risk_event, coid)
    ack = await broker.submit_order(build_submission(order))    # paper or live per settings
    await repo.orders.attach_broker_id(order.id, ack.broker_order_id, status=ack.status)
    await repo.audit.log("order.submitted", entity="order", entity_id=order.id, payload=...)
    return order
```

---

## FastAPI App Skeleton

```python
def create_app() -> FastAPI:
    app = FastAPI(title="Darth Schwader", lifespan=lifespan)
    for r in (health, status, broker, chains, positions, orders, signals, risk, admin):
        app.include_router(r.router, prefix="/api/v1")
    app.include_router(ui.routes.router)                        # serves "/" + HTMX partials
    app.mount("/static", StaticFiles(directory="src/darth_schwader/ui/static"))
    app.add_exception_handler(BrokerHttpError, broker_error_handler)
    return app

@asynccontextmanager
async def lifespan(app):
    settings = get_settings(); configure_logging(settings)
    await run_alembic_migrations(settings.database_url)
    session_factory = build_session_factory(settings)
    token_store     = SqlTokenStore(session_factory, settings.token_encryption_key)
    broker          = SchwabApiClient(settings, token_store) if not settings.paper_trading else PaperBrokerClient(...)
    risk_engine     = RiskEngine(default_rules(), RiskPolicies.from_settings(settings))
    scheduler       = build_scheduler(settings, broker, risk_engine, session_factory)
    app.state.broker, app.state.risk, app.state.sessions = broker, risk_engine, session_factory
    await bootstrap_tokens_if_present(broker, token_store)
    await reconcile_account_state(broker, session_factory)
    scheduler.start()
    try: yield
    finally: scheduler.shutdown(wait=False)
```

---

## Background Scheduler (APScheduler AsyncIO, max_instances=1, coalesce=True)

| Job | Cadence | Notes |
|---|---|---|
| `token_watchdog` | every 5 min | refresh proactively if access token < 10 min to expiry |
| `account_snapshot` | every 5 min | persist `account_snapshots` row |
| `chain_pull` (watchlist) | every 2–5 min market hours | bounded retention (rolling N hours) |
| `position_sync` | every 1 min | reconcile `positions` against broker truth |
| `eod_reconciliation` | 16:30 ET | fills, equity, expire stale signals |

Each job is wrapped with timeout, exception capture, and `audit_log` write so a single failure cannot kill the scheduler.

---

## Configuration (`pydantic-settings`)

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
    token_encryption_key: SecretStr        # Fernet key

    # Risk caps (deterministic, hardcoded ceiling)
    paper_trading: bool = True             # default ON in Phase 1
    max_risk_per_trade_pct: Decimal = Decimal("0.02")
    max_daily_drawdown_pct:  Decimal = Decimal("0.04")
    max_weekly_drawdown_pct: Decimal = Decimal("0.08")
    max_positions: int = 6
    max_underlying_allocation_pct: Decimal = Decimal("0.20")
    watchlist: list[str] = []
```

`.env` holds static config only. **Tokens never live in `.env`** — they live encrypted in `broker_tokens`. Logging filters `Authorization`, token bodies, PKCE verifier, and full account numbers.

---

## UI: FastAPI + Jinja2 + HTMX

**Layout (single-page dashboard, sticky header + 65/35 columns)**

- **Sticky header**: bot status pill (RUNNING / PAUSED / HALTED), NLV, day P&L, **Kill-Switch**.
- **Left 65%**: Active Positions grid → Signal Queue (HITL approve/reject).
- **Right 35%**: Risk Engine Log → Equity sparkline → Option Chain Explorer (collapsible).

**Component skeletons**

```html
<!-- _status_header.html -->
<header class="status-bar"
        hx-get="/api/v1/status" hx-trigger="every 5s" hx-swap="outerHTML">
  <span class="state state-{{ status|lower }}">{{ status }}</span>
  <span class="nlv mono">NLV {{ nlv | money }}</span>
  <span class="pnl mono {{ 'profit' if day_pnl >= 0 else 'loss' }}">
    {{ day_pnl | money_signed }}
  </span>
  <button class="btn-emergency"
          hx-post="/api/v1/admin/kill"
          hx-confirm="ABORT ALL OPERATIONS? Cancels all orders and attempts to flatten positions."
          data-hold-ms="1500">
    KILL
  </button>
</header>
```

```html
<!-- _positions_table.html -->
<section id="positions"
         hx-get="/api/v1/positions" hx-trigger="every 10s" hx-swap="innerHTML">
  <table class="dense tabular">
    <thead><tr>
      <th>Sym</th><th>Strategy</th><th>Exp</th><th class="num">Qty</th>
      <th class="num">Δ</th><th class="num">Γ</th><th class="num">Θ</th><th class="num">ν</th>
      <th class="num">Mark</th><th class="num">Max Loss</th><th class="num">P/L</th>
    </tr></thead>
    <tbody>
      {% for p in positions %}
      <tr class="{{ 'profit' if p.unrealized >= 0 else 'loss' }}">
        <td>{{ p.underlying }}</td><td>{{ p.strategy_type }}</td>
        <td>{{ p.nearest_expiration }}</td><td class="num">{{ p.quantity }}</td>
        <td class="num">{{ "%.2f"|format(p.delta) }}</td>
        <td class="num">{{ "%.3f"|format(p.gamma) }}</td>
        <td class="num">{{ "%.2f"|format(p.theta) }}</td>
        <td class="num">{{ "%.2f"|format(p.vega) }}</td>
        <td class="num mono">{{ p.current_mark | money }}</td>
        <td class="num mono">{{ p.max_loss | money }}</td>
        <td class="num mono">{{ p.unrealized | money_signed }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
</section>
```

**Kill-switch safety (Phase 1)**: `hx-confirm` browser-native modal **plus** a small JS hook for hold-to-confirm using `data-hold-ms`. Phase 2 graduates to a slide-to-confirm component.

**Risk surfacing**: every rejected signal is rendered in `_risk_log.html` with `reason_code`, `reason_text`, and the rule that fired. Halted state pulses a red border around the dashboard.

**Polling cadence**: header 5s, positions 10s, signals 10s, risk log 15s, chain on user action only. HTMX `hx-swap="innerHTML"` preserves scroll position. A header refresh icon triggers all sections at once.

---

## API Contract (UI ↔ Backend)

| Method | Path | Returns / Body |
|---|---|---|
| GET | `/api/v1/health` | `{"status":"ok","db":"ok","scheduler":"ok"}` |
| GET | `/api/v1/status` | `{status, circuit_breaker, nlv, day_pnl, week_pnl, last_snapshot_at, paper_trading}` |
| GET | `/api/v1/broker/oauth/start` | 302 → Schwab authorize URL (PKCE) |
| GET | `/api/v1/broker/oauth/callback?code=&state=` | exchange + persist → 302 to `/` |
| GET | `/api/v1/chains/{symbol}?from=&to=&strike_count=` | `NormalizedOptionChain` JSON |
| GET | `/api/v1/positions` | `Position[]` with Greeks, mark, unrealized |
| GET | `/api/v1/orders?status=` | `Order[]` |
| GET | `/api/v1/signals?status=` | `Signal[]` |
| POST | `/api/v1/signals/{id}/approve` | runs risk engine → submits or rejects → returns RiskDecision |
| POST | `/api/v1/signals/{id}/reject` | manual rejection with reason |
| GET | `/api/v1/risk/events?since=` | `RiskEvent[]` |
| POST | `/api/v1/admin/kill` | cancel-all-and-flatten; sets bot status HALTED |

All UI fragments served from `/ui/...` returning HTML partials (HTMX consumes them); all JSON endpoints under `/api/v1`.

---

## Testing Strategy

**Unit (pytest)**
- `test_risk_rules.py` — table-driven: naked rejection, max-loss cap, drawdown breaker, concentration cap.
- `test_chain_normalization.py` — fixture payloads → `NormalizedOptionChain`.
- `test_client_order_id.py` — same signal+decision → same coid; different inputs → different coid.
- `test_schwab_retry_refresh.py` — `respx`: 401 → refresh → retry once → success; second 401 → fail closed.

**Integration**
- `test_api_status.py` against in-memory SQLite + `respx` Schwab mock.
- `test_scheduler_jobs.py` with `freezegun` for chain-pull cadence.
- `test_reconciliation.py` simulating restart: broker has 2 open positions, local DB stale → reconcile rebuilds.

**Coverage target ≥ 80%** on `risk/`, `broker/schwab/`, `services/order_service.py` (per global rules).

---

## Implementation Steps

1. **Repo scaffold**: pyproject (uv or poetry), `src/` layout, `.env.example`, `.gitignore`, Makefile/`scripts/run_dev.sh`. *Deliverable*: `uvicorn darth_schwader.main:app` boots with `/api/v1/health` returning ok.
2. **Settings + logging**: `pydantic-settings`, structlog, token-redaction filter. *Deliverable*: tokens never appear in logs even when injected.
3. **DB layer + Alembic baseline**: SQLAlchemy models matching schema above; first migration. *Deliverable*: `alembic upgrade head` creates fresh DB.
4. **Token store**: Fernet-encrypted `broker_tokens` repo with single-flight refresh lock. *Deliverable*: unit tests for encrypt/decrypt + version bump on rotation.
5. **Schwab OAuth bootstrap**: `scripts/schwab_oauth_login.py` + `/broker/oauth/start` + `/callback`. *Deliverable*: end-to-end login persists encrypted tokens; smoke test against sandbox.
6. **Schwab client + chain normalization**: `_request` retry-once-on-401, `get_option_chain`, mappers to `NormalizedOptionChain`. *Deliverable*: integration test with recorded fixture returns Greeks/IV.
7. **Risk engine + rules**: pure functions, `RiskDecision` audit shape, hard schema-level defined-risk guarantee. *Deliverable*: 100% branch coverage on `risk/rules.py`.
8. **Order service**: deterministic `client_order_id`, mandatory `risk_event_id` FK enforcement, paper-broker stub implementing `BrokerClient`. *Deliverable*: cannot create an order without a prior approve `risk_event`.
9. **Scheduler**: APScheduler jobs (token watchdog, snapshot, chain pull, position sync). *Deliverable*: jobs visible at `/api/v1/health` extended payload; failures audited but do not crash app.
10. **UI (Jinja+HTMX)**: dashboard template, partials, `app.css`, kill-switch with hold-to-confirm, risk log surfacing rejections. *Deliverable*: `/` renders status, positions table, signals queue, risk log; polling works without scroll jump.
11. **Tests**: complete unit + integration suites; CI script in `scripts/`.
12. **Docs**: `README.md` quickstart (setup, OAuth, run, tests) + `docs/phase-1-plan.md` linking to this plan.

---

## Key Files (top of build order)

| File | Operation | Description |
|---|---|---|
| `pyproject.toml` | Create | deps + tool config |
| `src/darth_schwader/main.py` | Create | uvicorn entry |
| `src/darth_schwader/config.py` | Create | Settings (incl. risk caps) |
| `src/darth_schwader/db/models.py` | Create | SQLAlchemy ORM matching DDL above |
| `alembic/versions/0001_init.py` | Create | initial migration |
| `src/darth_schwader/broker/schwab/oauth.py` | Create | PKCE + refresh |
| `src/darth_schwader/broker/schwab/client.py` | Create | SchwabApiClient + retry-once |
| `src/darth_schwader/broker/schwab/mappers.py` | Create | normalize chain |
| `src/darth_schwader/risk/engine.py` | Create | RiskEngine + rule pipeline |
| `src/darth_schwader/services/order_service.py` | Create | sole writer to `orders` |
| `src/darth_schwader/api/routers/*.py` | Create | thin HTTP surface |
| `src/darth_schwader/ui/templates/dashboard.html` | Create | HTMX dashboard |
| `tests/unit/test_risk_rules.py` | Create | deterministic rule coverage |

---

## Risks and Mitigation

| Risk | Mitigation |
|---|---|
| Schwab API auth UX is awkward (manual PKCE flow with HTTPS callback) | One-shot `scripts/schwab_oauth_login.py` + clear README; reuse `mkcert` for local TLS |
| Refresh token race conditions (two requests both seeing 401) | Single-flight `asyncio.Lock` around refresh; second waiter re-reads new tokens after release |
| AI plug-in tempted to bypass risk engine | Type system (`SignalGenerator` returns `StrategySignal`, not `OrderSubmission`); `order_service` is the only path with execution rights |
| SQLite write contention from chain snapshots | WAL mode + bounded retention + UNIQUE constraint forces upserts; chain pulls coalesced |
| Naked-options accident | `defined_risk = 1` CHECK on `orders` and `positions` + risk-engine rule + integration test |
| Token leak via logs | Structlog redaction filter + linter rule banning `print(token)`; tokens never serialized in any API response |
| Restart leaves orphan orders | Lifespan reconciliation: pull broker open orders, match by `client_order_id`, audit any drift |
| User accidentally submits live orders during dev | `paper_trading` defaults `True`; flipping it requires explicit env change + the dashboard header shows `PAPER` badge |

---

## Clarifying Questions for Phase 2 (AI Engine)

Please answer these so Phase 2 can be planned tightly:

1. **AI substrate**: managed LLM (Anthropic Claude / OpenAI GPT-4o) for strategy reasoning over chain snapshots, or a classical/ML stack (XGBoost / lightGBM on engineered features), or hybrid (ML for direction + LLM for strategy selection)?
2. **Signal cadence**: continuous (every chain pull) or scheduled (e.g. once per market open + 30 min before close)?
3. **Universe**: which underlyings on the watchlist initially? (e.g. SPY/QQQ/IWM only? mega-caps? earnings plays?)
4. **Strategy templates**: confirm we limit Phase 2 to {vertical credit/debit spreads, iron condors, defined-risk directional (long call/put with hedge)}? Anything else now or later (calendars, butterflies, ratio defined-risk)?
5. **Hard risk caps**: confirm Phase 1 defaults — `max_risk_per_trade_pct=2%`, `max_daily_drawdown=4%`, `max_weekly_drawdown=8%`, `max_positions=6`, `max_underlying_allocation=20%`. Adjust?
6. **HITL or autonomous?** Should approved-by-risk signals auto-submit, or always wait for a human click in the Signal Queue for Phase 1?
7. **Account number sourcing**: do you already have Schwab developer credentials + an approved app with a registered HTTPS redirect URI, or do you need help with that registration first?
8. **Backtest data**: do you have or want to acquire historical option chain data (e.g. ORATS, CBOE DataShop), or is Phase 2 forward-only paper trading?
9. **Hosting**: Phase 1 stays local; Phase 3 (later) — do you intend to put this on a VPS / always-on machine? Affects token storage choice.
10. **Compliance**: any pattern-day-trader / margin / taxable-account constraints we should encode now?

---

## Phase 2 Handoff Hooks (already wired in Phase 1)

- `ai.service.SignalGenerator.generate(context) -> list[StrategySignal]` — pure function, easy to swap implementations.
- `BrokerClient` Protocol — `PaperBrokerClient` for tests/dev, `SchwabApiClient` for live.
- `risk_event_id` FK on `orders` — guarantees AI can never bypass risk audit even if a future contributor adds a new order path.

---

## SESSION_ID (for `/ccg:execute` resume)

- **CODEX_SESSION**: `019da0d7-af38-7642-8491-021060c3c77d`
- **GEMINI_SESSION**: `770af350-d30c-47bf-8347-1be13d22f9c2`
