from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from darth_schwader.ai.contracts import StrategySignal
from darth_schwader.domain.enums import StrategyType
from darth_schwader.risk.models import RuleResult
from darth_schwader.risk.policies import EffectivePolicy

_ZERO = Decimal("0")
_MULTIPLIER = Decimal("100")


@dataclass(frozen=True, slots=True)
class RiskMath:
    result: RuleResult
    per_contract_max_loss: Decimal
    max_loss: Decimal
    required_collateral: Decimal


def _ok(code: str, text: str, evidence: dict[str, object] | None = None) -> RuleResult:
    return RuleResult(True, code, text, evidence or {})


def _reject(code: str, text: str, evidence: dict[str, object] | None = None) -> RuleResult:
    return RuleResult(False, code, text, evidence or {})


def check_strategy_whitelist(signal: StrategySignal, policy: EffectivePolicy) -> RuleResult:
    allowed = {
        StrategyType.VERTICAL_SPREAD,
        StrategyType.IRON_CONDOR,
        StrategyType.DEFINED_RISK_DIRECTIONAL,
        StrategyType.CASH_SECURED_PUT,
        StrategyType.COVERED_CALL,
        StrategyType.CALENDAR_SPREAD,
    }
    if policy.allow_naked:
        allowed.update({StrategyType.NAKED_PUT, StrategyType.NAKED_CALL})
    if signal.strategy_type not in allowed:
        return _reject("STRATEGY_NOT_ALLOWED", f"{signal.strategy_type} is not permitted")
    return _ok("STRATEGY_ALLOWED", "strategy is allowed")


def check_naked_gate(signal: StrategySignal, policy: EffectivePolicy) -> RuleResult:
    if signal.strategy_type in {StrategyType.NAKED_CALL, StrategyType.NAKED_PUT} and not policy.allow_naked:
        return _reject("NAKED_DISABLED", "naked strategies are disabled")
    return _ok("NAKED_GATE_OK", "naked gate satisfied")


def check_dte_bounds(signal: StrategySignal, policy: EffectivePolicy) -> RuleResult:
    today = datetime.now(tz=UTC).date()
    dte = (signal.expiration_date - today).days
    if dte < policy.min_dte_days or dte > policy.max_dte_days:
        return _reject(
            "DTE_OUT_OF_BOUNDS",
            f"expiration {dte} days out is outside configured bounds",
            {"dte": dte},
        )
    return _ok("DTE_OK", "DTE bounds satisfied", {"dte": dte})


def check_account_type_compat(signal: StrategySignal, account_type: str, policy: EffectivePolicy) -> RuleResult:
    if account_type == "CASH" and signal.strategy_type == StrategyType.NAKED_CALL:
        return _reject("ACCOUNT_TYPE_INCOMPATIBLE", "cash accounts cannot carry naked calls")
    return _ok("ACCOUNT_TYPE_OK", "account type is compatible")


def check_tier_requirement(signal: StrategySignal, account_tier: int, policy: EffectivePolicy) -> RuleResult:
    required = 3 if signal.strategy_type == StrategyType.IRON_CONDOR else 2
    effective = min(account_tier, policy.options_approval_tier)
    if effective < required:
        return _reject(
            "INSUFFICIENT_OPTIONS_TIER",
            f"strategy requires tier {required}",
            {"required": required, "effective": effective},
        )
    return _ok("OPTIONS_TIER_OK", "options approval tier satisfied")


def check_defined_risk_math(signal: StrategySignal, proposed_quantity: int) -> RiskMath:
    if proposed_quantity <= 0:
        return RiskMath(
            result=_reject("INVALID_QUANTITY", "quantity must be greater than zero"),
            per_contract_max_loss=_ZERO,
            max_loss=_ZERO,
            required_collateral=_ZERO,
        )

    payload = signal.features_snapshot
    if "per_contract_max_loss" in payload:
        per_contract = Decimal(str(payload["per_contract_max_loss"]))
    elif signal.suggested_quantity and signal.suggested_max_loss:
        per_contract = signal.suggested_max_loss / Decimal(signal.suggested_quantity)
    else:
        return RiskMath(
            result=_reject("MISSING_RISK_MATH", "signal is missing per-contract max loss"),
            per_contract_max_loss=_ZERO,
            max_loss=_ZERO,
            required_collateral=_ZERO,
        )

    if per_contract <= _ZERO:
        return RiskMath(
            result=_reject("INVALID_MAX_LOSS", "per-contract max loss must be positive"),
            per_contract_max_loss=_ZERO,
            max_loss=_ZERO,
            required_collateral=_ZERO,
        )

    collateral = Decimal(str(payload.get("required_collateral_per_contract", per_contract))) * Decimal(
        proposed_quantity
    )
    max_loss = per_contract * Decimal(proposed_quantity)
    return RiskMath(
        result=_ok("DEFINED_RISK_OK", "defined-risk math satisfied", {"per_contract_max_loss": str(per_contract)}),
        per_contract_max_loss=per_contract,
        max_loss=max_loss,
        required_collateral=collateral,
    )


