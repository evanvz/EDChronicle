"""Confirms the two new BGS/RES-status tables exist after migration --
same fixture shape as test_faction_snapshot_freshness.py."""
import pytest

from persistence.database import Database
from persistence.schema import SCHEMA_SQL


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.executescript(SCHEMA_SQL)
    database.run_migrations()
    return database


def _table_columns(db, table_name):
    rows = db.conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {r["name"] for r in rows}


def test_system_bgs_status_table_exists(db):
    cols = _table_columns(db, "system_bgs_status")
    assert cols == {
        "system_address", "system_name", "conflicts", "faction_states",
        "data_timestamp", "source",
        "economy", "second_economy", "government", "security",
        "population", "allegiance", "profile_timestamp",
    }


def test_system_res_sites_table_exists(db):
    cols = _table_columns(db, "system_res_sites")
    assert cols == {
        "system_address", "system_name", "tiers", "data_timestamp", "source",
    }


def test_system_bgs_status_upsert_keyed_on_system_address(db):
    db.execute(
        "INSERT INTO system_bgs_status (system_address, system_name, data_timestamp) VALUES (?, ?, ?)",
        (1, "Sol", "2026-08-23T00:00:00Z"),
    )
    with pytest.raises(Exception):
        db.execute(
            "INSERT INTO system_bgs_status (system_address, system_name, data_timestamp) VALUES (?, ?, ?)",
            (1, "Sol", "2026-08-23T01:00:00Z"),
        )
