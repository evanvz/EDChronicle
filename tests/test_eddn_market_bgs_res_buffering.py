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


def test_pop_buffers_returns_bgs_status_and_res_sites_in_12_tuple_and_clears_them():
    cache = EddnMarketCache(repo=None)
    conflicts = [{"WarType": "war", "Status": "active", "Faction1": {"Name": "A", "WonDays": 1}, "Faction2": {"Name": "B", "WonDays": 0}}]
    factions = [{"Name": "B", "FactionState": "War", "ActiveStates": [{"State": "War"}], "PendingStates": [], "RecoveringStates": []}]
    cache.on_bgs_status_seen(1, "Sol", conflicts, factions, "2026-08-23T10:00:00Z")
    cache.on_res_signal_seen(1, "Sol", ["Hazardous", "High"], "2026-08-23T10:00:00Z")

    result = cache.pop_buffers()
    assert len(result) == 12
    coords, market, ftns, stations, codex, fcmaterials, carrier_access, bgs_status, res_sites, body_signals, system_profiles, body_scans = result

    assert bgs_status == [(1, ("Sol", conflicts, factions, "2026-08-23T10:00:00Z"))]
    assert res_sites == [(1, ("Sol", ["Hazardous", "High"], "2026-08-23T10:00:00Z"))]

    # The two new internal buffers are now empty.
    assert cache._bgs_status_buffer == {}
    assert cache._res_sites_buffer == {}


def test_on_body_signals_seen_buffers_and_merges():
    cache = EddnMarketCache(repo=None)
    cache.on_body_signals_seen(1281804437875, "HR 8769 A 1", {"mining": 3})
    cache.on_body_signals_seen(1281804437875, "HR 8769 A 1", {"mining": 6, "geo": 3})  # merges, mining overwritten

    _, _, _, _, _, _, _, _, _, body_signals, _, _ = cache.pop_buffers()
    assert body_signals == [((1281804437875, "HR 8769 A 1"), {"mining": 6, "geo": 3})]
    assert cache._body_signals_buffer == {}


def test_on_body_signals_seen_ignores_malformed_input():
    cache = EddnMarketCache(repo=None)
    cache.on_body_signals_seen(None, "HR 8769 A 1", {"mining": 6})
    cache.on_body_signals_seen(1, "", {"mining": 6})
    cache.on_body_signals_seen(1, "HR 8769 A 1", {})

    _, _, _, _, _, _, _, _, _, body_signals, _, _ = cache.pop_buffers()
    assert body_signals == []


def test_write_buffers_persists_body_signals_to_db(repo):
    write_buffers(repo, [], [], [], [], [], [], [], [], [], [((1, "Body 1"), {"mining": 6, "bio": 4})])

    row = repo.db.conn.execute(
        "SELECT * FROM net.spansh_bodies WHERE system_address = 1 AND body_name = 'Body 1'"
    ).fetchone()
    assert row is not None
    assert row["surface_mining_signals"] == 6
    assert row["bio_signals"] == 4


def test_on_system_profile_seen_buffers_and_dedupes():
    cache = EddnMarketCache(repo=None)
    profile1 = {"economy": "$economy_HighTech;"}
    profile2 = {"economy": "$economy_Agri;"}
    cache.on_system_profile_seen(1, "Sol", profile1, "2026-09-01T00:00:00Z")
    cache.on_system_profile_seen(1, "Sol", profile2, "2026-09-02T00:00:00Z")  # later sighting wins

    *_, system_profiles, _ = cache.pop_buffers()
    assert system_profiles == [(1, ("Sol", profile2, "2026-09-02T00:00:00Z"))]
    assert cache._system_profile_buffer == {}


def test_on_system_profile_seen_ignores_malformed_input():
    cache = EddnMarketCache(repo=None)
    cache.on_system_profile_seen(None, "Sol", {"economy": "x"}, "2026-09-01T00:00:00Z")
    cache.on_system_profile_seen(1, "", {"economy": "x"}, "2026-09-01T00:00:00Z")

    *_, system_profiles, _ = cache.pop_buffers()
    assert system_profiles == []


