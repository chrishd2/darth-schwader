from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from darth_schwader.api.deps import get_runtime_settings, get_session
from darth_schwader.broker.factory import LIVE_BROKER_CAPABILITIES
from darth_schwader.config import Settings
from darth_schwader.db.models import AuditLog, RiskPolicyOverride
from darth_schwader.logging import get_logger
from darth_schwader.risk.policies import EffectivePolicy
from darth_schwader.services.readiness import (
    ReadinessCheck,
    ReadinessError,
    ReadinessReport,
    assert_live_readiness,
)

_RUNTIME_UPDATABLE_KEYS: frozenset[str] = frozenset(
    {
        "hitl_required",
        "allow_naked",
        "max_risk_per_trade_pct",
        "preferred_max_risk_per_trade_pct",
        "max_daily_drawdown_pct",
        "max_weekly_drawdown_pct",
        "max_positions",
        "max_underlying_allocation_pct",
        "min_dte_days",
        "max_dte_days",
        "auto_execute_confidence_threshold",
        "auto_execute_consent_live",
    }
)

router = APIRouter(tags=["settings"])

_logger = get_logger(__name__)

_MODE_CONFIRM_TOKEN = "SWITCH_MODE"
_LIVE_CONFIRM_TOKEN = "EXECUTE_LIVE"
_LIVE_CONFIRM_FIELD = "live_confirm"
_LIVE_CONFIRM_VALUE = "EXECUTE LIVE"
_NAKED_CONFIRM_TOKEN = "CONFIRM"
_PERSISTED_KEY_BLOCKLIST: frozenset[str] = frozenset({_LIVE_CONFIRM_FIELD})

_TRUE_LITERALS = frozenset({"true", "1", "yes", "on"})
_FALSE_LITERALS = frozenset({"false", "0", "no", "off", ""})


def _coerce_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _TRUE_LITERALS:
            return True
        if normalized in _FALSE_LITERALS:
            return False
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"expected boolean value, got {value!r}",
    )


@router.get("/settings")
async def settings_view(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_runtime_settings),
) -> dict[str, object]:
    effective = await EffectivePolicy.load(session, settings)
    payload: dict[str, object] = asdict(effective)
    payload["paper_trading"] = settings.paper_trading
    payload["hitl_required"] = settings.hitl_required
    payload["auto_execute_confidence_threshold"] = str(
        settings.auto_execute_confidence_threshold
    )
    payload["auto_execute_consent_live"] = settings.auto_execute_consent_live
    return payload


def _serialize_readiness(report: ReadinessReport) -> dict[str, object]:
    return {
        "code": "READINESS_FAILED",
        "passed": report.passed,
        "checks": [_serialize_check(check) for check in report.checks],
    }


def _serialize_check(check: ReadinessCheck) -> dict[str, object]:
    return {
        "name": check.name,
        "passed": check.passed,
        "reason_code": check.reason_code,
        "reason_text": check.reason_text,
        "evidence": check.evidence,
    }


@router.put("/settings")
async def update_settings(
    body: dict[str, object],
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_runtime_settings),
    x_confirm: str | None = Header(default=None, alias="X-Confirm"),
) -> dict[str, str]:
    wants_naked = "allow_naked" in body and _coerce_bool(body["allow_naked"])
    if wants_naked and x_confirm != _NAKED_CONFIRM_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"X-Confirm: {_NAKED_CONFIRM_TOKEN} is required to enable allow_naked",
        )

    mode_change_requested = False
    requested_paper_trading: bool | None = None
    if "paper_trading" in body:
        requested_paper_trading = _coerce_bool(body["paper_trading"])
        mode_change_requested = requested_paper_trading != settings.paper_trading
    going_live = mode_change_requested and requested_paper_trading is False
    if mode_change_requested and x_confirm != _MODE_CONFIRM_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"X-Confirm: {_MODE_CONFIRM_TOKEN} is required to change paper_trading"
            ),
        )
    if going_live and body.get(_LIVE_CONFIRM_FIELD) != _LIVE_CONFIRM_VALUE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"field '{_LIVE_CONFIRM_FIELD}' must equal '{_LIVE_CONFIRM_VALUE}' "
                "to flip to live"
            ),
        )

    persisted_body = {
        key: value for key, value in body.items() if key not in _PERSISTED_KEY_BLOCKLIST
    }
    merged = settings.model_dump()
    merged.update(persisted_body)
    validated = Settings.model_validate(merged)

    if going_live:
        try:
            await assert_live_readiness(
                session=session,
                settings=validated,
                live_capabilities=LIVE_BROKER_CAPABILITIES,
            )
        except ReadinessError as exc:
            _logger.warning(
                "live_readiness_failed",
                reason_codes=[check.reason_code for check in exc.report.failing],
            )
            raise HTTPException(
                status_code=status.HTTP_412_PRECONDITION_FAILED,
                detail=_serialize_readiness(exc.report),
            ) from exc

    hot_update = {
        key: getattr(validated, key)
        for key in _RUNTIME_UPDATABLE_KEYS
        if key in persisted_body
    }
    if hot_update:
        current = request.app.state.settings
        updated_runtime = current.model_copy(update=hot_update)
        request.app.state.settings = updated_runtime

    for key, value in persisted_body.items():
        row = await session.scalar(
            select(RiskPolicyOverride).where(RiskPolicyOverride.key == key)
        )
        if row is None:
            row = RiskPolicyOverride(key=key, value=str(value), updated_by="api")
            session.add(row)
        else:
            row.value = str(value)
            row.updated_by = "api"

    if mode_change_requested and requested_paper_trading is not None:
        session.add(
            AuditLog(
                event_type="MODE_CHANGE_REQUESTED",
                entity_type="system",
                entity_id="paper_trading",
                correlation_id=None,
                payload_json={
                    "from": settings.paper_trading,
                    "to": requested_paper_trading,
                },
            )
        )
        _logger.warning(
            "mode_change_requested",
            current=settings.paper_trading,
            requested=requested_paper_trading,
        )

    await session.commit()
    return {
        "status": "ok",
        "restart_required": "true" if mode_change_requested else "false",
    }


__all__ = ["router"]
