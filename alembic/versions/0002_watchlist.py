from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from darth_schwader.config import get_settings

revision = "0002_watchlist"
down_revision = "0001_init"
branch_labels = None
depends_on = None


asset_type_enum = sa.Enum(
    "EQUITY",
    "ETF",
    "FUTURE",
    "OPTION_UNDERLYING",
    name="assettype",
    native_enum=False,
    create_constraint=True,
)


def upgrade() -> None:
    op.create_table(
        "watchlists",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("symbol", sa.String(16), nullable=False),
        sa.Column("asset_type", asset_type_enum, nullable=False),
        sa.Column("strategies", sa.JSON(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.UniqueConstraint(
            "symbol", "asset_type", name="uq_watchlists_symbol_asset_type"
        ),
    )
    op.create_index("idx_watchlists_active", "watchlists", ["active"])

    settings = get_settings()
    seed_symbols = list(dict.fromkeys(s.strip().upper() for s in settings.watchlist if s))
    if not seed_symbols:
        return

    watchlists = sa.table(
        "watchlists",
        sa.column("symbol", sa.String()),
        sa.column("asset_type", sa.String()),
        sa.column("strategies", sa.JSON()),
        sa.column("active", sa.Boolean()),
    )
    op.bulk_insert(
        watchlists,
        [
            {
                "symbol": sym,
                "asset_type": "EQUITY",
                "strategies": ["VERTICAL_SPREAD"],
                "active": True,
            }
            for sym in seed_symbols
        ],
    )


def downgrade() -> None:
    op.drop_index("idx_watchlists_active", table_name="watchlists")
    op.drop_table("watchlists")
