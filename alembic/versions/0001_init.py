from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001_init"
down_revision = None
branch_labels = None
depends_on = None


strategy_enum = sa.Enum(
    "VERTICAL_SPREAD",
    "IRON_CONDOR",
    "DEFINED_RISK_DIRECTIONAL",
    "CASH_SECURED_PUT",
    "COVERED_CALL",
    "CALENDAR_SPREAD",
    "NAKED_PUT",
    "NAKED_CALL",
    name="strategytype",
    native_enum=False,
    create_constraint=True,
)
signal_status_enum = sa.Enum(
    "PENDING",
    "APPROVED_AWAITING_HITL",
    "REJECTED",
    "EXPIRED",
    "EXECUTED",
    name="signalstatus",
    native_enum=False,
    create_constraint=True,
)
order_status_enum = sa.Enum(
    "PENDING_SUBMISSION",
    "SUBMITTED",
    "WORKING",
    "FILLED",
    "PARTIALLY_FILLED",
    "CANCELLED",
    "REJECTED",
    "ERROR",
    name="orderstatus",
    native_enum=False,
    create_constraint=True,
)
collateral_enum = sa.Enum(
    "CASH",
    "SHARES",
    "LONG_OPTION",
    "NONE",
    name="collateralkind",
    native_enum=False,
    create_constraint=True,
)
account_type_enum = sa.Enum(
    "CASH",
    "MARGIN",
    "PORTFOLIO_MARGIN",
    name="accounttype",
    native_enum=False,
    create_constraint=True,
)
cash_ledger_reason_enum = sa.Enum(
    "ORDER_FILL",
    "COLLATERAL_LOCK",
    "COLLATERAL_RELEASE",
    "MANUAL_ADJUSTMENT",
    "RECONCILIATION",
    name="cashledgerreason",
    native_enum=False,
    create_constraint=True,
)


