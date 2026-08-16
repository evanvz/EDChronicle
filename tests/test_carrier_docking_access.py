"""Tests for Repository.save_carrier_docking_access_batch() and
search_fleet_carrier_materials()'s docking-access filter -- real SQLite
(temp file), not mocks, matching this repo's established pattern (see
tests/test_fleet_carrier_materials.py)."""
from datetime import datetime, timedelta, timezone

import pytest

from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL

_FRESH = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def repo(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return Repository(db)


def _seed_station(repo, market_id, system_name, station_type="FleetCarrier"):
    repo.save_station_info_batch([{
        "market_id": market_id,
        "station_name": "Test Carrier",
        "system_name": system_name,
        "station_type": station_type,
        "pads_small": None,
        "pads_medium": None,
        "pads_large": 1,
        "timestamp": "2026-08-12T00:00:00Z",
    }])


def _seed_coords(repo, system_name, x, y, z):
    repo.save_system_coords_batch([(system_name, x, y, z, "2026-08-12T00:00:00Z")])


def _seed_material(repo, market_id, symbol, price=1000, stock=5, demand=0,
                    last_updated=_FRESH, carrier_name="Test Carrier", carrier_id="ABC-123"):
    repo.save_fleet_carrier_materials_batch([
        (market_id, symbol, carrier_name, carrier_id, price, stock, demand, last_updated)
    ])


# --- save_carrier_docking_access_batch() ---

def test_save_carrier_docking_access_inserts_skeletal_row_when_none_exists(repo):
    # No _seed_station() call -- simulates a commodity/3 sighting arriving
    # before any Docked sighting for this market_id.
    repo.save_carrier_docking_access_batch([(1001, "all", "2026-08-12T00:00:00Z")])
    row = repo.db.conn.execute(
        "SELECT market_id, carrier_docking_access FROM station_info WHERE market_id = 1001"
    ).fetchone()
    assert row["market_id"] == 1001
    assert row["carrier_docking_access"] == "all"


def test_save_carrier_docking_access_updates_existing_row_without_clobbering_other_columns(repo):
    _seed_station(repo, 1001, "Sol")
    repo.save_carrier_docking_access_batch([(1001, "friends", "2026-08-12T00:00:00Z")])
    row = repo.db.conn.execute(
        "SELECT system_name, carrier_docking_access FROM station_info WHERE market_id = 1001"
    ).fetchone()
    assert row["system_name"] == "Sol"
    assert row["carrier_docking_access"] == "friends"


def test_docked_sighting_after_docking_access_does_not_clobber_it(repo):
    # Order-independence: a commodity/3 sighting (docking access) arriving
    # BEFORE a Docked sighting (station_info's other fields) must survive
    # that later Docked upsert untouched.
    repo.save_carrier_docking_access_batch([(1001, "squadron", "2026-08-12T00:00:00Z")])
    _seed_station(repo, 1001, "Sol")
    row = repo.db.conn.execute(
        "SELECT system_name, carrier_docking_access FROM station_info WHERE market_id = 1001"
    ).fetchone()
    assert row["system_name"] == "Sol"
    assert row["carrier_docking_access"] == "squadron"


# --- search_fleet_carrier_materials() docking-access filter ---

def test_confirmed_open_carrier_is_included(repo):
    _seed_station(repo, 1001, "Sol")
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_material(repo, 1001, "graphene")
    repo.save_carrier_docking_access_batch([(1001, "all", "2026-08-12T00:00:00Z")])

    result = repo.search_fleet_carrier_materials(["graphene"], 0.0, 0.0, 0.0, 50.0)
    assert len(result["graphene"]) == 1
    assert result["graphene"][0]["docking_access"] == "all"


def test_unknown_access_carrier_is_included(repo):
    _seed_station(repo, 1001, "Sol")
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_material(repo, 1001, "graphene")
    # No save_carrier_docking_access_batch() call at all.

    result = repo.search_fleet_carrier_materials(["graphene"], 0.0, 0.0, 0.0, 50.0)
    assert len(result["graphene"]) == 1
    assert result["graphene"][0]["docking_access"] is None


@pytest.mark.parametrize("restricted_value", ["friends", "squadron", "squadronfriends", "none"])
def test_confirmed_restricted_carrier_is_excluded(repo, restricted_value):
    _seed_station(repo, 1001, "Sol")
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_material(repo, 1001, "graphene")
    repo.save_carrier_docking_access_batch([(1001, restricted_value, "2026-08-12T00:00:00Z")])

    result = repo.search_fleet_carrier_materials(["graphene"], 0.0, 0.0, 0.0, 50.0)
    assert result["graphene"] == []
