from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    env: Literal["dev", "test", "prod"] = "dev"
    app_host: str = "127.0.0.1"
    app_port: int = 8000
    database_url: str = "sqlite+aiosqlite:///./data/darth_schwader.db"
    log_level: str = "INFO"

    schwab_client_id: str
    schwab_client_secret: SecretStr
    schwab_redirect_uri: AnyHttpUrl = AnyHttpUrl(
        "https://127.0.0.1:8000/api/v1/broker/oauth/callback"
    )
    schwab_account_number: str
    token_encryption_key: SecretStr

    account_type: Literal["CASH", "MARGIN", "PORTFOLIO_MARGIN"] = "CASH"
    options_approval_tier: int = 2
    watchlist: list[str] = Field(
        default_factory=lambda: ["SPY", "QQQ", "IWM", "AAPL", "NVDA", "TSLA", "MSFT", "META"]
    )

    paper_trading: bool = True
    hitl_required: bool = True
    allow_naked: bool = False

    max_risk_per_trade_pct: Decimal = Decimal("0.25")
    preferred_max_risk_per_trade_pct: Decimal = Decimal("0.05")
    max_daily_drawdown_pct: Decimal = Decimal("0.05")
    max_weekly_drawdown_pct: Decimal = Decimal("0.10")
    max_positions: int = 5
    max_underlying_allocation_pct: Decimal = Decimal("0.20")
    min_dte_days: int = 14
    max_dte_days: int = 60

    ai_provider: Literal["claude", "openai", "none"] = "claude"
    anthropic_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    iv_spike_threshold_pct: Decimal = Decimal("90")
    polygon_api_key: SecretStr | None = None
    polygon_backfill_days: int = 365

    @field_validator("watchlist", mode="before")
    @classmethod
    def _parse_watchlist(cls, value: object) -> list[str]:
        if isinstance(value, str):
            parts = [item.strip().upper() for item in value.split(",")]
            return [item for item in parts if item]
        if isinstance(value, list):
            return [str(item).strip().upper() for item in value if str(item).strip()]
        raise TypeError("watchlist must be a comma-separated string or list")

    @field_validator(
        "max_risk_per_trade_pct",
        "preferred_max_risk_per_trade_pct",
        "max_daily_drawdown_pct",
        "max_weekly_drawdown_pct",
        "max_underlying_allocation_pct",
        mode="before",
    )
    @classmethod
    def _parse_decimal(cls, value: object) -> Decimal:
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))

    @field_validator("options_approval_tier")
    @classmethod
    def _validate_tier(cls, value: int) -> int:
        if value not in {1, 2, 3}:
            raise ValueError("options_approval_tier must be 1, 2, or 3")
        return value

    @field_validator("min_dte_days", "max_dte_days", "polygon_backfill_days", "max_positions")
    @classmethod
    def _validate_positive_ints(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("value must be greater than zero")
        return value

    @model_validator(mode="after")
    def _validate_risk_caps(self) -> Settings:
        if self.preferred_max_risk_per_trade_pct <= Decimal("0"):
            raise ValueError("preferred_max_risk_per_trade_pct must be greater than zero")
        if self.max_risk_per_trade_pct <= Decimal("0"):
            raise ValueError("max_risk_per_trade_pct must be greater than zero")
        if self.preferred_max_risk_per_trade_pct > self.max_risk_per_trade_pct:
            raise ValueError("preferred_max_risk_per_trade_pct must be <= max_risk_per_trade_pct")
        if self.max_risk_per_trade_pct > Decimal("0.50"):
            raise ValueError("max_risk_per_trade_pct must be <= 0.50")
        if self.min_dte_days > self.max_dte_days:
            raise ValueError("min_dte_days must be <= max_dte_days")
        return self

    @property
    def is_dev(self) -> bool:
        return self.env == "dev"

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


__all__ = ["Settings", "get_settings"]