def upgrade() -> None:
    op.create_table(
        "config_refs",
        sa.Column("key", sa.String(length=100), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
    )
    op.create_table(
        "broker_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("access_token_ciphertext", sa.Text(), nullable=False),
        sa.Column("refresh_token_ciphertext", sa.Text(), nullable=False),
        sa.Column("access_token_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refresh_token_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scope", sa.Text(), nullable=True),
        sa.Column("token_type", sa.String(length=32), nullable=False),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_refresh_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_refresh_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.UniqueConstraint("provider", name="uq_broker_tokens_provider"),
    )
    op.create_table(
        "accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("broker_account_id", sa.String(length=64), nullable=False),
        sa.Column("account_hash", sa.String(length=128), nullable=True),
        sa.Column("account_type", account_type_enum, nullable=False),
        sa.Column("base_currency", sa.String(length=3), nullable=False),
        sa.Column("options_approval_tier", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.CheckConstraint("options_approval_tier IN (1, 2, 3)", name="ck_accounts_options_approval_tier"),
        sa.UniqueConstraint("broker_account_id", name="uq_accounts_broker_account_id"),
    )
    op.create_table(
        "account_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("net_liquidation_value", sa.Numeric(18, 4), nullable=False),
        sa.Column("cash_balance", sa.Numeric(18, 4), nullable=False),
        sa.Column("buying_power", sa.Numeric(18, 4), nullable=True),
        sa.Column("maintenance_requirement", sa.Numeric(18, 4), nullable=True),
        sa.Column("day_pnl", sa.Numeric(18, 4), nullable=True),
        sa.Column("week_pnl", sa.Numeric(18, 4), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.UniqueConstraint("account_id", "as_of", name="uq_account_snapshots_account_as_of"),
    )
    op.create_table(
        "signals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("signal_id", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("strategy_type", strategy_enum, nullable=False),
        sa.Column("underlying", sa.String(length=16), nullable=False),
        sa.Column("expiration_date", sa.Date(), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=True),
        sa.Column("thesis", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Numeric(10, 6), nullable=True),
        sa.Column("proposed_payload", sa.JSON(), nullable=False),
        sa.Column("suggested_quantity", sa.Integer(), nullable=True),
        sa.Column("suggested_max_loss", sa.Numeric(18, 4), nullable=True),
        sa.Column("preferred_quantity", sa.Integer(), nullable=True),
        sa.Column("ceiling_quantity", sa.Integer(), nullable=True),
        sa.Column("status", signal_status_enum, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.CheckConstraint("source IN ('AI','RULE','MANUAL')", name="ck_signals_source"),
        sa.UniqueConstraint("signal_id", name="uq_signals_signal_id"),
    )
    op.create_table(
        "risk_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("signal_id", sa.Integer(), sa.ForeignKey("signals.id"), nullable=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("reason_text", sa.Text(), nullable=False),
        sa.Column("rule_results_json", sa.JSON(), nullable=False),
        sa.Column("warnings_json", sa.JSON(), nullable=True),
        sa.Column("max_loss", sa.Numeric(18, 4), nullable=True),
        sa.Column("position_size_limit", sa.Numeric(18, 4), nullable=True),
        sa.Column("approved_quantity", sa.Integer(), nullable=True),
        sa.Column("correlation_bucket", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.CheckConstraint("decision IN ('APPROVE','REJECT')", name="ck_risk_events_decision"),
    )
    op.create_index("idx_risk_events_account_time", "risk_events", ["account_id", "created_at"])
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("signal_id", sa.Integer(), sa.ForeignKey("signals.id"), nullable=True),
        sa.Column("risk_event_id", sa.Integer(), sa.ForeignKey("risk_events.id"), nullable=False),
        sa.Column("broker_order_id", sa.String(length=64), nullable=True),
        sa.Column("client_order_id", sa.String(length=40), nullable=False),
        sa.Column("strategy_type", strategy_enum, nullable=False),
        sa.Column("underlying", sa.String(length=16), nullable=False),
        sa.Column("order_status", order_status_enum, nullable=False),
        sa.Column("intent", sa.String(length=16), nullable=False),
        sa.Column("price_limit", sa.Numeric(18, 4), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("defined_risk", sa.Boolean(), nullable=False),
        sa.Column("is_naked", sa.Boolean(), nullable=False),
        sa.Column("required_collateral", sa.Numeric(18, 4), nullable=False),
        sa.Column("collateral_kind", collateral_enum, nullable=False),
        sa.Column("max_loss", sa.Numeric(18, 4), nullable=False),
        sa.Column("order_payload", sa.JSON(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.CheckConstraint("intent IN ('OPEN','CLOSE','ADJUST')", name="ck_orders_intent"),
        sa.CheckConstraint("quantity > 0", name="ck_orders_quantity_positive"),
        sa.CheckConstraint("defined_risk IN (0,1)", name="ck_orders_defined_risk_boolean"),
        sa.CheckConstraint("is_naked IN (0,1)", name="ck_orders_is_naked_boolean"),
        sa.CheckConstraint("max_loss >= 0", name="ck_orders_max_loss_nonnegative"),
        sa.CheckConstraint("required_collateral >= 0", name="ck_orders_required_collateral_nonnegative"),
        sa.UniqueConstraint("broker_order_id", name="uq_orders_broker_order_id"),
        sa.UniqueConstraint("client_order_id", name="uq_orders_client_order_id"),
    )
    op.create_index("idx_orders_account_status", "orders", ["account_id", "order_status"])
    op.create_index("idx_orders_underlying_status", "orders", ["underlying", "order_status"])
    op.create_table(
        "fills",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("broker_fill_id", sa.String(length=64), nullable=False),
        sa.Column("filled_quantity", sa.Integer(), nullable=False),
        sa.Column("fill_price", sa.Numeric(18, 4), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.UniqueConstraint("broker_fill_id", name="uq_fills_broker_fill_id"),
    )
    op.create_table(
        "positions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("broker_position_id", sa.String(length=64), nullable=True),
        sa.Column("underlying", sa.String(length=16), nullable=False),
        sa.Column("strategy_type", strategy_enum, nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("entry_cost", sa.Numeric(18, 4), nullable=True),
        sa.Column("current_mark", sa.Numeric(18, 4), nullable=True),
        sa.Column("max_profit", sa.Numeric(18, 4), nullable=True),
        sa.Column("max_loss", sa.Numeric(18, 4), nullable=False),
        sa.Column("defined_risk", sa.Boolean(), nullable=False),
        sa.Column("is_naked", sa.Boolean(), nullable=False),
        sa.Column("collateral_amount", sa.Numeric(18, 4), nullable=False),
        sa.Column("collateral_kind", collateral_enum, nullable=False),
        sa.Column("legs_json", sa.JSON(), nullable=False),
        sa.Column("last_reconciled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.CheckConstraint("quantity > 0", name="ck_positions_quantity_positive"),
        sa.CheckConstraint("max_loss >= 0", name="ck_positions_max_loss_nonnegative"),
        sa.CheckConstraint("collateral_amount >= 0", name="ck_positions_collateral_amount_nonnegative"),
        sa.CheckConstraint("is_naked IN (0,1)", name="ck_positions_is_naked_boolean"),
    )
    op.create_index("idx_positions_account_status", "positions", ["account_id", "status"])
    op.create_index("idx_positions_underlying_status", "positions", ["underlying", "status"])
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=64), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
    )
    op.create_index("idx_audit_log_correlation", "audit_log", ["correlation_id", "created_at"])
    op.create_index("idx_audit_log_entity", "audit_log", ["entity_type", "entity_id", "created_at"])
    op.create_table(
        "chain_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("underlying", sa.String(length=16), nullable=False),
        sa.Column("quote_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expiration_date", sa.Date(), nullable=False),
        sa.Column("option_type", sa.String(length=8), nullable=False),
        sa.Column("strike", sa.Numeric(18, 4), nullable=False),
        sa.Column("bid", sa.Numeric(18, 4), nullable=True),
        sa.Column("ask", sa.Numeric(18, 4), nullable=True),
        sa.Column("last", sa.Numeric(18, 4), nullable=True),
        sa.Column("mark", sa.Numeric(18, 4), nullable=True),
        sa.Column("implied_volatility", sa.Numeric(10, 6), nullable=True),
        sa.Column("delta", sa.Numeric(10, 6), nullable=True),
        sa.Column("gamma", sa.Numeric(10, 6), nullable=True),
        sa.Column("theta", sa.Numeric(10, 6), nullable=True),
        sa.Column("vega", sa.Numeric(10, 6), nullable=True),
        sa.Column("rho", sa.Numeric(10, 6), nullable=True),
        sa.Column("open_interest", sa.Integer(), nullable=True),
        sa.Column("volume", sa.Integer(), nullable=True),
        sa.Column("in_the_money", sa.Boolean(), nullable=True),
        sa.Column("data_source", sa.String(length=16), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.CheckConstraint("option_type IN ('CALL','PUT')", name="ck_chain_snapshots_option_type"),
        sa.CheckConstraint("data_source IN ('SCHWAB','POLYGON')", name="ck_chain_snapshots_data_source"),
        sa.UniqueConstraint(
            "underlying",
            "quote_time",
            "expiration_date",
            "option_type",
            "strike",
            "data_source",
            name="uq_chain_snapshots_key",
        ),
    )
    op.create_index(
        "idx_chain_snapshots_lookup",
        "chain_snapshots",
        ["underlying", "expiration_date", "option_type", "strike"],
    )
    op.create_index("idx_chain_snapshots_quote_time", "chain_snapshots", ["underlying", "quote_time"])
    op.create_table(
        "cash_ledger",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settles_on", sa.Date(), nullable=False),
        sa.Column("delta_amount", sa.Numeric(18, 4), nullable=False),
        sa.Column("reason", cash_ledger_reason_enum, nullable=False),
        sa.Column("related_order_id", sa.Integer(), sa.ForeignKey("orders.id"), nullable=True),
        sa.Column("related_fill_id", sa.Integer(), sa.ForeignKey("fills.id"), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
    )
    op.create_index("idx_cash_ledger_account_settles", "cash_ledger", ["account_id", "settles_on"])
    op.create_table(
        "risk_policy_overrides",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_by", sa.String(length=64), nullable=False),
        sa.UniqueConstraint("key"),
    )
    op.create_table(
        "iv_spike_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("underlying", sa.String(length=16), nullable=False),
        sa.Column("iv_percentile", sa.Numeric(10, 6), nullable=False),
        sa.Column("iv_rank", sa.Numeric(10, 6), nullable=True),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("threshold_used", sa.Numeric(10, 6), nullable=False),
        sa.Column("signal_run_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.current_timestamp()),
    )
    op.create_index("idx_iv_events_underlying_time", "iv_spike_events", ["underlying", "triggered_at"])


def downgrade() -> None:
    op.drop_index("idx_iv_events_underlying_time", table_name="iv_spike_events")
    op.drop_table("iv_spike_events")
    op.drop_table("risk_policy_overrides")
    op.drop_index("idx_cash_ledger_account_settles", table_name="cash_ledger")
    op.drop_table("cash_ledger")
    op.drop_index("idx_chain_snapshots_quote_time", table_name="chain_snapshots")
    op.drop_index("idx_chain_snapshots_lookup", table_name="chain_snapshots")
    op.drop_table("chain_snapshots")
    op.drop_index("idx_audit_log_entity", table_name="audit_log")
    op.drop_index("idx_audit_log_correlation", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index("idx_positions_underlying_status", table_name="positions")
    op.drop_index("idx_positions_account_status", table_name="positions")
    op.drop_table("positions")
    op.drop_table("fills")
    op.drop_index("idx_orders_underlying_status", table_name="orders")
    op.drop_index("idx_orders_account_status", table_name="orders")
    op.drop_table("orders")
    op.drop_index("idx_risk_events_account_time", table_name="risk_events")
    op.drop_table("risk_events")
    op.drop_table("signals")
    op.drop_table("account_snapshots")
    op.drop_table("accounts")
    op.drop_table("broker_tokens")
    op.drop_table("config_refs")
