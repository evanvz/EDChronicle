"""Repository.save_body() previously always overwrote planet_class/
landable/distance_ls/estimated_value even when the caller didn't have
them -- same clobber footgun already fixed this session for
save_spansh_body()/save_body_signal_counts(). Real bug, confirmed live:
a body scanned in an old journal file (since rotated off disk) had its
real planet_class/landable in the DB, but a later SAASignalsFound event
for the same body -- processed via journal_importer.py's per-import-run
bodies_by_name cache, which starts empty every run -- created a blank
CachedBody(planet_class=None, landable=None) and nulled out the real
values on the next save_body() call. Now COALESCEd like the other
optional columns."""
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL

from edc.core.journal_importer import JournalImporter


def _importer(tmp_path, repo):
    imp = JournalImporter(tmp_path, repo)
    imp.current_system_address = 3205949786483
    return imp


def _repo(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return Repository(db)


def test_saasignalsfound_does_not_null_out_landable_from_an_older_scan(tmp_path):
    repo = _repo(tmp_path)
    imp = _importer(tmp_path, repo)

    # A real Scan event, as it would have appeared in a journal file
    # that's since been rotated off disk.
    imp._process_event({
        "event": "Scan", "ScanType": "Detailed", "BodyName": "Ekono A 1 a",
        "BodyID": 4, "SystemAddress": 3205949786483,
        "PlanetClass": "Rocky body", "Landable": True, "DistanceFromArrivalLS": 300.0,
        "WasDiscovered": True, "WasMapped": False,
    })

    # Simulate a fresh import run (or a later session) where that Scan
    # event's journal file no longer exists on disk -- bodies_by_name
    # starts empty, so this SAASignalsFound is the first this body's
    # been seen this run.
    imp.bodies_by_name.clear()
    imp._process_event({
        "event": "SAASignalsFound", "BodyName": "Ekono A 1 a", "BodyID": 4,
        "SystemAddress": 3205949786483,
        "Signals": [{"Type": "$SAA_SignalType_Human;", "Count": 10}],
        "Genuses": [],
    })

    rows = repo.get_bodies(3205949786483)
    row = next(r for r in rows if r["body_name"] == "Ekono A 1 a")
    assert row["planet_class"] == "Rocky body"
    assert row["landable"] == 1
    assert row["distance_ls"] == 300.0


def test_saasignalsfound_still_marks_dss_mapped(tmp_path):
    # The fix must not weaken the real, always-true dss_mapped=1 signal
    # SAASignalsFound provides -- only planet_class/landable/distance_ls/
    # estimated_value are protected from clobber, not dss_mapped.
    repo = _repo(tmp_path)
    imp = _importer(tmp_path, repo)

    imp._process_event({
        "event": "Scan", "ScanType": "Detailed", "BodyName": "Test Body",
        "BodyID": 7, "SystemAddress": 3205949786483,
        "PlanetClass": "Icy body", "Landable": False, "DistanceFromArrivalLS": 50.0,
        "WasDiscovered": True, "WasMapped": False,
    })
    imp._process_event({
        "event": "SAASignalsFound", "BodyName": "Test Body", "BodyID": 7,
        "SystemAddress": 3205949786483,
        "Signals": [{"Type": "$SAA_SignalType_Geological;", "Count": 2}],
        "Genuses": [],
    })

    rows = repo.get_bodies(3205949786483)
    row = next(r for r in rows if r["body_name"] == "Test Body")
    assert row["dss_mapped"] == 1
