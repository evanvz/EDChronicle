"""Tests for Repository.save_fleet_carrier_materials_batch() and
search_fleet_carrier_materials() -- real SQLite (temp file), not mocks."""
import inspect
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


def _seed_station(repo, market_id, system_name, station_type="FleetCarrier", last_visited="2026-08-12T00:00:00Z"):
    repo.save_station_info_batch([{
        "market_id": market_id,
        "station_name": "Test Carrier",
        "system_name": system_name,
        "station_type": station_type,
        "pads_small": None,
        "pads_medium": None,
        "pads_large": 1,
        "timestamp": last_visited,
    }])


def _seed_coords(repo, system_name, x, y, z):
    repo.save_system_coords_batch([(system_name, x, y, z, "2026-08-12T00:00:00Z")])


def _seed_material(repo, market_id, symbol, price=1000, stock=5, demand=0,
                    last_updated=_FRESH, carrier_name="Test Carrier", carrier_id="ABC-123"):
    repo.save_fleet_carrier_materials_batch([
        (market_id, symbol, carrier_name, carrier_id, price, stock, demand, last_updated)
    ])


def test_finds_material_within_radius(repo):
    _seed_station(repo, 1001, "Sol")
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_material(repo, 1001, "graphene")

    result = repo.search_fleet_carrier_materials(["graphene"], 0.0, 0.0, 0.0, 50.0)
    assert len(result["graphene"]) == 1
    assert result["graphene"][0]["carrier_name"] == "Test Carrier"
    assert result["graphene"][0]["system_name"] == "Sol"


def test_excludes_material_outside_radius(repo):
    _seed_station(repo, 1001, "Far System")
    _seed_coords(repo, "Far System", 1000.0, 0.0, 0.0)
    _seed_material(repo, 1001, "graphene")

    result = repo.search_fleet_carrier_materials(["graphene"], 0.0, 0.0, 0.0, 50.0)
    assert result["graphene"] == []


def test_carrier_with_no_station_info_row_is_excluded(repo):
    # No _seed_station() call -- simulates a carrier we've never had a
    # Docked sighting for, so its location is genuinely unknown.
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_material(repo, 2002, "graphene")

    result = repo.search_fleet_carrier_materials(["graphene"], 0.0, 0.0, 0.0, 50.0)
    assert result["graphene"] == []


def test_uses_inner_join_against_station_info_not_left_join():
    # search_fleet_carrier_materials() joins station_info (for system_name)
    # and then system_coords (for x/y/z), since fleet_carrier_materials has
    # no location columns of its own. That means, for this exact query,
    # INNER JOIN and LEFT JOIN produce byte-identical results for ANY seeded
    # data: a row unmatched in station_info gets si.system_name = NULL under
    # a LEFT JOIN, which then fails to match any row in system_coords (NULL
    # never equals a system_name), so the row is excluded from the result
    # exactly as an INNER JOIN would -- confirmed empirically, no
    # data-seeding test can distinguish the two join types here. Pinning the
    # SQL text itself is the only way to catch a future INNER -> LEFT edit.
    source = inspect.getsource(Repository.search_fleet_carrier_materials)
    assert "INNER JOIN net.station_info" in source
    assert "LEFT JOIN net.station_info" not in source


def test_stale_listing_excluded_past_7_day_cutoff(repo):
    _seed_station(repo, 1001, "Sol")
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_material(repo, 1001, "graphene", last_updated="2026-07-01T00:00:00Z")

    result = repo.search_fleet_carrier_materials(["graphene"], 0.0, 0.0, 0.0, 50.0)
    assert result["graphene"] == []


def test_multiple_symbols_returned_in_one_call(repo):
    _seed_station(repo, 1001, "Sol")
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_material(repo, 1001, "graphene")
    _seed_material(repo, 1001, "geneticrepairmeds")

    result = repo.search_fleet_carrier_materials(["graphene", "geneticrepairmeds", "unseen"], 0.0, 0.0, 0.0, 50.0)
    assert len(result["graphene"]) == 1
    assert len(result["geneticrepairmeds"]) == 1
    assert result["unseen"] == []


def test_exclude_market_id_skips_current_carrier(repo):
    _seed_station(repo, 1001, "Sol")
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_material(repo, 1001, "graphene")

    result = repo.search_fleet_carrier_materials(["graphene"], 0.0, 0.0, 0.0, 50.0, exclude_market_id=1001)
    assert result["graphene"] == []


