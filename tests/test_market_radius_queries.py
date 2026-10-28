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


def test_search_market_prices_excludes_fleet_carrier_by_market_station_type(repo):
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_market_row(repo, 1001, "gold", "Sol", station_type="FleetCarrier", sell_price=5000)

    results = repo.search_market_prices("gold", 0.0, 0.0, 0.0, 50.0)
    assert results == []


def test_search_market_prices_excludes_fleet_carrier_by_station_info_type_even_if_market_type_blank(repo):
    # Confirmed live: EDDN's commodity payload doesn't always carry
    # stationType for carriers, leaving market_prices.station_type blank
    # ('' not NULL) while our own Docked-event-sourced station_info still
    # correctly knows it's a FleetCarrier -- must check both sources, not
    # just the market row's own (unreliable) station_type.
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_market_row(repo, 1001, "gold", "Sol", station_type="", sell_price=5000)
    repo.save_station_info(1001, "XBZ-9TZ", "Sol", "FleetCarrier", None, None, None, "2026-08-12T00:00:00Z")

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


# ---- prune_stale_market_prices ----

def test_prune_stale_market_prices_deletes_only_rows_past_cutoff(repo):
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_market_row(repo, 1001, "gold", "Sol", last_updated=_FRESH)
    _seed_market_row(repo, 1001, "silver", "Sol", last_updated="2026-01-01T00:00:00Z")

    deleted = repo.prune_stale_market_prices()

    assert deleted == 1
    remaining = repo.db.conn.execute("SELECT commodity_name FROM market_prices").fetchall()
    assert [r["commodity_name"] for r in remaining] == ["gold"]


def test_prune_stale_market_prices_batches_across_boundary(repo):
    # Regression test: this used to run as one giant DELETE, holding
    # SQLite's write lock for its entire duration (confirmed live: ~2
    # minutes at 1.5M+ rows), which starved other concurrent background
    # writers (the historical journal importer, the Player Faction daily
    # EDSM refresh) past their 30s busy_timeout, failing with "database is
    # locked". Now batched, committing after every batch_size rows -- seed
    # more stale rows than one batch to prove the loop correctly spans
    # multiple batches and still deletes everything stale.
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    for i in range(5):
        _seed_market_row(repo, 1001, f"stale{i}", "Sol", last_updated="2026-01-01T00:00:00Z")
    _seed_market_row(repo, 1001, "gold", "Sol", last_updated=_FRESH)

    deleted = repo.prune_stale_market_prices(batch_size=2)

    assert deleted == 5
    remaining = repo.db.conn.execute("SELECT commodity_name FROM market_prices").fetchall()
    assert [r["commodity_name"] for r in remaining] == ["gold"]


# ---- hub-first market search ----

def _hub_row(market_id, commodity="gold", sell_price=5000, pads=(None, None, None), station_type="Coriolis", faction=None):
    return {
        "market_id": market_id, "commodity": commodity, "station_name": f"Hub {market_id}",
        "station_type": station_type, "system_name": "Hubville", "sell_price": sell_price,
        "demand": 10, "stock": 0, "last_updated": _FRESH, "x": 3.0, "y": 4.0, "z": 0.0,
        "distance_ly": 5.0, "pads_small": pads[0], "pads_medium": pads[1], "pads_large": pads[2],
        "station_faction": faction,
    }


@pytest.fixture
def hub(monkeypatch):
    calls = []
    state = {"ret": []}

    def fake(base_url, commodities, x, y, z, radius, exclude_market_id=None):
        calls.append((base_url, list(commodities), exclude_market_id))
        return state["ret"]

    monkeypatch.setattr("persistence.repository.fetch_market_search", fake)
    monkeypatch.setattr(Repository, "hub_url", "http://hub")
    state["calls"] = calls
    return state


def test_hub_rows_used_when_hub_answers(repo, hub):
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_market_row(repo, 1001, "gold", "Sol", sell_price=9000)
    hub["ret"] = [_hub_row(2002, station_type="Coriolis")]

    results = repo.search_market_prices("gold", 0.0, 0.0, 0.0, 50.0)
    assert [r["market_id"] for r in results] == [2002]
    assert results[0]["distance_ly"] == 5.0
    assert results[0]["pad_known"] is True
    assert results[0]["pad_size"] == "L"


def test_hub_empty_list_is_an_answer(repo, hub):
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_market_row(repo, 1001, "gold", "Sol", sell_price=9000)
    hub["ret"] = []

    assert repo.search_market_prices("gold", 0.0, 0.0, 0.0, 50.0) == []


def test_hub_none_falls_back_to_local(repo, hub):
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_market_row(repo, 1001, "gold", "Sol", sell_price=9000)
    hub["ret"] = None

    results = repo.search_market_prices("gold", 0.0, 0.0, 0.0, 50.0)
    assert [r["market_id"] for r in results] == [1001]


def test_wide_radius_stays_local(repo, hub):
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_market_row(repo, 1001, "gold", "Sol", sell_price=9000)
    hub["ret"] = []

    results = repo.search_market_prices("gold", 0.0, 0.0, 0.0, 1500.0)
    assert hub["calls"] == []
    assert [r["market_id"] for r in results] == [1001]


def test_no_hub_url_never_calls_hub(repo, hub, monkeypatch):
    monkeypatch.setattr(Repository, "hub_url", "")
    repo.search_market_prices("gold", 0.0, 0.0, 0.0, 50.0)
    repo.search_market_prices_multi(["gold"], 0.0, 0.0, 0.0, 50.0)
    assert hub["calls"] == []


def test_hub_rows_fill_pads_from_local_station_info(repo, hub):
    repo.save_station_info(3003, "Pad Place", "Hubville", "Outpost", 0, 0, 2, "2026-08-12T00:00:00Z")
    hub["ret"] = [
        _hub_row(4004, sell_price=9000, station_type=None),
        _hub_row(3003, sell_price=5000, station_type=None),
    ]

    results = repo.search_market_prices("gold", 0.0, 0.0, 0.0, 50.0)
    assert [r["market_id"] for r in results] == [3003, 4004]
    assert results[0]["pad_known"] is True
    assert results[1]["pad_known"] is False


def test_multi_groups_hub_rows_by_commodity(repo, hub):
    repo.save_station_info(3003, "Pad Place", "Hubville", "Outpost", 0, 0, 2, "2026-08-12T00:00:00Z")
    hub["ret"] = [
        _hub_row(4004, "gold", 9000, station_type=None),
        _hub_row(3003, "gold", 5000, station_type=None),
        _hub_row(3003, "silver", 100, station_type=None),
    ]

    by = repo.search_market_prices_multi(["gold", "silver", "tin"], 0.0, 0.0, 0.0, 50.0)
    assert [r["market_id"] for r in by["gold"]] == [3003, 4004]
    assert [r["market_id"] for r in by["silver"]] == [3003]
    assert by["tin"] == []
    assert by["gold"][0]["commodity_name"] == "gold"


def test_multi_chunks_over_200_and_falls_back_if_any_chunk_fails(repo, hub, monkeypatch):
    _seed_coords(repo, "Sol", 0.0, 0.0, 0.0)
    _seed_market_row(repo, 1001, "gold", "Sol", sell_price=9000)
    names = ["gold"] + [f"c{i}" for i in range(250)]
    answers = iter([[], None])
    monkeypatch.setattr(
        "persistence.repository.fetch_market_search", lambda *a, **k: next(answers)
    )

    by = repo.search_market_prices_multi(names, 0.0, 0.0, 0.0, 50.0)
    assert [r["market_id"] for r in by["gold"]] == [1001]
