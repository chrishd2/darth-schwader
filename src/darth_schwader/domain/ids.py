from __future__ import annotations

import hashlib


def make_client_order_id(signal_id: str, attempt: int) -> str:
    if attempt < 1:
        raise ValueError("attempt must be >= 1")

    payload = f"{signal_id}:{attempt}".encode("utf-8")
    digest = hashlib.blake2s(payload, digest_size=10).hexdigest()
    client_order_id = f"dsw-{digest}-{attempt}"
    return client_order_id[:40]


__all__ = ["make_client_order_id"]
