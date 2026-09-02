"""Tests for EddnMarketCache.on_bgs_status_seen()/on_res_signal_seen() --
the two new buffers added alongside the existing seven (see
_faction_buffer/on_faction_seen for the closest existing model: same
key-by-system_address, same store-a-tuple-in-a-dict shape). Confirms the
buffer/pop_buffers round trip AND that write_buffers() actually lands rows
in system_bgs_status/system_res_sites via a real temp-file Repository --
same fixture pattern as test_bgs_status_repository.py."""
import json

import pytest

from edc.core.eddn_market import EddnMarketCache, write_buffers
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL


@pytest.fixture
def repo(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return Repository(db)


def test_pop_buffers_returns_bgs_status_and_res_sites_in_10_tuple_and_clears_them():
    cache = EddnMarketCache(repo=None)
    conflicts = [{"WarType": "war", "Status": "active", "Faction1": {"Name": "A", "WonDays": 1}, "Faction2": {"Name": "B", "WonDays": 0}}]
    factions = [{"Name": "B", "FactionState": "War", "ActiveStates": [{"State": "War"}], "PendingStates": [], "RecoveringStates": []}]
    cache.on_bgs_status_seen(1, "Sol", conflicts, factions, "2026-08-23T10:00:00Z")
    cache.on_res_signal_seen(1, "Sol", ["Hazardous", "High"], "2026-08-23T10:00:00Z")

    result = cache.pop_buffers()
    assert len(result) == 10
    coords, market, ftns, stations, codex, fcmaterials, carrier_access, bgs_status, res_sites, mining_signals = result

    assert bgs_status == [(1, ("Sol", conflicts, factions, "2026-08-23T10:00:00Z"))]
    assert res_sites == [(1, ("Sol", ["Hazardous", "High"], "2026-08-23T10:00:00Z"))]

    # The two new internal buffers are now empty.
    assert cache._bgs_status_buffer == {}
    assert cache._res_sites_buffer == {}


def test_on_body_mining_signal_seen_buffers_and_dedupes():
    cache = EddnMarketCache(repo=None)
    cache.on_body_mining_signal_seen(1281804437875, "HR 8769 A 1", 3)
    cache.on_body_mining_signal_seen(1281804437875, "HR 8769 A 1", 6)  # later sighting wins

    _, _, _, _, _, _, _, _, _, mining_signals = cache.pop_buffers()
    assert mining_signals == [((1281804437875, "HR 8769 A 1"), 6)]
    assert cache._mining_signal_buffer == {}


def test_on_body_mining_signal_seen_ignores_malformed_input():
    cache = EddnMarketCache(repo=None)
    cache.on_body_mining_signal_seen(None, "HR 8769 A 1", 6)
    cache.on_body_mining_signal_seen(1, "", 6)

    _, _, _, _, _, _, _, _, _, mining_signals = cache.pop_buffers()
    assert mining_signals == []


def test_write_buffers_persists_mining_signals_to_db(repo):
    write_buffers(repo, [], [], [], [], [], [], [], [], [], [((1, "Body 1"), 6)])

    row = repo.db.conn.execute(
        "SELECT * FROM net.spansh_bodies WHERE system_address = 1 AND body_name = 'Body 1'"
    ).fetchone()
    assert row is not None
    assert row["surface_mining_signals"] == 6


def test_on_bgs_status_seen_ignores_malformed_input():
    cache = EddnMarketCache(repo=None)
    cache.on_bgs_status_seen(None, "Sol", [], [], "2026-08-23T10:00:00Z")
    cache.on_bgs_status_seen(1, "", [], [], "2026-08-23T10:00:00Z")

    _, _, _, _, _, _, _, bgs_status, _, _ = cache.pop_buffers()
    assert bgs_status == []


def test_on_res_signal_seen_ignores_malformed_input():
    cache = EddnMarketCache(repo=None)
    cache.on_res_signal_seen(None, "Sol", ["High"], "2026-08-23T10:00:00Z")
    cache.on_res_signal_seen(1, "", ["High"], "2026-08-23T10:00:00Z")

    _, _, _, _, _, _, _, _, res_sites, _ = cache.pop_buffers()
    assert res_sites == []


def test_write_buffers_persists_bgs_status_and_res_sites_to_db(repo):
    conflicts = [{"WarType": "civilwar", "Status": "pending", "Faction1": {"Name": "C", "WonDays": 0}, "Faction2": {"Name": "D", "WonDays": 0}}]
    factions = []
    bgs_status = [(1, ("Sol", conflicts, factions, "2026-08-23T10:00:00Z"))]
    res_sites = [(1, ("Sol", ["Hazardous", "Low"], "2026-08-23T10:00:00Z"))]

    write_buffers(repo, [], [], [], [], [], [], [], bgs_status, res_sites)

    bgs_row = repo.db.conn.execute(
        "SELECT * FROM system_bgs_status WHERE system_address = 1"
    ).fetchone()
    assert bgs_row is not None
    assert bgs_row["system_name"] == "Sol"
    stored_conflicts = json.loads(bgs_row["conflicts"])
    assert stored_conflicts[0]["faction1"] == "C"
    assert stored_conflicts[0]["faction2"] == "D"

    res_row = repo.db.conn.execute(
        "SELECT * FROM system_res_sites WHERE system_address = 1"
    ).fetchone()
    assert res_row is not None
    assert res_row["system_name"] == "Sol"
    assert json.loads(res_row["tiers"]) == ["Hazardous", "Low"]


def test_cache_pop_buffers_then_write_buffers_end_to_end(repo):
    cache = EddnMarketCache(repo=repo)
    conflicts = [{"WarType": "war", "Status": "active", "Faction1": {"Name": "E", "WonDays": 3}, "Faction2": {"Name": "F", "WonDays": 1}}]
    cache.on_bgs_status_seen(42, "Deciat", conflicts, [], "2026-08-23T12:00:00Z")
    cache.on_res_signal_seen(42, "Deciat", ["Nominal"], "2026-08-23T12:00:00Z")

    coords, market, factions, stations, codex, fcmaterials, carrier_access, bgs_status, res_sites, mining_signals = cache.pop_buffers()
    write_buffers(repo, coords, market, factions, stations, codex, fcmaterials, carrier_access, bgs_status, res_sites, mining_signals)

    bgs_row = repo.db.conn.execute(
        "SELECT * FROM system_bgs_status WHERE system_address = 42"
    ).fetchone()
    assert bgs_row is not None
    assert json.loads(bgs_row["conflicts"])[0]["faction1"] == "E"

    res_row = repo.db.conn.execute(
        "SELECT * FROM system_res_sites WHERE system_address = 42"
    ).fetchone()
    assert res_row is not None
    assert json.loads(res_row["tiers"]) == ["Nominal"]
