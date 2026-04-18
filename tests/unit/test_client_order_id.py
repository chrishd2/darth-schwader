from __future__ import annotations

from darth_schwader.domain.ids import make_client_order_id


def test_make_client_order_id_is_deterministic_and_bounded() -> None:
    left = make_client_order_id("sig-123", 1)
    right = make_client_order_id("sig-123", 1)
    assert left == right
    assert len(left) <= 40
