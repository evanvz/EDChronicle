"""Tests for repo.save_system_from_flight_log() (the EDSM personal flight
log backfill, tools/import_edsm_flight_log.py) and the tool's own log-entry
grouping/date-windowing logic."""
import sys
from pathlib import Path
from unittest.mock import Mock, patch

from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL

sys.path.insert(0, str(Path(__file__).parent.parent / "tools"))
from import_edsm_flight_log import fetch_flight_log, group_by_system, open_staging_db, save_staged_systems  # noqa: E402
from import_edsm_staging_to_db import read_staged_systems  # noqa: E402


def _fake_response(logs):
    resp = Mock()
    resp.raise_for_status = Mock()
    resp.json.return_value = {"msgnum": 100, "msg": "OK", "logs": logs}
    return resp


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


def test_fetch_flight_log_walks_in_7_day_windows_and_accumulates():
    """EDSM's get-logs silently returns nothing for a wide date span
    (confirmed live) -- this must issue one request per 7-day window,
    not one request for the whole range."""
    responses = [_fake_response([{"system": "A"}]), _fake_response([{"system": "B"}]), _fake_response([{"system": "C"}])]
    with patch("import_edsm_flight_log.requests.get", side_effect=responses) as mock_get, \
         patch("import_edsm_flight_log.time.sleep") as mock_sleep:
        logs = fetch_flight_log("CMDR", "key", "2019-01-01", "2019-01-22")  # 21 days = 3 windows

    assert mock_get.call_count == 3
    assert logs == [{"system": "A"}, {"system": "B"}, {"system": "C"}]
    # First window starts exactly at `since`
    first_call_params = mock_get.call_args_list[0].kwargs["params"]
    assert first_call_params["startDateTime"] == "2019-01-01 00:00:00"
    assert first_call_params["endDateTime"] == "2019-01-08 00:00:00"
    # Last window is clipped to `until`, not overshooting into an 8th day
    last_call_params = mock_get.call_args_list[2].kwargs["params"]
    assert last_call_params["endDateTime"] == "2019-01-22 00:00:00"
    # Sleeps between windows (2 sleeps for 3 windows), never after the last
    assert mock_sleep.call_count == 2


def test_fetch_flight_log_single_partial_window_for_short_range():
    with patch("import_edsm_flight_log.requests.get", return_value=_fake_response([])) as mock_get, \
         patch("import_edsm_flight_log.time.sleep") as mock_sleep:
        fetch_flight_log("CMDR", "key", "2019-01-01", "2019-01-03")  # 2 days, under one window

    assert mock_get.call_count == 1
    mock_sleep.assert_not_called()


def test_fetch_flight_log_skips_a_window_that_keeps_failing_and_continues():
    """A single bad week must not abort an hour-long run."""
    import requests as requests_module

    responses = [requests_module.exceptions.ConnectionError("boom")] * 4  # 3 retries + initial for window 1
    responses += [_fake_response([{"system": "B"}])]  # window 2 succeeds
    with patch("import_edsm_flight_log.requests.get", side_effect=responses), \
         patch("import_edsm_flight_log.time.sleep"):
        logs = fetch_flight_log("CMDR", "key", "2019-01-01", "2019-01-15")  # 14 days = 2 windows

    assert logs == [{"system": "B"}]


def test_staging_db_roundtrip(tmp_path):
    """The staging DB is a real sqlite3 file, deliberately separate from
    edhelper.db -- writing to it must never require or touch the real DB."""
    staging_path = tmp_path / "staging.db"
    conn = open_staging_db(staging_path)
    save_staged_systems(conn, {
        1: {"system_name": "Eranin", "first_visit": "2019-01-01 10:00:00", "last_visit": "2019-03-01 10:00:00", "visit_count": 3, "first_discovery": 1},
        2: {"system_name": "Sol", "first_visit": "2019-01-02 10:00:00", "last_visit": "2019-01-02 10:00:00", "visit_count": 1, "first_discovery": 0},
    })
    conn.close()

    rows = {r["system_address"]: r for r in read_staged_systems(staging_path)}
    assert rows[1]["system_name"] == "Eranin"
    assert rows[1]["visit_count"] == 3
    assert rows[1]["first_discovery"] == 1
    assert rows[2]["system_name"] == "Sol"


def test_staging_db_merges_repeated_runs_for_the_same_system(tmp_path):
    """Re-running the fetch for an overlapping/retried date range must
    merge into the existing staged row, not duplicate or clobber it."""
    staging_path = tmp_path / "staging.db"
    conn = open_staging_db(staging_path)
    save_staged_systems(conn, {
        1: {"system_name": "Eranin", "first_visit": "2019-02-01 10:00:00", "last_visit": "2019-02-01 10:00:00", "visit_count": 1, "first_discovery": 0},
    })
    save_staged_systems(conn, {
        1: {"system_name": "Eranin", "first_visit": "2019-01-01 10:00:00", "last_visit": "2019-03-01 10:00:00", "visit_count": 2, "first_discovery": 1},
    })
    conn.close()

    rows = read_staged_systems(staging_path)
    assert len(rows) == 1
    assert rows[0]["first_visit"] == "2019-01-01 10:00:00"  # earliest of the two runs
    assert rows[0]["last_visit"] == "2019-03-01 10:00:00"   # latest of the two runs
    assert rows[0]["visit_count"] == 3                       # summed
    assert rows[0]["first_discovery"] == 1                   # OR'd in
