# Implementation Plan: Darth Schwader — Phase 1 (v3 delta)

> v3 is a focused delta on top of v2. **Execute v2 + v3 together** — v3 does not restate unchanged sections.
> Source: `.claude/plan/darth-schwader-phase-1-v2.md`

---

## v3 Change Summary

User decision: **per-trade risk ceiling is adjustable in settings AND per individual trade**. Default behaves per recommendation (a):
- **Hard ceiling** (`max_risk_per_trade_pct`): default 25%, editable in settings. Any trade above this is **rejected** by the risk engine.
- **Soft preferred cap** (`preferred_max_risk_per_trade_pct`): default 5%, editable in settings. AI sizes toward this. Trades between preferred and ceiling are **allowed but warned** in the UI.
- **Per-trade override**: in the HITL queue, the user can adjust quantity (and therefore $ at risk) on each signal before clicking Submit. Server re-runs risk evaluation with the override.

---

## Config diff

```diff
 class Settings(BaseSettings):
     ...
-    max_risk_per_trade_pct: Decimal = Decimal("0.25")
+    # Hard ceiling — risk engine REJECTS any trade above this
+    max_risk_per_trade_pct: Decimal = Decimal("0.25")
+    # Soft preferred — AI aims to size at-or-under this; UI warns above it
+    preferred_max_risk_per_trade_pct: Decimal = Decimal("0.05")
```

Both values are editable via `PUT /api/v1/settings` (already wired in v2 via `risk_policy_overrides`). Validation: `0 < preferred ≤ hard ≤ 0.50`. The 0.50 outer guard is a hardcoded sanity rail (a single options trade losing more than half the account in one shot is almost never the intent).

---

## Schema diff

```diff
 -- signals: capture both AI-suggested and AI-preferred sizing for audit
 ALTER TABLE signals ADD COLUMN suggested_quantity INTEGER;        -- what AI proposed
 ALTER TABLE signals ADD COLUMN suggested_max_loss REAL;
 ALTER TABLE signals ADD COLUMN preferred_quantity INTEGER;        -- AI's size aiming at preferred cap
 ALTER TABLE signals ADD COLUMN ceiling_quantity INTEGER;          -- max size allowed by hard ceiling

 -- risk_events: separate warnings from reject reasons
 ALTER TABLE risk_events ADD COLUMN warnings_json TEXT;            -- nullable JSON array

 -- orders: audit when human overrode AI sizing
 ALTER TABLE orders ADD COLUMN quantity_override_by_human INTEGER NOT NULL DEFAULT 0
     CHECK (quantity_override_by_human IN (0,1));
 ALTER TABLE orders ADD COLUMN size_pct_of_nlv REAL;               -- recorded at submit time
```

Migration: new file `alembic/versions/0002_per_trade_size_override.py`.

---

## Risk Engine diff

Rule #7 (per-trade cap) split into two rules:

```python
# rules.py — replace the single PER_TRADE_CAP rule with these two

class PreferredRiskWarning(RiskRule):
    """Warning, not a reject. Captured in risk_events.warnings_json."""
    def evaluate(self, ctx: RiskContext) -> RuleResult:
        if ctx.proposed_max_loss > ctx.policies.preferred_max_risk_per_trade_pct * ctx.account.nlv:
            return RuleResult(
                passed=True,                          # not a reject
                reason_code="PREFERRED_RISK_EXCEEDED",
                reason_text=(
                    f"Trade max_loss "
                    f"${ctx.proposed_max_loss:.0f} "
                    f"({ctx.proposed_max_loss / ctx.account.nlv:.1%} of NLV) "
                    f"exceeds preferred cap "
                    f"({ctx.policies.preferred_max_risk_per_trade_pct:.0%})"
                ),
                severity="WARNING",
                evidence={"max_loss": ctx.proposed_max_loss, "nlv": ctx.account.nlv},
            )
        return RuleResult(passed=True, reason_code="PREFERRED_RISK_OK", severity="INFO")


class HardRiskCeiling(RiskRule):
    """Reject if above the hard ceiling. Cannot be overridden per trade."""
    def evaluate(self, ctx: RiskContext) -> RuleResult:
        cap = ctx.policies.max_risk_per_trade_pct * ctx.account.nlv
        if ctx.proposed_max_loss > cap:
            return RuleResult(
                passed=False,
                reason_code="HARD_RISK_CEILING_EXCEEDED",
                reason_text=(
                    f"Trade max_loss ${ctx.proposed_max_loss:.0f} > hard ceiling "
                    f"${cap:.0f} ({ctx.policies.max_risk_per_trade_pct:.0%} of NLV)"
                ),
                severity="REJECT",
                evidence={"max_loss": ctx.proposed_max_loss, "ceiling": cap},
            )
        return RuleResult(passed=True, reason_code="HARD_RISK_CEILING_OK", severity="INFO")
```

