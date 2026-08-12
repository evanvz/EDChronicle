"""Tests for Repository.save_fleet_carrier_materials_batch() and
search_fleet_carrier_materials() -- real SQLite (temp file), not mocks."""
import inspect

import pytest

from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL


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
                    last_updated="2026-08-12T00:00:00Z", carrier_name="Test Carrier", carrier_id="ABC-123"):
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
    # search_fleet_carrier_materials()'s WHERE clause filters on
    # si.system_name -- the only place a location lives, since
    # fleet_carrier_materials has no system_name column of its own. That
    # means, for this exact query, INNER JOIN and LEFT JOIN produce
    # byte-identical results for ANY seeded data: a row unmatched in
    # station_info gets si.system_name = NULL under a LEFT JOIN, and SQL's
    # `NULL IN (...)` is falsy, so the WHERE clause excludes it exactly as
    # an INNER JOIN would -- confirmed empirically, no data-seeding test
    # can distinguish the two join types here. Pinning the SQL text itself
    # is the only way to catch a future INNER -> LEFT edit.
    source = inspect.getsource(Repository.search_fleet_carrier_materials)
    assert "INNER JOIN station_info" in source
    assert "LEFT JOIN station_info" not in source


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
