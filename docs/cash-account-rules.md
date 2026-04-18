# Cash Account Rules

Because the account is cash and sub-$25k:

- PDT rules do not apply.
- No margin means no margin collateral model.
- Defined-risk spreads can still work when the broker holds the long leg as collateral.
- CSPs require full strike × 100 × contracts in cash.
- Covered calls require 100 shares per contract.
- Debit calendars are treated as defined-risk cash trades.
- T+1 settlement means the bot must separate settled from unsettled cash.

## Options approval

- Tier 2 is the minimum target for long options, covered calls, cash-secured puts, and debit spreads.
- Tier 3 is typically required for iron condors and credit spread structures in a cash account.

## Naked options

- `allow_naked` defaults to `False`.
- Cash-account naked calls are not economically practical.
- Cash-account naked puts collapse into CSP semantics because full cash collateral still has to be reserved.
- The API requires `X-Confirm: CONFIRM` before enabling naked strategies in settings.

## T+1 settlement examples

### Example 1 — Sale proceeds are unsettled

- Monday: you sell an option for `$400`.
- Monday after fill: buying power may appear larger, but the new cash is unsettled.
- Tuesday: the `$400` becomes settled and can be reused safely.

### Example 2 — Collateral locks and releases

- Account starts with `$5,000` settled.
- A new CSP reserves `$2,000`; settled availability drops to `$3,000`.
- The order is cancelled and the lock is released; settled availability returns to `$5,000`.

### Example 3 — Avoiding a good-faith violation

- Monday morning: `$1,000` settled.
- Monday afternoon: another trade closes for a gain, but the proceeds are unsettled until Tuesday.
- The risk engine still treats only the original `$1,000` as available collateral on Monday.

## Operational note

Back up the SQLite `data/` directory. Phase 1 uses local persistence and assumes the operator is responsible for local recovery.
