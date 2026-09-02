"""journal_importer.py's one-time startup backfill needs the same
persistence as the live event path, or a from-scratch DB rebuild would
lose star resolution and Notable Stellar Phenomena confirmations even
though they're now saved live. Mirrors event_engine.py's logic closely
enough to produce the same resolved_bodies/codex_entries rows. Real
SQLite (temp file) and real Repository, matching this repo's convention
(see test_footfall_tracking.py)."""
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL

from edc.core.journal_importer import JournalImporter


def _importer(tmp_path, repo):
    imp = JournalImporter(tmp_path, repo)
    imp.current_system_address = 12345
    return imp


def _repo(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return Repository(db)


def test_star_scan_backfills_resolved_body(tmp_path):
    repo = _repo(tmp_path)
    imp = _importer(tmp_path, repo)

    imp._process_event({
        "event": "Scan", "ScanType": "AutoScan",
        "BodyName": "Test System", "BodyID": 0,
        "SystemAddress": 12345, "StarType": "K",
    })

    assert repo.get_resolved_body_ids(12345) == [0]


def test_belt_cluster_scan_not_backfilled_as_resolved(tmp_path):
    repo = _repo(tmp_path)
    imp = _importer(tmp_path, repo)

    imp._process_event({
        "event": "Scan", "ScanType": "AutoScan",
        "BodyName": "Test System A Belt Cluster 1", "BodyID": 3,
        "SystemAddress": 12345,
    })

    assert repo.get_resolved_body_ids(12345) == []


def test_nsp_codex_entry_backfilled(tmp_path):
    repo = _repo(tmp_path)
    imp = _importer(tmp_path, repo)

    imp._process_event({
        "event": "CodexEntry", "SystemAddress": 12345, "BodyID": 1,
        "Name_Localised": "Purpureum Metallic Crystals",
        "NearestDestination": "$Fixed_Event_Life_Cloud;",
        "EntryID": 2100802,
    })

    rows = repo.get_codex_entries(12345)
    assert len(rows) == 1
    assert rows[0]["is_phenomena"] == 1
    assert rows[0]["genus"] == "Purpureum"
    assert rows[0]["variant"]


def test_planetary_codex_entry_backfilled_not_phenomena(tmp_path):
    repo = _repo(tmp_path)
    imp = _importer(tmp_path, repo)

    imp._process_event({
        "event": "CodexEntry", "SystemAddress": 12345, "BodyID": 12,
        "Name_Localised": "Stratum Tectonicas - Green",
        "NearestDestination": "",
        "EntryID": 2420703,
    })

    rows = repo.get_codex_entries(12345)
    assert len(rows) == 1
    assert rows[0]["is_phenomena"] == 0
    assert rows[0]["variant"] == "Green"


def test_fssbodysignals_backfills_surface_mining_signals(tmp_path):
    # Surface Mining (Update 4.4): $PlanetaryMiningLocation_Name; must
    # persist to body_signals.surface_mining_signals via the historical
    # import path, same as bio/geo/human.
    repo = _repo(tmp_path)
    imp = _importer(tmp_path, repo)

    imp._process_event({
        "event": "FSSBodySignals", "BodyName": "HR 8769 A 1",
        "SystemAddress": 12345, "BodyID": 5,
        "Signals": [
            {"Type": "$PlanetaryMiningLocation_Name;", "Type_Localised": "Planetary Mining Location", "Count": 6},
            {"Type": "$SAA_SignalType_Geological;", "Type_Localised": "Geological", "Count": 3},
        ],
    })

    rows = repo.get_body_signals(12345)
    assert len(rows) == 1
    assert rows[0]["body_name"] == "HR 8769 A 1"
    assert rows[0]["surface_mining_signals"] == 6
    assert rows[0]["geo_signals"] == 3


def test_historical_fsdjump_backfills_squadron_faction(tmp_path):
    # Without this, a fresh DB never learns the player's squadron-aligned
    # faction until a live Docked/FSDJump/Location happens during the
    # current session -- even with years of already-imported journals.
    repo = _repo(tmp_path)
    imp = _importer(tmp_path, repo)

    imp._process_event({
        "event": "FSDJump", "SystemAddress": 12345, "StarSystem": "Test System",
        "timestamp": "2024-03-01T10:00:00Z",
        "SystemFaction": {"Name": "Some Faction"},
        "Factions": [
            {"Name": "Some Faction", "SquadronFaction": True, "Influence": 0.4},
            {"Name": "Other Faction", "Influence": 0.6},
        ],
    })

    overview = repo.get_player_faction_overview()
    assert overview is not None
    assert overview["faction_name"] == "Some Faction"
    assert len(overview["systems"]) == 1
    assert overview["systems"][0]["system_address"] == 12345
