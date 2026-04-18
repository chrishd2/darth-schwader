from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, Header
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from darth_schwader.api.deps import get_runtime_settings, get_session
from darth_schwader.config import Settings
from darth_schwader.db.models import RiskPolicyOverride
from darth_schwader.risk.policies import EffectivePolicy

router = APIRouter(tags=["settings"])


@router.get("/settings")
async def settings_view(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_runtime_settings),
) -> dict[str, object]:
    effective = await EffectivePolicy.load(session, settings)
    return effective.__dict__


@router.put("/settings")
async def update_settings(
    body: dict[str, object],
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_runtime_settings),
    x_confirm: str | None = Header(default=None, alias="X-Confirm"),
) -> dict[str, str]:
    if body.get("allow_naked") is True and x_confirm != "CONFIRM":
        raise ValueError("X-Confirm: CONFIRM is required to enable allow_naked")

    merged = settings.model_dump()
    merged.update(body)
    Settings.model_validate(merged)

    for key, value in body.items():
        row = await session.scalar(select(RiskPolicyOverride).where(RiskPolicyOverride.key == key))
        if row is None:
            row = RiskPolicyOverride(key=key, value=str(value), updated_by="api")
            session.add(row)
        else:
            row.value = str(value)
            row.updated_by = "api"
    await session.commit()
    return {"status": "ok"}


__all__ = ["router"]
