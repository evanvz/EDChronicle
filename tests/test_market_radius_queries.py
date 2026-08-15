"""Tests for the 4 radius-based Repository search functions that read
system_coords via a JOIN (search_market_prices, search_market_prices_multi,
search_market_buy_prices, get_market_snapshot_in_radius) -- real SQLite
(temp file), not mocks. These functions had no test coverage before this
file; the tests here are safety nets for the IN-list -> JOIN rewrite
(behavior must not change), not TDD-red tests."""
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


def _seed_coords(repo, system_name, x, y, z):
    repo.save_system_coords_batch([(system_name, x, y, z, "2026-08-12T00:00:00Z")])


def _seed_market_row(
    repo, market_id, commodity_name, system_name, station_name="Test Station",
    station_type="Coriolis", sell_price=1000, buy_price=None, mean_price=1000,
    demand=0, demand_bracket=0, stock=None, stock_bracket=0,
    last_updated=_FRESH,
):
    repo.save_market_snapshot_batch([(
        market_id, commodity_name, station_name, station_type, system_name,
        sell_price, buy_price, mean_price, demand, demand_bracket,
        stock, stock_bracket, last_updated,
    )])


# ---- search_market_prices ----

def test_search_market_prices_finds_row_within_radius(repo):
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_market_row(repo, 1001, "gold", "Sol", sell_price=5000)

    results = repo.search_market_prices("gold", 0.0, 0.0, 0.0, 50.0)
    assert len(results) == 1
    assert results[0]["system_name"] == "Sol"
    assert results[0]["sell_price"] == 5000


def test_search_market_prices_excludes_row_outside_radius(repo):
    _seed_coords(repo, "Far System", 1000.0, 0.0, 0.0)
    _seed_market_row(repo, 1001, "gold", "Far System", sell_price=5000)

    results = repo.search_market_prices("gold", 0.0, 0.0, 0.0, 50.0)
    assert results == []


def test_search_market_prices_excludes_stale_row(repo):
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_market_row(repo, 1001, "gold", "Sol", sell_price=5000, last_updated="2026-01-01T00:00:00Z")

    results = repo.search_market_prices("gold", 0.0, 0.0, 0.0, 50.0)
    assert results == []


# ---- search_market_prices_multi ----

def test_search_market_prices_multi_finds_row_within_radius(repo):
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_market_row(repo, 1001, "gold", "Sol", sell_price=5000)

    by_commodity = repo.search_market_prices_multi(["gold", "silver"], 0.0, 0.0, 0.0, 50.0)
    assert len(by_commodity["gold"]) == 1
    assert by_commodity["silver"] == []


def test_search_market_prices_multi_excludes_row_outside_radius(repo):
    _seed_coords(repo, "Far System", 1000.0, 0.0, 0.0)
    _seed_market_row(repo, 1001, "gold", "Far System", sell_price=5000)

    by_commodity = repo.search_market_prices_multi(["gold"], 0.0, 0.0, 0.0, 50.0)
    assert by_commodity["gold"] == []


def test_search_market_prices_multi_excludes_stale_row(repo):
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_market_row(repo, 1001, "gold", "Sol", sell_price=5000, last_updated="2026-01-01T00:00:00Z")

    by_commodity = repo.search_market_prices_multi(["gold"], 0.0, 0.0, 0.0, 50.0)
    assert by_commodity["gold"] == []


# ---- search_market_buy_prices ----

def test_search_market_buy_prices_finds_row_within_radius(repo):
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_market_row(repo, 1001, "tritium", "Sol", sell_price=None, buy_price=8000, stock=500)

    results = repo.search_market_buy_prices("tritium", 0.0, 0.0, 0.0, 50.0)
    assert len(results) == 1
    assert results[0]["buy_price"] == 8000


def test_search_market_buy_prices_excludes_row_outside_radius(repo):
    _seed_coords(repo, "Far System", 1000.0, 0.0, 0.0)
    _seed_market_row(repo, 1001, "tritium", "Far System", sell_price=None, buy_price=8000, stock=500)

    results = repo.search_market_buy_prices("tritium", 0.0, 0.0, 0.0, 50.0)
    assert results == []


def test_search_market_buy_prices_excludes_stale_row(repo):
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_market_row(
        repo, 1001, "tritium", "Sol", sell_price=None, buy_price=8000, stock=500,
        last_updated="2026-01-01T00:00:00Z",
    )

    results = repo.search_market_buy_prices("tritium", 0.0, 0.0, 0.0, 50.0)
    assert results == []


# ---- get_market_snapshot_in_radius ----

def test_get_market_snapshot_in_radius_finds_station_within_radius(repo):
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_market_row(repo, 1001, "gold", "Sol", sell_price=5000)

    snapshot = repo.get_market_snapshot_in_radius(0.0, 0.0, 0.0, 50.0)
    assert 1001 in snapshot
    assert snapshot[1001]["sells"]["gold"] == (5000, 0, _FRESH)


def test_get_market_snapshot_in_radius_excludes_station_outside_radius(repo):
    _seed_coords(repo, "Far System", 1000.0, 0.0, 0.0)
    _seed_market_row(repo, 1001, "gold", "Far System", sell_price=5000)

    snapshot = repo.get_market_snapshot_in_radius(0.0, 0.0, 0.0, 50.0)
    assert snapshot == {}


def test_get_market_snapshot_in_radius_excludes_stale_row(repo):
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_market_row(repo, 1001, "gold", "Sol", sell_price=5000, last_updated="2026-01-01T00:00:00Z")

    snapshot = repo.get_market_snapshot_in_radius(0.0, 0.0, 0.0, 50.0)
    assert snapshot == {}
