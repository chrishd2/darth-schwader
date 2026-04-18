from __future__ import annotations

from darth_schwader.api.routers.admin import router as admin_router
from darth_schwader.api.routers.broker import router as broker_router
from darth_schwader.api.routers.cash_ledger import router as cash_ledger_router
from darth_schwader.api.routers.chains import router as chains_router
from darth_schwader.api.routers.health import router as health_router
from darth_schwader.api.routers.orders import router as orders_router
from darth_schwader.api.routers.positions import router as positions_router
from darth_schwader.api.routers.risk import router as risk_router
from darth_schwader.api.routers.settings import router as settings_router
from darth_schwader.api.routers.signals import router as signals_router
from darth_schwader.api.routers.status import router as status_router
from darth_schwader.api.routers.watchlist import router as watchlist_router

__all__ = [
    "admin_router",
    "broker_router",
    "cash_ledger_router",
    "chains_router",
    "health_router",
    "orders_router",
    "positions_router",
    "risk_router",
    "settings_router",
    "signals_router",
    "status_router",
    "watchlist_router",
]
