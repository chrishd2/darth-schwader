from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator

from darth_schwader.db.repositories.watchlist import WatchlistRepository
from darth_schwader.domain.asset_types import AssetType

router = APIRouter(tags=["watchlist"])


class WatchlistEntryOut(BaseModel):
    id: int
    symbol: str
    asset_type: AssetType
    strategies: list[str]
    active: bool
    notes: str | None = None


class WatchlistEntryCreate(BaseModel):
    symbol: str = Field(min_length=1, max_length=16)
    asset_type: AssetType
    strategies: list[str] = Field(default_factory=list)
    active: bool = True
    notes: str | None = None

    @field_validator("symbol")
    @classmethod
    def _symbol_upper(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("symbol must not be blank")
        return normalized


class WatchlistEntryUpdate(BaseModel):
    strategies: list[str] | None = None
    active: bool | None = None
    notes: str | None = None


def _to_out(entry: object) -> WatchlistEntryOut:
    return WatchlistEntryOut.model_validate(entry, from_attributes=True)


def _repo(request: Request) -> WatchlistRepository:
    return WatchlistRepository(request.app.state.session_factory)


@router.get("/watchlist", response_model=list[WatchlistEntryOut])
async def list_watchlist(
    request: Request, active_only: bool = False
) -> list[WatchlistEntryOut]:
    entries = await _repo(request).list_all(active_only=active_only)
    return [_to_out(entry) for entry in entries]


@router.post(
    "/watchlist",
    response_model=WatchlistEntryOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_watchlist_entry(
    payload: WatchlistEntryCreate, request: Request
) -> WatchlistEntryOut:
    repo = _repo(request)
    existing = await repo.find(payload.symbol, payload.asset_type)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"watchlist entry for {payload.symbol}/{payload.asset_type.value} "
                "already exists"
            ),
        )
    entry = await repo.create(
        symbol=payload.symbol,
        asset_type=payload.asset_type,
        strategies=payload.strategies,
        active=payload.active,
        notes=payload.notes,
    )
    return _to_out(entry)


@router.patch("/watchlist/{entry_id}", response_model=WatchlistEntryOut)
async def update_watchlist_entry(
    entry_id: int, payload: WatchlistEntryUpdate, request: Request
) -> WatchlistEntryOut:
    entry = await _repo(request).update(
        entry_id,
        strategies=payload.strategies,
        active=payload.active,
        notes=payload.notes,
    )
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"watchlist entry {entry_id} not found",
        )
    return _to_out(entry)


@router.delete("/watchlist/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_watchlist_entry(entry_id: int, request: Request) -> None:
    deleted = await _repo(request).delete(entry_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"watchlist entry {entry_id} not found",
        )


__all__ = ["router"]
