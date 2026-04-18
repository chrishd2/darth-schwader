from __future__ import annotations

from decimal import Decimal

from darth_schwader.broker.schwab.mappers import map_option_chain


def test_map_option_chain_parses_quote_time_and_occ_symbols(load_fixture: callable) -> None:
    payload = load_fixture("schwab/option_chain_aapl.json")
    chain = map_option_chain(payload)

    assert chain.underlying == "AAPL"
    assert chain.quote_time.year == 2024
    assert chain.contracts[0].occ_symbol == "AAPL  240621C00195000"
    assert isinstance(chain.contracts[0].strike, Decimal)
    assert isinstance(chain.contracts[0].bid, Decimal)
    assert isinstance(chain.underlying_mark, Decimal)