def test_sorted_closest_first(repo):
    _seed_station(repo, 1001, "Near")
    _seed_coords(repo, "Near", 10.0, 0.0, 0.0)
    _seed_material(repo, 1001, "graphene", carrier_name="Near Carrier")

    _seed_station(repo, 1002, "Far")
    _seed_coords(repo, "Far", 40.0, 0.0, 0.0)
    _seed_material(repo, 1002, "graphene", carrier_name="Far Carrier")

    result = repo.search_fleet_carrier_materials(["graphene"], 0.0, 0.0, 0.0, 50.0)
    assert [r["carrier_name"] for r in result["graphene"]] == ["Near Carrier", "Far Carrier"]


def test_upsert_overwrites_previous_listing_for_same_carrier_and_material(repo):
    _seed_station(repo, 1001, "Sol")
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_material(repo, 1001, "graphene", price=1000, stock=5)
    _seed_material(repo, 1001, "graphene", price=2000, stock=9)

    result = repo.search_fleet_carrier_materials(["graphene"], 0.0, 0.0, 0.0, 50.0)
    assert len(result["graphene"]) == 1
    assert result["graphene"][0]["price"] == 2000
    assert result["graphene"][0]["stock"] == 9


def test_empty_symbol_list_returns_empty_dict(repo):
    result = repo.search_fleet_carrier_materials([], 0.0, 0.0, 0.0, 50.0)
    assert result == {}


def test_zero_stock_listing_excluded_even_if_symbol_and_location_match(repo):
    # stock=0 means this is a purchase order (Demand > 0), not a sale --
    # a carrier buying graphene must never show up as a place to buy it.
    _seed_station(repo, 1001, "Sol")
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_material(repo, 1001, "graphene", stock=0, demand=5)

    result = repo.search_fleet_carrier_materials(["graphene"], 0.0, 0.0, 0.0, 50.0)
    assert result["graphene"] == []


def test_search_succeeds_with_more_systems_than_old_sqlite_variable_limit(repo):
    # Regression test for the production crash this fix addresses:
    # sqlite3.OperationalError: too many SQL variables. The OLD
    # implementation built one SQL bound parameter per system_coords row
    # inside the search radius; with system_coords fed continuously and
    # unboundedly by the EDDN listener, a real search once had to bind
    # 36,148 parameters against this build's 32,766 limit
    # (conn.getlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER)). Seed comfortably
    # past that limit here so this test would fail with that exact
    # OperationalError against the pre-fix code, and passes against the
    # JOIN-based rewrite (whose bound-parameter count doesn't grow with
    # table size at all).
    dummy_coords = [
        (f"Dummy System {i}", float(i % 100), float((i // 100) % 100), float(i // 10000), "2026-08-12T00:00:00Z")
        for i in range(33_000)
    ]
    repo.save_system_coords_batch(dummy_coords)

    _seed_station(repo, 1001, "Sol")
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_material(repo, 1001, "graphene")

    result = repo.search_fleet_carrier_materials(["graphene"], 0.0, 0.0, 0.0, 2000.0)

    assert len(result["graphene"]) == 1
    assert result["graphene"][0]["carrier_name"] == "Test Carrier"


def test_prune_stale_fleet_carrier_materials_deletes_only_rows_past_7_day_cutoff(repo):
    _seed_station(repo, 1001, "Sol")
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_material(repo, 1001, "graphene", last_updated=_FRESH)  # fresh, within 7 days
    _seed_material(repo, 1001, "geneticrepairmeds", last_updated="2026-07-01T00:00:00Z")  # stale

    deleted = repo.prune_stale_fleet_carrier_materials()

    assert deleted == 1
    remaining = repo.db.conn.execute(
        "SELECT material_symbol FROM fleet_carrier_materials"
    ).fetchall()
    assert [r["material_symbol"] for r in remaining] == ["graphene"]


def test_prune_stale_fleet_carrier_materials_batches_across_boundary(repo):
    # Regression test: the prune used to run as one giant DELETE, holding
    # SQLite's write lock for the whole operation and starving other
    # concurrent background writers (confirmed live: "database is locked"
    # in the historical journal importer and the Player Faction daily
    # refresh worker). Now batched, committing after every batch_size rows
    # -- seed more stale rows than one batch to prove the loop correctly
    # spans multiple batches and still deletes everything stale.
    _seed_station(repo, 1001, "Sol")
    for i in range(5):
        _seed_material(repo, 1001, f"stale{i}", last_updated="2026-07-01T00:00:00Z")
    _seed_material(repo, 1001, "graphene", last_updated=_FRESH)

    deleted = repo.prune_stale_fleet_carrier_materials(batch_size=2)

    assert deleted == 5
    remaining = repo.db.conn.execute(
        "SELECT material_symbol FROM fleet_carrier_materials"
    ).fetchall()
    assert [r["material_symbol"] for r in remaining] == ["graphene"]
