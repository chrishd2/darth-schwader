from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_bracket_orders"
down_revision = "0002_watchlist"
branch_labels = None
depends_on = None


STRATEGY_VALUES_V2 = (
    "VERTICAL_SPREAD",
    "IRON_CONDOR",
    "DEFINED_RISK_DIRECTIONAL",
    "CASH_SECURED_PUT",
    "COVERED_CALL",
    "CALENDAR_SPREAD",
    "NAKED_PUT",
    "NAKED_CALL",
    "LONG_EQUITY",
    "SHORT_EQUITY",
    "LONG_FUTURE",
    "SHORT_FUTURE",
)

STRATEGY_VALUES_V1 = (
    "VERTICAL_SPREAD",
    "IRON_CONDOR",
    "DEFINED_RISK_DIRECTIONAL",
    "CASH_SECURED_PUT",
    "COVERED_CALL",
    "CALENDAR_SPREAD",
    "NAKED_PUT",
    "NAKED_CALL",
)

STRATEGY_TABLES = ("signals", "orders", "positions")


def _check_sql(values: tuple[str, ...]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"strategy_type IN ({quoted})"


def _replace_strategy_check(table: str, values: tuple[str, ...]) -> None:
    with op.batch_alter_table(table) as batch_op:
        batch_op.drop_constraint("strategytype", type_="check")
        batch_op.create_check_constraint("strategytype", _check_sql(values))


def upgrade() -> None:
    for table in STRATEGY_TABLES:
        _replace_strategy_check(table, STRATEGY_VALUES_V2)

    with op.batch_alter_table("orders") as batch_op:
        batch_op.add_column(sa.Column("parent_order_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("bracket_role", sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column("stop_price", sa.Numeric(18, 4), nullable=True))
        batch_op.add_column(sa.Column("target_price", sa.Numeric(18, 4), nullable=True))
        batch_op.create_foreign_key(
            "fk_orders_parent_order_id",
            "orders",
            ["parent_order_id"],
            ["id"],
        )
        batch_op.create_check_constraint(
            "ck_orders_bracket_role",
            "bracket_role IS NULL OR bracket_role IN ('ENTRY','STOP','TARGET')",
        )

    op.create_index("idx_orders_parent", "orders", ["parent_order_id"])


def downgrade() -> None:
    op.drop_index("idx_orders_parent", table_name="orders")

    with op.batch_alter_table("orders") as batch_op:
        batch_op.drop_constraint("ck_orders_bracket_role", type_="check")
        batch_op.drop_constraint("fk_orders_parent_order_id", type_="foreignkey")
        batch_op.drop_column("target_price")
        batch_op.drop_column("stop_price")
        batch_op.drop_column("bracket_role")
        batch_op.drop_column("parent_order_id")

    for table in STRATEGY_TABLES:
        _replace_strategy_check(table, STRATEGY_VALUES_V1)
