from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from darth_schwader.broker.models import (
    Account,
    OptionChain,
    OptionContract,
    OrderRequest,
    OrderResponse,
    Position,
    PositionLeg,
)
from darth_schwader.domain.enums import CollateralKind, OrderStatus, StrategyType


def _decimal(value: Any) -> Decimal | None:
    if value in (None, "", "NaN"):
        return None
    return Decimal(str(value))


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _parse_quote_time(payload: dict[str, Any]) -> datetime:
    candidates = (
        payload.get("quoteTimeInLong"),
        payload.get("underlying", {}).get("quoteTime"),
        payload.get("quoteTime"),
    )
    for candidate in candidates:
        if candidate in (None, ""):
            continue
        if isinstance(candidate, (int, float)) or str(candidate).isdigit():
            raw = int(candidate)
            divisor = 1000 if raw > 10_000_000_000 else 1
            return datetime.fromtimestamp(raw / divisor, tz=UTC)
        try:
            return datetime.fromisoformat(str(candidate).replace("Z", "+00:00")).astimezone(UTC)
        except ValueError:
            continue
    return datetime.now(tz=UTC)


def normalize_occ_symbol(symbol: str, expiration: str, option_type: str, strike: Decimal) -> str:
    yymmdd = expiration.replace("-", "")[2:]
    cp = "C" if option_type.upper() == "CALL" else "P"
    strike_raw = int((strike * Decimal("1000")).quantize(Decimal("1")))
    return f"{symbol.upper():<6}{yymmdd}{cp}{strike_raw:08d}"


def map_account(payload: dict[str, Any]) -> Account:
    balances = payload.get("securitiesAccount", {}).get("currentBalances", {})
    account_info = payload.get("securitiesAccount", {})
    return Account(
        broker_account_id=str(account_info.get("accountNumber", "")),
        account_type=str(account_info.get("type", "CASH")),
        net_liquidation_value=_decimal(balances.get("liquidationValue")) or Decimal("0"),
        cash_balance=_decimal(balances.get("cashBalance")) or Decimal("0"),
        buying_power=_decimal(balances.get("buyingPower")),
        options_approval_tier=_int_or_none(
            account_info.get("optionApprovalLevel") or account_info.get("optionsApprovalLevel")
        ),
        raw=payload,
    )


def map_position(payload: dict[str, Any]) -> Position:
    long_qty = int(payload.get("longQuantity", 0) or 0)
    short_qty = int(payload.get("shortQuantity", 0) or 0)
    net_qty = max(long_qty, short_qty)
    instrument = payload.get("instrument", {})
    symbol = str(instrument.get("symbol", ""))
    leg = PositionLeg(
        symbol=symbol,
        quantity=net_qty,
        side="SHORT" if short_qty else "LONG",
        strike=_decimal(instrument.get("strikePrice")),
        expiration_date=instrument.get("expirationDate"),
        option_type=instrument.get("putCall"),
    )
    return Position(
        broker_position_id=str(payload.get("positionId", "")) or None,
        underlying=str(instrument.get("underlyingSymbol", symbol[:6].strip())),
        strategy_type=StrategyType.DEFINED_RISK_DIRECTIONAL,
        quantity=net_qty,
        entry_cost=_decimal(payload.get("averagePrice")),
        current_mark=_decimal(payload.get("marketValue")),
        max_loss=_decimal(payload.get("marketValue")) or Decimal("0"),
        defined_risk=True,
        is_naked=False,
        collateral_amount=Decimal("0"),
        collateral_kind=CollateralKind.NONE,
        legs=[leg],
        raw=payload,
    )


def map_option_chain(payload: dict[str, Any]) -> OptionChain:
    quote_time = _parse_quote_time(payload)
    contracts: list[OptionContract] = []
    for side_key, option_type in (("callExpDateMap", "CALL"), ("putExpDateMap", "PUT")):
        exp_map = payload.get(side_key, {})
        for expiration_key, strikes in exp_map.items():
            expiration = expiration_key.split(":")[0]
            for strike_str, raw_contracts in strikes.items():
                for raw_contract in raw_contracts:
                    strike = _decimal(strike_str) or Decimal("0")
                    contracts.append(
                        OptionContract(
                            occ_symbol=normalize_occ_symbol(
                                payload["symbol"],
                                expiration,
                                option_type,
                                strike,
                            ),
                            underlying=payload["symbol"],
                            expiration_date=expiration,
                            strike=strike,
                            option_type=option_type,
                            bid=_decimal(raw_contract.get("bid")),
                            ask=_decimal(raw_contract.get("ask")),
                            last=_decimal(raw_contract.get("last")),
                            mark=_decimal(raw_contract.get("mark")),
                            implied_volatility=_decimal(raw_contract.get("volatility")),
                            delta=_decimal(raw_contract.get("delta")),
                            gamma=_decimal(raw_contract.get("gamma")),
                            theta=_decimal(raw_contract.get("theta")),
                            vega=_decimal(raw_contract.get("vega")),
                            rho=_decimal(raw_contract.get("rho")),
                            open_interest=raw_contract.get("openInterest"),
                            volume=raw_contract.get("totalVolume"),
                            in_the_money=raw_contract.get("inTheMoney"),
                            raw=raw_contract,
                        )
                    )
    underlying_price = payload.get("underlyingPrice")
    return OptionChain(
        underlying=payload["symbol"],
        quote_time=quote_time,
        underlying_mark=_decimal(underlying_price),
        contracts=contracts,
        raw=payload,
    )


def map_order_request(request: OrderRequest) -> dict[str, Any]:
    return {
        "session": "NORMAL",
        "duration": "DAY",
        "orderType": "LIMIT" if request.price_limit is not None else "MARKET",
        "complexOrderStrategyType": "NONE",
        "price": str(request.price_limit) if request.price_limit is not None else None,
        "orderStrategyType": "SINGLE",
        "orderLegCollection": [
            {
                "instruction": leg.instruction,
                "quantity": leg.quantity,
                "instrument": {
                    "symbol": leg.instrument_symbol,
                    "assetType": leg.asset_type,
                },
            }
            for leg in request.legs
        ],
        "specialInstruction": request.client_order_id,
    }


def map_order_response(payload: dict[str, Any], status_hint: str | None = None) -> OrderResponse:
    raw_status = status_hint or payload.get("status") or "SUBMITTED"
    status = OrderStatus(raw_status) if raw_status in OrderStatus._value2member_map_ else OrderStatus.SUBMITTED
    return OrderResponse(
        broker_order_id=str(payload.get("orderId", "")) or None,
        status=status,
        raw=payload,
    )
