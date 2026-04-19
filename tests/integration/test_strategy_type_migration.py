from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from darth_schwader.config import get_settings

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def alembic_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[Config, Path]]:
    db_file = tmp_path / "migration.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_file}")
    get_settings.cache_clear()
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    yield cfg, db_file
    get_settings.cache_clear()


def _read_check_sql(db_file: Path, table: str, constraint: str) -> str:
    conn = sqlite3.connect(db_file)
    try:
        ((sql,),) = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchall()
    finally:
        conn.close()

    for line in sql.splitlines():
        if f"CONSTRAINT {constraint} " in line:
            return str(line.strip().rstrip(","))
    raise AssertionError(f"constraint {constraint} not found on table {table}")


def test_upgrade_extends_strategy_enum_on_signals_orders_positions(
    alembic_config: tuple[Config, Path],
) -> None:
    cfg, db_file = alembic_config
    command.upgrade(cfg, "head")

    for table in ("signals", "orders", "positions"):
        sql = _read_check_sql(db_file, table, "strategytype")
        for value in ("VERTICAL_SPREAD", "LONG_EQUITY", "SHORT_FUTURE"):
            assert f"'{value}'" in sql, f"{value} missing from {table}.strategytype"


def test_upgrade_adds_bracket_columns_and_index_on_orders(
    alembic_config: tuple[Config, Path],
) -> None:
    cfg, db_file = alembic_config
    command.upgrade(cfg, "head")

    conn = sqlite3.connect(db_file)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(orders)").fetchall()}
        assert {"parent_order_id", "bracket_role", "stop_price", "target_price"} <= cols

        indexes = {row[1] for row in conn.execute("PRAGMA index_list(orders)").fetchall()}
        assert "idx_orders_parent" in indexes

        bracket_sql = _read_check_sql(db_file, "orders", "ck_orders_bracket_role")
        assert "'ENTRY'" in bracket_sql
        assert "'STOP'" in bracket_sql
        assert "'TARGET'" in bracket_sql
    finally:
        conn.close()


def test_downgrade_restores_v1_enum_and_drops_bracket_columns(
    alembic_config: tuple[Config, Path],
) -> None:
    cfg, db_file = alembic_config
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "0002_watchlist")

    conn = sqlite3.connect(db_file)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(orders)").fetchall()}
        assert "parent_order_id" not in cols
        assert "bracket_role" not in cols
    finally:
        conn.close()

    for table in ("signals", "orders", "positions"):
        sql = _read_check_sql(db_file, table, "strategytype")
        assert "VERTICAL_SPREAD" in sql
        assert "LONG_EQUITY" not in sql
        assert "SHORT_FUTURE" not in sql
