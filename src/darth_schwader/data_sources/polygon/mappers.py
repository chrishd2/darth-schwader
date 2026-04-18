from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any

from darth_schwader.broker.schwab.mappers import normalize_occ_symbol


def _decimal(value: object | None) -> Decimal | None:
    if value in (None, ""):
        return None
    return Decimal(str(value))


def _timestamp_ms(value: object | None, fallback: date) -> datetime:
    if value in (None, ""):
        return datetime.combine(fallback, time(20, 0), tzinfo=UTC)
    return datetime.fromtimestamp(int(str(value)) / 1000, tz=UTC)


def map_option_chain_rows(
    underlying: str,
    contracts: list[dict[str, Any]],
    *,
    as_of: date,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for contract in contracts:
        details = contract.get("details", {})
        option_type = str(details.get("contract_type", "")).upper()
        expiration = date.fromisoformat(str(details["expiration_date"]))
        strike = Decimal(str(details["strike_price"]))
        greeks = contract.get("greeks", {})
        last_quote = contract.get("last_quote", {})
        day = contract.get("day", {})
        occ_symbol = str(details.get("ticker", "")).removeprefix("O:")
        if not occ_symbol:
            occ_symbol = normalize_occ_symbol(underlying.upper(), expiration.isoformat(), option_type, strike)

        rows.append(
            {
                "underlying": underlying.upper(),
                "quote_time": _timestamp_ms(last_quote.get("last_updated"), as_of),
                "expiration_date": expiration,
                "option_type": option_type,
                "strike": strike,
                "bid": _decimal(last_quote.get("bid")),
                "ask": _decimal(last_quote.get("ask")),
                "last": _decimal(day.get("close")),
                "mark": _decimal(contract.get("fmv")) or _decimal(day.get("close")),
                "implied_volatility": _decimal(contract.get("implied_volatility")),
                "delta": _decimal(greeks.get("delta")),
                "gamma": _decimal(greeks.get("gamma")),
                "theta": _decimal(greeks.get("theta")),
                "vega": _decimal(greeks.get("vega")),
                "rho": _decimal(greeks.get("rho")),
                "open_interest": int(contract.get("open_interest", 0) or 0),
                "volume": int(day.get("volume", 0) or 0),
                "in_the_money": contract.get("details", {}).get("exercise_style") == "american",
                "data_source": "POLYGON",
                "raw_payload": {
                    **contract,
                    "normalized_occ_symbol": occ_symbol,
                },
            }
        )
    return rows


__all__ = ["map_option_chain_rows"]
