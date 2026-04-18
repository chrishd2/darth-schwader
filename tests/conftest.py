from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path

from cryptography.fernet import Fernet

for key, value in {
    "SCHWAB_CLIENT_ID": "client-id",
    "SCHWAB_CLIENT_SECRET": "client-secret",
    "SCHWAB_ACCOUNT_NUMBER": "123456789",
    "TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode("utf-8"),
    "WATCHLIST": "AAPL",
}.items():
    os.environ.setdefault(key, value)

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
import respx  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from darth_schwader.config import Settings, get_settings  # noqa: E402
from darth_schwader.db.base import Base  # noqa: E402
from darth_schwader.main import create_app  # noqa: E402


@pytest.fixture
def settings() -> Settings:
    return Settings(
        env="test",
        database_url="sqlite+aiosqlite:///:memory:",
        schwab_client_id="client-id",
        schwab_client_secret="client-secret",
        schwab_account_number="123456789",
        token_encryption_key=Fernet.generate_key().decode("utf-8"),
        watchlist=["AAPL"],
        polygon_api_key="polygon-key",
        polygon_backfill_days=30,
    )


@pytest_asyncio.fixture
async def engine() -> AsyncEngine:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


@pytest_asyncio.fixture
async def session(session_factory: async_sessionmaker[AsyncSession]) -> AsyncSession:
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
def respx_mock() -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as router:
        yield router


@pytest.fixture
def fixture_path() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def load_fixture(fixture_path: Path) -> callable:
    def _load(relative_path: str) -> dict[str, object]:
        return json.loads((fixture_path / relative_path).read_text(encoding="utf-8"))

    return _load


@pytest.fixture
def make_app(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> callable:
    monkeypatch.setattr("darth_schwader.config.get_settings", lambda: settings)
    monkeypatch.setattr("darth_schwader.api.deps.get_settings", lambda: settings)
    monkeypatch.setattr("darth_schwader.main.get_settings", lambda: settings)

    def _factory():
        app = create_app()
        app.dependency_overrides[get_settings] = lambda: settings
        app.state.session_factory = session_factory
        app.state.settings = settings
        app.state.bot_state = "ACTIVE"
        app.state.last_scheduler_run = None
        return app

    return _factory


@pytest_asyncio.fixture
async def api_client(make_app: callable) -> AsyncClient:
    app = make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
        yield client
