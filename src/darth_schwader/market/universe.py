from __future__ import annotations

from collections.abc import Sequence

from darth_schwader.config import get_settings


def watchlist() -> tuple[str, ...]:
    return tuple(get_settings().watchlist)


def is_in_watchlist(symbol: str) -> bool:
    return symbol.upper() in watchlist()


def validate_universe(symbols: Sequence[str]) -> tuple[str, ...]:
    allowed = watchlist()
    normalized = tuple(symbol.upper() for symbol in symbols)
    invalid = [symbol for symbol in normalized if symbol not in allowed]
    if invalid:
        invalid_str = ", ".join(sorted(set(invalid)))
        raise ValueError(f"symbols outside configured universe: {invalid_str}")
    return normalized


class _WatchlistProxy(tuple):
    def __new__(cls):
        return super().__new__(cls, ())

    def __iter__(self):
        return iter(watchlist())

    def __contains__(self, item):
        return item in watchlist()

    def __len__(self):
        return len(watchlist())

    def __getitem__(self, index):
        return watchlist()[index]


WATCHLIST = _WatchlistProxy()


__all__ = ["WATCHLIST", "is_in_watchlist", "validate_universe", "watchlist"]
