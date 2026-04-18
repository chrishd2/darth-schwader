from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from darth_schwader.api.deps import get_session
from darth_schwader.db.models import ChainSnapshot

router = APIRouter(tags=["chains"])


@router.get("/chains/{underlying}")
async def latest_chain(
    underlying: str,
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, object]]:
    rows = await session.scalars(
        select(ChainSnapshot)
        .where(ChainSnapshot.underlying == underlying.upper())
        .order_by(ChainSnapshot.quote_time.desc())
        .limit(50)
    )
    return [
        {
            "underlying": row.underlying,
            "quote_time": row.quote_time.isoformat(),
            "expiration_date": row.expiration_date.isoformat(),
            "strike": str(row.strike),
            "option_type": row.option_type,
            "mark": str(row.mark) if row.mark is not None else None,
            "iv": str(row.implied_volatility) if row.implied_volatility is not None else None,
        }
        for row in rows
    ]


@router.post("/chains/{underlying}/refresh")
async def refresh_chain(underlying: str, request: Request) -> dict[str, object]:
    chain_service = request.app.state.chain_service
    count = await chain_service.pull(underlying.upper())
    return {"underlying": underlying.upper(), "contracts": count}


__all__ = ["router"]
