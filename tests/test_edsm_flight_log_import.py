"""Tests for repo.save_system_from_flight_log() (the EDSM personal flight
log backfill, tools/import_edsm_flight_log.py) and the tool's own log-entry
grouping logic."""
import sys
from pathlib import Path

from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
from import_edsm_flight_log import group_by_system  # noqa: E402


def _repo(tmp_path) -> Repository:
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return Repository(db)


def test_inserts_a_system_not_previously_known(tmp_path):
    repo = _repo(tmp_path)
    repo.save_system_from_flight_log(
        system_address=1, system_name="Eranin",
        first_visit="2019-01-01T00:00:00Z", last_visit="2019-06-01T00:00:00Z",
        visit_count=3, first_discovery=1,
    )
    row = repo.get_system(1)
    assert row["system_name"] == "Eranin"
    assert row["first_visit"] == "2019-01-01T00:00:00Z"
    assert row["last_visit"] == "2019-06-01T00:00:00Z"
    assert row["visit_count"] == 3
    assert row["first_discovery"] == 1


def test_never_overwrites_a_system_journal_already_knows(tmp_path):
    repo = _repo(tmp_path)
    repo.save_system(
        system_address=1, system_name="Sol", body_count=12, fss_complete=1,
        first_visit="2026-01-01T00:00:00Z", last_visit="2026-08-01T00:00:00Z",
        visit_count=50,
    )
    repo.save_system_from_flight_log(
        system_address=1, system_name="Sol (stale EDSM name)",
        first_visit="2019-01-01T00:00:00Z", last_visit="2019-01-01T00:00:00Z",
        visit_count=1, first_discovery=1,
    )
    row = repo.get_system(1)
    assert row["system_name"] == "Sol"
    assert row["body_count"] == 12
    assert row["visit_count"] == 50
    assert row["first_discovery"] in (0, None)


def test_default_first_discovery_is_zero_for_pre_split_rows(tmp_path):
    """The new column defaults to 0 -- a system saved before this feature
    existed (via the ordinary journal-driven save_system path) must not
    look first-discovered just because the column is new."""
    repo = _repo(tmp_path)
    repo.save_system(
        system_address=2, system_name="Deciat", body_count=5, fss_complete=1,
        first_visit="2026-01-01T00:00:00Z", last_visit="2026-01-01T00:00:00Z",
        visit_count=1,
    )
    row = repo.get_system(2)
    assert row["first_discovery"] == 0


def test_group_by_system_tracks_visit_span_and_count():
    logs = [
        {"system": "Eranin", "systemId64": 1, "date": "2019-03-01 10:00:00", "firstDiscover": False},
        {"system": "Eranin", "systemId64": 1, "date": "2019-01-01 10:00:00", "firstDiscover": True},
        {"system": "Eranin", "systemId64": 1, "date": "2019-02-01 10:00:00", "firstDiscover": False},
    ]
    result = group_by_system(logs)
    assert result[1]["system_name"] == "Eranin"
    assert result[1]["first_visit"] == "2019-01-01 10:00:00"
    assert result[1]["last_visit"] == "2019-03-01 10:00:00"
    assert result[1]["visit_count"] == 3
    assert result[1]["first_discovery"] == 1


def test_group_by_system_skips_entries_with_no_resolvable_address():
    logs = [
        {"system": "Duplicate Name System", "date": "2019-01-01 10:00:00", "firstDiscover": False},  # no systemId64
        {"system": "Eranin", "systemId64": 1, "date": "2019-01-01 10:00:00", "firstDiscover": False},
    ]
    result = group_by_system(logs)
    assert list(result.keys()) == [1]


def test_group_by_system_separate_systems_stay_separate():
    logs = [
        {"system": "Eranin", "systemId64": 1, "date": "2019-01-01 10:00:00", "firstDiscover": False},
        {"system": "Sol", "systemId64": 2, "date": "2019-01-02 10:00:00", "firstDiscover": True},
    ]
    result = group_by_system(logs)
    assert result[1]["visit_count"] == 1
    assert result[2]["visit_count"] == 1
    assert result[1]["first_discovery"] == 0
    assert result[2]["first_discovery"] == 1