`RiskDecision` now carries both `rejections: list[RuleResult]` and `warnings: list[RuleResult]`. `decision == "APPROVE"` only when `rejections` is empty; warnings do not block approval but **must** be displayed in the UI.

---

## AI / Signal Generator diff

```python
# ai/service.py — when generating a signal, compute three sizes

def size_signal(strategy_legs, account, policies) -> SignalSizing:
    leg_max_loss_per_contract = strategy_max_loss_per_contract(strategy_legs)
    nlv = account.nlv

    preferred_dollar_budget = policies.preferred_max_risk_per_trade_pct * nlv
    ceiling_dollar_budget   = policies.max_risk_per_trade_pct           * nlv

    preferred_qty = floor(preferred_dollar_budget / leg_max_loss_per_contract)
    ceiling_qty   = floor(ceiling_dollar_budget   / leg_max_loss_per_contract)
    suggested_qty = max(1, preferred_qty)         # AI's default suggestion = preferred

    return SignalSizing(
        suggested_quantity = suggested_qty,
        suggested_max_loss = suggested_qty * leg_max_loss_per_contract,
        preferred_quantity = preferred_qty,
        ceiling_quantity   = ceiling_qty,
    )
```

Suggested = AI default (sized to preferred cap). Preferred = same as suggested when ≥ 1 contract. Ceiling = max integer contracts the hard cap permits — shown to the user as a "maximum allowed" reference.

If `preferred_qty == 0` (preferred budget too small for even one contract), suggested falls back to 1 contract — but only if that 1 contract also fits under the hard ceiling. If it doesn't, the signal is auto-rejected with `MIN_QUANTITY_EXCEEDS_CEILING` (the trade's per-contract risk is so large that even one contract breaks the rules).

---

## API diff

```diff
- POST /api/v1/signals/{id}/submit
+ POST /api/v1/signals/{id}/submit
+   body (all optional): {
+     "quantity_override": int,        # human-set size; defaults to signal.suggested_quantity
+     "limit_price_override": float,   # optional; defaults to AI's target
+     "acknowledge_warnings": bool     # required true if any warnings present
+   }
```

Server flow on `/submit`:
1. Look up signal; reject if status ≠ `APPROVED_AWAITING_HITL`.
2. Apply override (or use suggested).
3. Re-run `RiskEngine.evaluate_signal` with the override quantity.
4. If new evaluation rejects → return 422 with the reject reasons (e.g. user tried to size above ceiling). Signal stays in `APPROVED_AWAITING_HITL`.
5. If warnings present and `acknowledge_warnings != true` → return 412 Precondition Failed with the warnings; UI must re-prompt.
6. Otherwise persist new `risk_event` (re-evaluation), then proceed to `order_service.submit_signal_for_execution(...)`.

This guarantees: **no order is submitted without a fresh `risk_event` row matching the actual final quantity**, even when humans override.

---

## UI diff (Signal Queue partial)

```html
<!-- _signals_queue.html — per row when status = APPROVED_AWAITING_HITL -->
<tr class="signal-row {{ 'has-warning' if warnings }}">
  <td>{{ underlying }}</td>
  <td>{{ strategy_type }}</td>
  <td class="num">{{ ai_thesis_short }}</td>

  <!-- Sizing controls -->
  <td class="sizing">
    <label>Qty
      <input type="number"
             name="quantity_override"
             min="1"
             max="{{ ceiling_quantity }}"
             value="{{ suggested_quantity }}"
             data-per-contract-loss="{{ per_contract_max_loss }}"
             data-nlv="{{ nlv }}"
             data-preferred-pct="{{ preferred_pct }}"
             data-ceiling-pct="{{ ceiling_pct }}"
             oninput="recomputeRiskBadge(this)" />
    </label>
    <span class="risk-badge" id="badge-{{ id }}">
      {{ suggested_max_loss | money }} ({{ suggested_pct_of_nlv }}% NLV)
    </span>
    <small class="muted">
      AI: {{ suggested_quantity }}  ·  Preferred: {{ preferred_quantity }}  ·  Max: {{ ceiling_quantity }}
    </small>
  </td>

  <!-- Warnings (if any) -->
  {% if warnings %}
  <td class="warnings">
    {% for w in warnings %}
      <div class="warn">⚠ {{ w.reason_text }}</div>
    {% endfor %}
    <label>
      <input type="checkbox" name="acknowledge_warnings" /> I acknowledge
    </label>
  </td>
  {% endif %}

  <td class="actions">
    <button class="btn-submit"
            hx-post="/api/v1/signals/{{ id }}/submit"
            hx-include="closest tr"
            hx-confirm="Submit {{ strategy_type }} on {{ underlying }} — qty will be re-evaluated by risk engine."
            data-hold-ms="1500">
      Submit
    </button>
    <button class="btn-reject"
            hx-post="/api/v1/signals/{{ id }}/reject">
      Reject
    </button>
  </td>
</tr>
```

