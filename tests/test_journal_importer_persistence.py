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
