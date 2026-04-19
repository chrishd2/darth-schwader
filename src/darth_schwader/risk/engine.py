from __future__ import annotations

from dataclasses import asdict
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from darth_schwader.ai.contracts import StrategySignal
from darth_schwader.db.models import RiskEvent
from darth_schwader.risk.models import RiskContext, RiskDecision, RuleResult
from darth_schwader.risk.rules import (
    check_account_type_compat,
    check_defined_risk_math,
    check_drawdown_breakers,
    check_dte_bounds,
    check_halted_state,
    check_liquidity,
    check_naked_gate,
    check_open_positions_cap,
    check_per_trade_cap_hard,
    check_per_trade_cap_preferred,
    check_per_underlying_concentration,
    check_settled_cash_collateral,
    check_strategy_whitelist,
    check_tier_requirement,
)
from darth_schwader.risk.sizing import compute_quantity_ceilings


class RiskEngine:
    def evaluate(
        self,
        signal: StrategySignal,
        context: RiskContext,
        override_quantity: int | None = None,
    ) -> RiskDecision:
        quantity = override_quantity if override_quantity is not None else signal.suggested_quantity
        if quantity <= 0:
            return RiskDecision(
                decision="REJECT",
                reason_code="INVALID_QUANTITY",
                reason_text="quantity must be greater than zero",
                rule_results=(),
                warnings=(),
                max_loss=Decimal("0"),
                position_size_limit=Decimal("0"),
                approved_quantity=0,
                correlation_bucket=signal.underlying,
                preferred_quantity=0,
                ceiling_quantity=0,
            )

        results: list[RuleResult] = []
        warnings: list[RuleResult] = []
        for result in (
            check_halted_state(context.state),
            check_strategy_whitelist(signal, context.policy),
            check_naked_gate(signal, context.policy),
            check_dte_bounds(signal, context.policy),
            check_account_type_compat(signal, context.account_type, context.policy),
            check_tier_requirement(signal, context.options_approval_tier, context.policy),
        ):
            results.append(result)
            if not result.passed:
                return self._reject(signal, results, warnings, result.reason_code, result.reason_text)

        math = check_defined_risk_math(signal, quantity)
        results.append(math.result)
        if not math.result.passed:
            return self._reject(signal, results, warnings, math.result.reason_code, math.result.reason_text)

        preferred_qty, ceiling_qty = compute_quantity_ceilings(math.per_contract_max_loss, context.nlv, context.policy)
        if quantity > ceiling_qty:
            reject = RuleResult(False, "OVERRIDE_EXCEEDS_CEILING", "requested quantity exceeds hard ceiling", {})
            results.append(reject)
            return self._reject(signal, results, warnings, reject.reason_code, reject.reason_text)

        ordered = (
            check_per_trade_cap_hard(math.max_loss, context.nlv, context.policy),
            check_per_trade_cap_preferred(math.max_loss, context.nlv, context.policy),
            check_per_underlying_concentration(
                signal,
                context.existing_exposure,
                context.nlv,
                context.policy,
                math.max_loss,
            ),
            check_open_positions_cap(context.open_positions_count, context.policy),
            check_drawdown_breakers(context.day_pnl_pct, context.week_pnl_pct, context.policy),
            check_settled_cash_collateral(signal, math.required_collateral, context.settled_cash),
            check_liquidity(signal, context.leg_quotes),
        )
        for result in ordered:
            if result.reason_code.startswith("PREFERRED_") and result.reason_code.endswith("EXCEEDED"):
                warnings.append(result)
                continue
            results.append(result)
            if not result.passed:
                return self._reject(signal, results, warnings, result.reason_code, result.reason_text)

        return RiskDecision(
            decision="APPROVE",
            reason_code="APPROVED",
            reason_text="all deterministic risk checks passed",
            rule_results=tuple(results),
            warnings=tuple(warnings),
            max_loss=math.max_loss,
            position_size_limit=context.policy.max_risk_per_trade_pct * context.nlv,
            approved_quantity=quantity,
            correlation_bucket=signal.underlying,
            preferred_quantity=preferred_qty,
            ceiling_quantity=ceiling_qty,
        )

    async def persist_decision(
        self,
        session: AsyncSession,
        signal_id: int,
        account_id: int,
        decision: RiskDecision,
    ) -> RiskEvent:
        row = RiskEvent(
            signal_id=signal_id,
            account_id=account_id,
            decision=decision.decision,
            reason_code=decision.reason_code,
            reason_text=decision.reason_text,
            rule_results_json=[asdict(result) for result in decision.rule_results],
            warnings_json=[asdict(warning) for warning in decision.warnings] or None,
            max_loss=decision.max_loss,
            position_size_limit=decision.position_size_limit,
            approved_quantity=decision.approved_quantity,
            correlation_bucket=decision.correlation_bucket,
        )
        session.add(row)
        await session.flush()
        return row

    def _reject(
        self,
        signal: StrategySignal,
        results: list[RuleResult],
        warnings: list[RuleResult],
        reason_code: str,
        reason_text: str,
    ) -> RiskDecision:
        return RiskDecision(
            decision="REJECT",
            reason_code=reason_code,
            reason_text=reason_text,
            rule_results=tuple(results),
            warnings=tuple(warnings),
            max_loss=Decimal("0"),
            position_size_limit=Decimal("0"),
            approved_quantity=0,
            correlation_bucket=signal.underlying,
            preferred_quantity=0,
            ceiling_quantity=0,
        )


__all__ = ["RiskEngine"]