```js
// static/js/risk-badge.js — pure DOM, no framework
function recomputeRiskBadge(input) {
  const qty = parseInt(input.value || "0", 10);
  const perContract = parseFloat(input.dataset.perContractLoss);
  const nlv = parseFloat(input.dataset.nlv);
  const preferredPct = parseFloat(input.dataset.preferredPct);
  const ceilingPct = parseFloat(input.dataset.ceilingPct);

  const dollars = qty * perContract;
  const pctOfNlv = nlv > 0 ? (dollars / nlv) * 100 : 0;
  const badge = input.parentElement.parentElement.querySelector(".risk-badge");

  let cls = "ok";
  if (pctOfNlv > ceilingPct) cls = "blocked";
  else if (pctOfNlv > preferredPct) cls = "warn";

  badge.className = `risk-badge ${cls}`;
  badge.textContent = `$${dollars.toFixed(0)} (${pctOfNlv.toFixed(1)}% NLV)`;
}
```

CSS semantics: `.ok` neutral, `.warn` amber border, `.blocked` red — and the Submit button auto-disables when `.blocked`.

---

## Settings panel diff

```diff
  <!-- _settings_form.html -->
  <fieldset>
    <legend>Risk Caps</legend>
+   <label>Preferred per-trade cap (AI sizes here)
+     <input name="preferred_max_risk_per_trade_pct" type="number" step="0.01" min="0.01" max="0.50"
+            value="{{ s.preferred_max_risk_per_trade_pct }}" />
+   </label>
    <label>Hard per-trade ceiling (rejects above)
      <input name="max_risk_per_trade_pct" type="number" step="0.01" min="0.01" max="0.50"
             value="{{ s.max_risk_per_trade_pct }}" />
    </label>
    <!-- daily/weekly drawdown, max_positions, allocation, DTE bounds — unchanged -->
  </fieldset>
```

Server-side validator: `0 < preferred ≤ hard ≤ 0.50`. Reject the PUT with 422 and a clear message otherwise.

---

## Test additions

```text
tests/unit/
  test_signal_sizing.py
    - suggested_quantity equals preferred_quantity when budget allows
    - ceiling_quantity ≥ preferred_quantity always
    - per_contract_max_loss > hard_cap → MIN_QUANTITY_EXCEEDS_CEILING auto-reject
  test_risk_warnings.py
    - 5% < proposed_max_loss/NLV ≤ 25% → APPROVE with PREFERRED_RISK_EXCEEDED warning
    - proposed_max_loss/NLV > 25% → REJECT with HARD_RISK_CEILING_EXCEEDED
  test_settings_validation.py
    - preferred > hard → 422
    - hard > 0.50 → 422

tests/integration/
  test_api_signals_submit_override.py
    - submit with quantity_override > ceiling → 422 + reject reason
    - submit with override in warning band, no ack → 412
    - submit with override + acknowledge_warnings=true → 200 + new risk_event row + new order row
    - audit_log contains override flag + final size
```

---

## Risk Register update

| # | Risk | Mitigation |
|---|---|---|
| 1 (revised) | 25% per-trade ceiling is adjustable; user could push it higher in a hot moment | Outer hardcoded rail at 50% in settings validator. UI warning band makes the cost of pushing past 5% visible on every single trade. Each override is recorded in `orders.quantity_override_by_human = 1` and audited. |
| 11 (new) | User overrides AI size in the HITL queue, then ignores warnings | UI requires explicit `acknowledge_warnings` checkbox; server returns 412 without it. Audit log records every override + acknowledgement so post-hoc review is possible. |

---

## Implementation order (where this slots into the v2 plan)

This delta touches **steps 9, 10, 12, 13, 15** of the v2 build order. Concretely:

- Step 9 (`risk/`): split per-trade rule, add warnings-vs-rejections separation in `RiskDecision`.
- Step 10 (`services/order_service.py`): re-evaluate risk on submit when quantity override is present.
- Step 12 (`api/routers/signals.py`): extend `/submit` body, return 412/422 paths.
- Step 13 (`ui/templates/_signals_queue.html` + `static/js/risk-badge.js`): sizing input + live badge.
- Step 15 (tests): add the four new test files above.

No re-ordering needed; same Phase-1 scope.

---

## SESSION_ID (carry-forward)

- **CODEX_SESSION**: `019da0d7-af38-7642-8491-021060c3c77d`
- **GEMINI_SESSION**: `770af350-d30c-47bf-8347-1be13d22f9c2`

---

**Plans to execute together**: `.claude/plan/darth-schwader-phase-1-v2.md` + `.claude/plan/darth-schwader-phase-1-v3.md`
