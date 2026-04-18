from __future__ import annotations


class BrokerError(RuntimeError):
    pass


class AuthExpiredError(BrokerError):
    pass


class OrderRejectedError(BrokerError):
    pass


class RateLimitError(BrokerError):
    pass


class TransientBrokerError(BrokerError):
    pass
