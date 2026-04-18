from __future__ import annotations

from collections.abc import Sequence

from darth_schwader.config import get_settings

WATCHLIST: tuple[str, ...] = tuple(get_settings().watchlist)


def is_in_watchlist(symbol: str) -> bool:
    return symbol.upper() in WATCHLIST


def validate_universe(symbols: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(symbol.upper() for symbol in symbols)
    invalid = [symbol for symbol in normalized if symbol not in WATCHLIST]
    if invalid:
        invalid_str = ", ".join(sorted(set(invalid)))
        raise ValueError(f"symbols outside configured universe: {invalid_str}")
    return normalized


__all__ = ["WATCHLIST", "is_in_watchlist", "validate_universe"]
