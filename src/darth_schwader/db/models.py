from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from darth_schwader.db.base import Base
from darth_schwader.domain.asset_types import AssetType
from darth_schwader.domain.enums import (
    AccountType,
    CashLedgerReason,
    CollateralKind,
    OrderStatus,
    SignalStatus,
    StrategyType,
)

money = Numeric(18, 4)
pct = Numeric(10, 6)


class ConfigRef(Base):
    __tablename__ = "config_refs"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )


class BrokerToken(Base):
    __tablename__ = "broker_tokens"
    __table_args__ = (UniqueConstraint("provider", name="uq_broker_tokens_provider"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    access_token_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    access_token_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    refresh_token_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scope: Mapped[str | None] = mapped_column(Text)
    token_type: Mapped[str] = mapped_column(String(32), nullable=False, default="Bearer")
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_refresh_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_refresh_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("broker_account_id", name="uq_accounts_broker_account_id"),
        CheckConstraint(
            "options_approval_tier IN (1, 2, 3)",
            name="ck_accounts_options_approval_tier",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    broker_account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    account_hash: Mapped[str | None] = mapped_column(String(128))
    account_type: Mapped[AccountType] = mapped_column(
        Enum(AccountType, native_enum=False, create_constraint=True),
        nullable=False,
    )
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    options_approval_tier: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )

    snapshots: Mapped[list[AccountSnapshot]] = relationship(back_populates="account")


class AccountSnapshot(Base):
    __tablename__ = "account_snapshots"
    __table_args__ = (
        UniqueConstraint("account_id", "as_of", name="uq_account_snapshots_account_as_of"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    net_liquidation_value: Mapped[Decimal] = mapped_column(money, nullable=False)
    cash_balance: Mapped[Decimal] = mapped_column(money, nullable=False)
    buying_power: Mapped[Decimal | None] = mapped_column(money)
    maintenance_requirement: Mapped[Decimal | None] = mapped_column(money)
    day_pnl: Mapped[Decimal | None] = mapped_column(money)
    week_pnl: Mapped[Decimal | None] = mapped_column(money)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )

    account: Mapped[Account] = relationship(back_populates="snapshots")


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_positions_quantity_positive"),
        CheckConstraint("max_loss >= 0", name="ck_positions_max_loss_nonnegative"),
        CheckConstraint("collateral_amount >= 0", name="ck_positions_collateral_amount_nonnegative"),
        CheckConstraint("is_naked IN (0,1)", name="ck_positions_is_naked_boolean"),
        Index("idx_positions_account_status", "account_id", "status"),
        Index("idx_positions_underlying_status", "underlying", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    broker_position_id: Mapped[str | None] = mapped_column(String(64))
    underlying: Mapped[str] = mapped_column(String(16), nullable=False)
    strategy_type: Mapped[StrategyType] = mapped_column(
        Enum(StrategyType, native_enum=False, create_constraint=True),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    entry_cost: Mapped[Decimal | None] = mapped_column(money)
    current_mark: Mapped[Decimal | None] = mapped_column(money)
    max_profit: Mapped[Decimal | None] = mapped_column(money)
    max_loss: Mapped[Decimal] = mapped_column(money, nullable=False)
    defined_risk: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_naked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    collateral_amount: Mapped[Decimal] = mapped_column(money, nullable=False, default=Decimal("0"))
    collateral_kind: Mapped[CollateralKind] = mapped_column(
        Enum(CollateralKind, native_enum=False, create_constraint=True),
        nullable=False,
        default=CollateralKind.NONE,
    )
    legs_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    last_reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )


class Signal(Base):
    __tablename__ = "signals"
    __table_args__ = (
        UniqueConstraint("signal_id", name="uq_signals_signal_id"),
        CheckConstraint("source IN ('AI','RULE','MANUAL')", name="ck_signals_source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    signal_id: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    strategy_type: Mapped[StrategyType] = mapped_column(
        Enum(StrategyType, native_enum=False, create_constraint=True),
        nullable=False,
    )
    underlying: Mapped[str] = mapped_column(String(16), nullable=False)
    expiration_date: Mapped[date] = mapped_column(Date, nullable=False)
    direction: Mapped[str | None] = mapped_column(String(16))
    thesis: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[Decimal | None] = mapped_column(pct)
    proposed_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    suggested_quantity: Mapped[int | None] = mapped_column(Integer)
    suggested_max_loss: Mapped[Decimal | None] = mapped_column(money)
    preferred_quantity: Mapped[int | None] = mapped_column(Integer)
    ceiling_quantity: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[SignalStatus] = mapped_column(
        Enum(SignalStatus, native_enum=False, create_constraint=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )


class RiskEvent(Base):
    __tablename__ = "risk_events"
    __table_args__ = (
        CheckConstraint("decision IN ('APPROVE','REJECT')", name="ck_risk_events_decision"),
        Index("idx_risk_events_account_time", "account_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    signal_id: Mapped[int | None] = mapped_column(ForeignKey("signals.id"))
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_text: Mapped[str] = mapped_column(Text, nullable=False)
    rule_results_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    warnings_json: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    max_loss: Mapped[Decimal | None] = mapped_column(money)
    position_size_limit: Mapped[Decimal | None] = mapped_column(money)
    approved_quantity: Mapped[int | None] = mapped_column(Integer)
    correlation_bucket: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("broker_order_id", name="uq_orders_broker_order_id"),
        UniqueConstraint("client_order_id", name="uq_orders_client_order_id"),
        CheckConstraint("intent IN ('OPEN','CLOSE','ADJUST')", name="ck_orders_intent"),
        CheckConstraint("quantity > 0", name="ck_orders_quantity_positive"),
        CheckConstraint("defined_risk IN (0,1)", name="ck_orders_defined_risk_boolean"),
        CheckConstraint("is_naked IN (0,1)", name="ck_orders_is_naked_boolean"),
        CheckConstraint("max_loss >= 0", name="ck_orders_max_loss_nonnegative"),
        CheckConstraint("required_collateral >= 0", name="ck_orders_required_collateral_nonnegative"),
        CheckConstraint(
            "bracket_role IS NULL OR bracket_role IN ('ENTRY','STOP','TARGET')",
            name="ck_orders_bracket_role",
        ),
        Index("idx_orders_account_status", "account_id", "order_status"),
        Index("idx_orders_underlying_status", "underlying", "order_status"),
        Index("idx_orders_parent", "parent_order_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    signal_id: Mapped[int | None] = mapped_column(ForeignKey("signals.id"))
    risk_event_id: Mapped[int] = mapped_column(ForeignKey("risk_events.id"), nullable=False)
    broker_order_id: Mapped[str | None] = mapped_column(String(64))
    client_order_id: Mapped[str] = mapped_column(String(40), nullable=False)
    strategy_type: Mapped[StrategyType] = mapped_column(
        Enum(StrategyType, native_enum=False, create_constraint=True),
        nullable=False,
    )
    underlying: Mapped[str] = mapped_column(String(16), nullable=False)
    order_status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, native_enum=False, create_constraint=True),
        nullable=False,
    )
    intent: Mapped[str] = mapped_column(String(16), nullable=False)
    price_limit: Mapped[Decimal | None] = mapped_column(money)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    defined_risk: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_naked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    required_collateral: Mapped[Decimal] = mapped_column(money, nullable=False, default=Decimal("0"))
    collateral_kind: Mapped[CollateralKind] = mapped_column(
        Enum(CollateralKind, native_enum=False, create_constraint=True),
        nullable=False,
        default=CollateralKind.NONE,
    )
    max_loss: Mapped[Decimal] = mapped_column(money, nullable=False)
    order_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    parent_order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
    bracket_role: Mapped[str | None] = mapped_column(String(16))
    stop_price: Mapped[Decimal | None] = mapped_column(money)
    target_price: Mapped[Decimal | None] = mapped_column(money)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )


class Fill(Base):
    __tablename__ = "fills"
    __table_args__ = (UniqueConstraint("broker_fill_id", name="uq_fills_broker_fill_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    broker_fill_id: Mapped[str] = mapped_column(String(64), nullable=False)
    filled_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    fill_price: Mapped[Decimal] = mapped_column(money, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("idx_audit_log_correlation", "correlation_id", "created_at"),
        Index("idx_audit_log_entity", "entity_type", "entity_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(64))
    correlation_id: Mapped[str | None] = mapped_column(String(64))
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )


class ChainSnapshot(Base):
    __tablename__ = "chain_snapshots"
    __table_args__ = (
        CheckConstraint("option_type IN ('CALL','PUT')", name="ck_chain_snapshots_option_type"),
        CheckConstraint("data_source IN ('SCHWAB','POLYGON')", name="ck_chain_snapshots_data_source"),
        UniqueConstraint(
            "underlying",
            "quote_time",
            "expiration_date",
            "option_type",
            "strike",
            "data_source",
            name="uq_chain_snapshots_key",
        ),
        Index("idx_chain_snapshots_lookup", "underlying", "expiration_date", "option_type", "strike"),
        Index("idx_chain_snapshots_quote_time", "underlying", "quote_time"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    underlying: Mapped[str] = mapped_column(String(16), nullable=False)
    quote_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expiration_date: Mapped[date] = mapped_column(Date, nullable=False)
    option_type: Mapped[str] = mapped_column(String(8), nullable=False)
    strike: Mapped[Decimal] = mapped_column(money, nullable=False)
    bid: Mapped[Decimal | None] = mapped_column(money)
    ask: Mapped[Decimal | None] = mapped_column(money)
    last: Mapped[Decimal | None] = mapped_column(money)
    mark: Mapped[Decimal | None] = mapped_column(money)
    implied_volatility: Mapped[Decimal | None] = mapped_column(pct)
    delta: Mapped[Decimal | None] = mapped_column(pct)
    gamma: Mapped[Decimal | None] = mapped_column(pct)
    theta: Mapped[Decimal | None] = mapped_column(pct)
    vega: Mapped[Decimal | None] = mapped_column(pct)
    rho: Mapped[Decimal | None] = mapped_column(pct)
    open_interest: Mapped[int | None] = mapped_column(Integer)
    volume: Mapped[int | None] = mapped_column(Integer)
    in_the_money: Mapped[bool | None] = mapped_column(Boolean)
    data_source: Mapped[str] = mapped_column(String(16), nullable=False, default="SCHWAB")
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )


class CashLedger(Base):
    __tablename__ = "cash_ledger"
    __table_args__ = (Index("idx_cash_ledger_account_settles", "account_id", "settles_on"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    settles_on: Mapped[date] = mapped_column(Date, nullable=False)
    delta_amount: Mapped[Decimal] = mapped_column(money, nullable=False)
    reason: Mapped[CashLedgerReason] = mapped_column(
        Enum(CashLedgerReason, native_enum=False, create_constraint=True),
        nullable=False,
    )
    related_order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
    related_fill_id: Mapped[int | None] = mapped_column(ForeignKey("fills.id"))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )


class RiskPolicyOverride(Base):
    __tablename__ = "risk_policy_overrides"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )
    updated_by: Mapped[str] = mapped_column(String(64), nullable=False, default="ui")


class IvSpikeEvent(Base):
    __tablename__ = "iv_spike_events"
    __table_args__ = (Index("idx_iv_events_underlying_time", "underlying", "triggered_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    underlying: Mapped[str] = mapped_column(String(16), nullable=False)
    iv_percentile: Mapped[Decimal] = mapped_column(pct, nullable=False)
    iv_rank: Mapped[Decimal | None] = mapped_column(pct)
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    threshold_used: Mapped[Decimal] = mapped_column(pct, nullable=False)
    signal_run_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )


asset_type_enum = Enum(
    AssetType,
    name="assettype",
    native_enum=False,
    values_callable=lambda enum_cls: [member.value for member in enum_cls],
    create_constraint=True,
)


class WatchlistEntry(Base):
    __tablename__ = "watchlists"
    __table_args__ = (
        UniqueConstraint("symbol", "asset_type", name="uq_watchlists_symbol_asset_type"),
        Index("idx_watchlists_active", "active"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    asset_type: Mapped[AssetType] = mapped_column(asset_type_enum, nullable=False)
    strategies: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )
