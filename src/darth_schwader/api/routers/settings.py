from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from darth_schwader.api.deps import get_runtime_settings, get_session
from darth_schwader.config import Settings
from darth_schwader.db.models import AuditLog, RiskPolicyOverride
from darth_schwader.logging import get_logger
from darth_schwader.risk.policies import EffectivePolicy

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
    }
)

router = APIRouter(tags=["settings"])

_logger = get_logger(__name__)

_MODE_CONFIRM_TOKEN = "SWITCH_MODE"
_NAKED_CONFIRM_TOKEN = "CONFIRM"

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
    return payload


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
    if mode_change_requested and x_confirm != _MODE_CONFIRM_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"X-Confirm: {_MODE_CONFIRM_TOKEN} is required to change paper_trading"
            ),
        )

    merged = settings.model_dump()
    merged.update(body)
    validated = Settings.model_validate(merged)

    hot_update = {key: getattr(validated, key) for key in _RUNTIME_UPDATABLE_KEYS if key in body}
    if hot_update:
        current = request.app.state.settings
        updated_runtime = current.model_copy(update=hot_update)
        request.app.state.settings = updated_runtime

    for key, value in body.items():
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
