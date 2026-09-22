"""JournalImporter._handle_colonisation_construction_depot -- historical-
replay counterpart to MainWindow._save_colonisation_depot. Without this,
a construction site only ever got tracked if the live watcher happened to
be running for a fresh Docked+ColonisationConstructionDepot pair; one
that predated an app restart (confirmed live 2026-09-22: docked before
relaunching EDChronicle) was invisible forever, leaving a manually-added
placeholder stuck on "Not yet visited". Real SQLite (temp file) and real
Repository, matching test_journal_importer_persistence.py's convention."""
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL

from edc.core.journal_importer import JournalImporter


def _importer(tmp_path, repo):
    return JournalImporter(tmp_path, repo)


def _repo(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return Repository(db)


def _docked_event(market_id=555, system_name="HIP 105879", station_name="Orbital Construction Site: Test"):
    return {
        "event": "Docked", "MarketID": market_id, "StationName": station_name,
        "StarSystem": system_name, "SystemAddress": 12345, "StationType": "SpaceConstructionDepot",
        "timestamp": "2026-09-22T08:00:00Z",
    }


def _depot_event(market_id=555, progress=0.2, complete=False, resources=None):
    return {
        "event": "ColonisationConstructionDepot", "MarketID": market_id,
        "ConstructionProgress": progress, "ConstructionComplete": complete,
        "ResourcesRequired": resources or [], "timestamp": "2026-09-22T08:00:05Z",
    }


def test_depot_after_docked_backfills_a_real_row(tmp_path):
    repo = _repo(tmp_path)
    imp = _importer(tmp_path, repo)

    imp._process_event(_docked_event())
    imp._process_event(_depot_event())

    depots = repo.get_colonisation_depots()
    assert len(depots) == 1
    assert depots[0]["system_name"] == "HIP 105879"
    assert depots[0]["station_name"] == "Orbital Construction Site: Test"
    assert depots[0]["market_id"] == 555


def test_depot_without_a_prior_docked_event_is_skipped(tmp_path):
    """The event carries no system/station name of its own -- if the
    matching Docked event isn't in the scanned journal range, this
    can't be resolved and must not raise or insert a nameless row."""
    repo = _repo(tmp_path)
    imp = _importer(tmp_path, repo)

    imp._process_event(_depot_event())

    assert repo.get_colonisation_depots() == []


def test_depot_backfills_manually_added_placeholder_by_exact_name(tmp_path):
    """Mirrors save_colonisation_depot_visit's own fallback match -- a
    manually-added row (market_id IS NULL) with the EXACT real station
    name gets filled in rather than duplicated."""
    repo = _repo(tmp_path)
    repo.add_colonisation_depot_manual("HIP 105879", "Orbital Construction Site: Test")
    imp = _importer(tmp_path, repo)

    imp._process_event(_docked_event())
    imp._process_event(_depot_event(progress=0.35))

    depots = repo.get_colonisation_depots()
    assert len(depots) == 1
    assert depots[0]["market_id"] == 555
    assert depots[0]["progress"] == 0.35


def test_depot_resources_are_saved(tmp_path):
    repo = _repo(tmp_path)
    imp = _importer(tmp_path, repo)

    imp._process_event(_docked_event())
    imp._process_event(_depot_event(resources=[
        {"Name": "$aluminium_name;", "Name_Localised": "Aluminium", "RequiredAmount": 100, "ProvidedAmount": 10},
    ]))

    depots = repo.get_colonisation_depots()
    assert depots[0]["resources"] == [
        {"name": "Aluminium", "required": 100, "provided": 10, "payment": None},
    ]


def test_non_integer_market_id_is_ignored(tmp_path):
    repo = _repo(tmp_path)
    imp = _importer(tmp_path, repo)

    imp._process_event({"event": "ColonisationConstructionDepot"})

    assert repo.get_colonisation_depots() == []
