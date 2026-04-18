from __future__ import annotations

from enum import StrEnum


class AssetType(StrEnum):
    EQUITY = "EQUITY"
    ETF = "ETF"
    FUTURE = "FUTURE"
    OPTION_UNDERLYING = "OPTION_UNDERLYING"


__all__ = ["AssetType"]