def check_per_trade_cap_hard(max_loss: Decimal, nlv: Decimal, policy: EffectivePolicy) -> RuleResult:
    cap = policy.max_risk_per_trade_pct * nlv
    if max_loss > cap:
        return _reject("HARD_RISK_CEILING_EXCEEDED", "trade exceeds hard per-trade risk ceiling")
    return _ok("HARD_RISK_CEILING_OK", "hard per-trade risk ceiling satisfied")


def check_per_trade_cap_preferred(max_loss: Decimal, nlv: Decimal, policy: EffectivePolicy) -> RuleResult:
    cap = policy.preferred_max_risk_per_trade_pct * nlv
    if max_loss > cap:
        return _ok(
            "PREFERRED_RISK_EXCEEDED",
            "trade exceeds preferred per-trade sizing target",
            {"preferred_cap": str(cap), "max_loss": str(max_loss)},
        )
    return _ok("PREFERRED_RISK_OK", "preferred per-trade target satisfied")


def check_per_underlying_concentration(
    signal: StrategySignal,
    existing_exposure: Decimal,
    nlv: Decimal,
    policy: EffectivePolicy,
    max_loss: Decimal,
) -> RuleResult:
    cap = policy.max_underlying_allocation_pct * nlv
    if existing_exposure + max_loss > cap:
        return _reject("UNDERLYING_CONCENTRATION_EXCEEDED", "per-underlying concentration cap exceeded")
    return _ok("UNDERLYING_CONCENTRATION_OK", "underlying concentration satisfied")


def check_open_positions_cap(open_count: int, policy: EffectivePolicy) -> RuleResult:
    if open_count >= policy.max_positions:
        return _reject("MAX_POSITIONS_EXCEEDED", "maximum concurrent positions exceeded")
    return _ok("MAX_POSITIONS_OK", "open position cap satisfied")


def check_drawdown_breakers(day_pnl_pct: Decimal, week_pnl_pct: Decimal, policy: EffectivePolicy) -> RuleResult:
    if day_pnl_pct <= -policy.max_daily_drawdown_pct:
        return _reject("DRAWDOWN_BREAKER_ACTIVE", "daily drawdown breaker active")
    if week_pnl_pct <= -policy.max_weekly_drawdown_pct:
        return _reject("DRAWDOWN_BREAKER_ACTIVE", "weekly drawdown breaker active")
    return _ok("DRAWDOWN_OK", "drawdown breaker not active")


def check_settled_cash_collateral(
    signal: StrategySignal,
    required_collateral: Decimal,
    settled_cash: Decimal,
) -> RuleResult:
    cash_bound = {
        StrategyType.CASH_SECURED_PUT,
        StrategyType.COVERED_CALL,
        StrategyType.CALENDAR_SPREAD,
        StrategyType.DEFINED_RISK_DIRECTIONAL,
    }
    if signal.strategy_type in cash_bound and required_collateral > settled_cash:
        return _reject("INSUFFICIENT_SETTLED_CASH", "insufficient settled cash for collateral")
    return _ok("SETTLED_CASH_OK", "settled cash requirement satisfied")


def check_liquidity(signal: StrategySignal, leg_quotes: dict[str, dict[str, Decimal]]) -> RuleResult:
    for leg in signal.legs:
        quote = leg_quotes.get(leg.occ_symbol)
        if quote is None:
            return _reject("MISSING_LEG_QUOTES", f"missing quote for {leg.occ_symbol}")
        bid = Decimal(str(quote.get("bid", "0")))
        ask = Decimal(str(quote.get("ask", "0")))
        open_interest = Decimal(str(quote.get("open_interest", "0")))
        if bid < _ZERO or ask <= _ZERO or ask < bid:
            return _reject("INVALID_LEG_QUOTES", f"invalid quote for {leg.occ_symbol}")
        mid = (bid + ask) / Decimal("2")
        if mid <= _ZERO:
            return _reject("ZERO_MID", f"zero mid price for {leg.occ_symbol}")
        if (ask - bid) / mid > Decimal("0.25"):
            return _reject("WIDE_BID_ASK", f"bid/ask spread too wide for {leg.occ_symbol}")
        if open_interest < Decimal("10"):
            return _reject("LOW_OPEN_INTEREST", f"open interest too low for {leg.occ_symbol}")
    return _ok("LIQUIDITY_OK", "liquidity gate satisfied")


def check_halted_state(state: str) -> RuleResult:
    if state.upper() == "HALTED":
        return _reject("BOT_HALTED", "bot is halted")
    return _ok("BOT_ACTIVE", "bot is active")


__all__ = [
    "RiskMath",
    "check_account_type_compat",
    "check_defined_risk_math",
    "check_drawdown_breakers",
    "check_dte_bounds",
    "check_halted_state",
    "check_liquidity",
    "check_naked_gate",
    "check_open_positions_cap",
    "check_per_trade_cap_hard",
    "check_per_trade_cap_preferred",
    "check_per_underlying_concentration",
    "check_settled_cash_collateral",
    "check_strategy_whitelist",
    "check_tier_requirement",
]
