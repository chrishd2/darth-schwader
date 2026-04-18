from __future__ import annotations

from cryptography.fernet import Fernet
from pydantic import SecretStr

from darth_schwader.ai.llm import build_selector
from darth_schwader.ai.llm.openrouter_provider import OpenRouterStrategySelector
from darth_schwader.ai.llm.selector import NullLLMSelector
from darth_schwader.config import Settings


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "env": "test",
        "database_url": "sqlite+aiosqlite:///:memory:",
        "schwab_client_id": "client-id",
        "schwab_client_secret": "client-secret",
        "schwab_account_number": "123456789",
        "token_encryption_key": Fernet.generate_key().decode("utf-8"),
        "watchlist": ["AAPL"],
    }
    base.update(overrides)
    return Settings(**base)


def test_build_selector_returns_null_when_no_api_key() -> None:
    selector = build_selector(
        _settings(ai_provider="openrouter", openrouter_api_key=None)
    )

    assert isinstance(selector, NullLLMSelector)


def test_build_selector_returns_null_when_provider_is_none() -> None:
    selector = build_selector(
        _settings(
            ai_provider="none",
            openrouter_api_key=SecretStr("openrouter-key"),
        )
    )

    assert isinstance(selector, NullLLMSelector)


def test_build_selector_returns_openrouter_when_configured() -> None:
    selector = build_selector(
        _settings(
            ai_provider="openrouter",
            openrouter_api_key=SecretStr("openrouter-key"),
            openrouter_model="anthropic/claude-sonnet-4.6",
            openrouter_base_url="https://openrouter.ai/api/v1",
            openrouter_http_referer="https://example.com",
            openrouter_app_title="Darth Schwader",
        )
    )

    assert isinstance(selector, OpenRouterStrategySelector)