def test_write_buffers_persists_system_profile_to_db(repo):
    profile = {
        "economy": "$economy_Agri;", "second_economy": "$economy_HighTech;",
        "government": "$government_Patronage;", "security": "$SYSTEM_SECURITY_medium;",
        "population": 12345, "allegiance": "Empire",
    }
    write_buffers(repo, [], [], [], [], [], [], [], [], [], [], [(1, ("Sol", profile, "2026-09-02T00:00:00Z"))])

    row = repo.get_system_profile_by_name("Sol")
    assert row is not None
    assert row["economy"] == "$economy_Agri;"
    assert row["population"] == 12345


def test_on_body_scan_seen_buffers_real_message(repo):
    cache = EddnMarketCache(repo=repo)
    msg = {
        "timestamp": "2026-09-02T15:04:29Z", "event": "Scan", "ScanType": "Detailed",
        "BodyName": "HR 8769 A 1", "BodyID": 5, "StarSystem": "HR 8769",
        "SystemAddress": 1281804437875, "DistanceFromArrivalLS": 357.229551,
        "TidalLock": False, "PlanetClass": "High metal content body", "Atmosphere": "",
        "AtmosphereType": "None", "Volcanism": "major silicate vapour geysers volcanism",
        "MassEM": 5.148939, "Radius": 9745449.0, "SurfaceGravity": 21.608442,
        "SurfaceTemperature": 712.736511, "SurfacePressure": 0.0, "Landable": True,
        "WasMapped": True,
    }
    cache.on_body_scan_seen(msg)

    *_, body_scans = cache.pop_buffers()
    assert len(body_scans) == 1
    (system_address, body_name), fields = body_scans[0]
    assert system_address == 1281804437875
    assert body_name == "HR 8769 A 1"
    assert fields[0] == "High metal content body"  # planet_class
    assert fields[3] == 1  # landable


def test_on_body_scan_seen_ignores_non_planet_body():
    cache = EddnMarketCache(repo=None)
    cache.on_body_scan_seen({
        "SystemAddress": 1, "BodyName": "Some Star", "StarType": "K",
    })

    *_, body_scans = cache.pop_buffers()
    assert body_scans == []


def test_write_buffers_persists_body_scan_to_db(repo):
    fields = (
        "High metal content body", 357.229551, None, 1, 21.608442, 9745449.0,
        5.148939, 712.736511, 0.0, "None", "major silicate vapour geysers volcanism",
        0, 1, "2026-09-02T15:04:29Z",
    )
    write_buffers(repo, [], [], [], [], [], [], [], [], [], [], [], [((1281804437875, "HR 8769 A 1"), fields)])

    rows = repo.get_spansh_bodies(1281804437875)
    assert len(rows) == 1
    assert rows[0]["body_name"] == "HR 8769 A 1"
    assert rows[0]["planet_class"] == "High metal content body"
    assert rows[0]["surface_gravity"] == 21.608442


def test_write_buffers_body_scan_does_not_clobber_spansh_estimated_value(repo):
    repo.save_spansh_body(
        system_address=1, body_name="Body 1", planet_class="Icy body",
        distance_ls=100.0, estimated_value=50000, landable=0,
    )
    fields = ("Icy body", 100.0, None, 0, None, None, None, None, None, None, None, None, None, None)
    write_buffers(repo, [], [], [], [], [], [], [], [], [], [], [], [((1, "Body 1"), fields)])

    rows = repo.get_spansh_bodies(1)
    assert rows[0]["estimated_value"] == 50000


def test_on_bgs_status_seen_ignores_malformed_input():
    cache = EddnMarketCache(repo=None)
    cache.on_bgs_status_seen(None, "Sol", [], [], "2026-08-23T10:00:00Z")
    cache.on_bgs_status_seen(1, "", [], [], "2026-08-23T10:00:00Z")

    _, _, _, _, _, _, _, bgs_status, _, _, _, _ = cache.pop_buffers()
    assert bgs_status == []


def test_on_res_signal_seen_ignores_malformed_input():
    cache = EddnMarketCache(repo=None)
    cache.on_res_signal_seen(None, "Sol", ["High"], "2026-08-23T10:00:00Z")
    cache.on_res_signal_seen(1, "", ["High"], "2026-08-23T10:00:00Z")

    _, _, _, _, _, _, _, _, res_sites, _, _, _ = cache.pop_buffers()
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

    coords, market, factions, stations, codex, fcmaterials, carrier_access, bgs_status, res_sites, body_signals, system_profiles, body_scans = cache.pop_buffers()
    write_buffers(repo, coords, market, factions, stations, codex, fcmaterials, carrier_access, bgs_status, res_sites, body_signals, system_profiles, body_scans)

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
