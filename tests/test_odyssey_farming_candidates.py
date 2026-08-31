"""Tests for Repository.get_odyssey_farming_candidates() -- real SQLite
(temp file), not mocks, since the query does the classification logic
that matters here."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL


@pytest.fixture
def repo(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return Repository(db)


_FRESH_TIMESTAMP = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _save(repo, system_address, system_name, faction_name, government=None,
          faction_state=None, active_states=None, is_controlling=True,
          data_timestamp=None):
    data_timestamp = data_timestamp or _FRESH_TIMESTAMP
    repo.save_system_name_if_missing(system_address, system_name)
    faction = {"Name": faction_name, "Influence": 0.5}
    if government is not None:
        faction["Government"] = government
    if faction_state is not None:
        faction["FactionState"] = faction_state
    if active_states is not None:
        faction["ActiveStates"] = active_states
    repo.save_faction_snapshot(
        system_address, faction, "2026-08-12", is_controlling,
        data_timestamp, "journal",
    )


def test_anarchy_government_is_a_candidate(repo):
    _save(repo, 1, "Anarchy System", "Faction A", government="Anarchy")
    result = repo.get_odyssey_farming_candidates()
    assert len(result) == 1
    assert result[0]["system_name"] == "Anarchy System"
    assert "Anarchy" in result[0]["matched_signals"]


def test_democracy_government_is_not_a_candidate(repo):
    _save(repo, 1, "Normal System", "Faction A", government="Democracy")
    result = repo.get_odyssey_farming_candidates()
    assert result == []


def test_war_faction_state_is_a_candidate(repo):
    _save(repo, 2, "War System", "Faction B", government="Democracy",
          faction_state="War")
    result = repo.get_odyssey_farming_candidates()
    assert len(result) == 1
    assert "War" in result[0]["matched_signals"]


def test_pirate_attack_in_active_states_is_a_candidate(repo):
    _save(repo, 3, "Pirate System", "Faction C", government="Democracy",
          active_states=[{"State": "PirateAttack", "Trend": 0}])
    result = repo.get_odyssey_farming_candidates()
    assert len(result) == 1
    assert "Pirate Attack" in result[0]["matched_signals"]


def test_civil_unrest_and_infrastructure_failure_detected(repo):
    _save(repo, 4, "Unrest System", "Faction D", government="Democracy",
          active_states=[{"State": "CivilUnrest", "Trend": 0}])
    _save(repo, 5, "Infra System", "Faction E", government="Democracy",
          active_states=[{"State": "InfrastructureFailure", "Trend": 0}])
    result = repo.get_odyssey_farming_candidates()
    by_name = {r["system_name"]: r["matched_signals"] for r in result}
    assert "Civil Unrest" in by_name["Unrest System"]
    assert "Infrastructure Failure" in by_name["Infra System"]


def test_multiple_signals_all_reported(repo):
    _save(repo, 6, "Chaos System", "Faction F", government="Anarchy",
          faction_state="War")
    result = repo.get_odyssey_farming_candidates()
    assert set(result[0]["matched_signals"]) == {"Anarchy", "War"}


def test_non_controlling_faction_is_ignored(repo):
    _save(repo, 7, "Uncontrolled System", "Faction G", government="Anarchy",
          is_controlling=False)
    result = repo.get_odyssey_farming_candidates()
    assert result == []


def test_only_latest_snapshot_date_used(repo):
    # Older row (different snapshot_date) says Anarchy; only the newest
    # row's classification should count. Use save_faction_snapshot twice
    # with different snapshot_date values via direct calls.
    repo.save_system_name_if_missing(8, "Changed System")
    repo.save_faction_snapshot(
        8, {"Name": "Faction H", "Government": "Anarchy"}, "2026-08-10",
        True, "2026-08-10T00:00:00Z", "journal",
    )
    repo.save_faction_snapshot(
        8, {"Name": "Faction H", "Government": "Democracy"}, "2026-08-12",
        True, "2026-08-12T00:00:00Z", "journal",
    )
    result = repo.get_odyssey_farming_candidates()
    assert result == []


def test_sorted_freshest_data_timestamp_first(repo):
    now = datetime.now(timezone.utc)
    older = (now - timedelta(days=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
    newer = (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    _save(repo, 9, "Older", "Faction I", government="Anarchy",
          data_timestamp=older)
    _save(repo, 10, "Newer", "Faction J", government="Anarchy",
          data_timestamp=newer)
    result = repo.get_odyssey_farming_candidates()
    assert [r["system_name"] for r in result] == ["Newer", "Older"]


def test_limit_caps_results(repo):
    for i in range(25):
        _save(repo, 100 + i, f"System {i}", f"Faction {i}",
              government="Anarchy")
    result = repo.get_odyssey_farming_candidates(limit=20)
    assert len(result) == 20


def test_returns_data_timestamp_field(repo):
    _save(repo, 11, "Timestamped", "Faction K", government="Anarchy",
          data_timestamp="2026-08-11T10:00:00Z")
    result = repo.get_odyssey_farming_candidates()
    assert result[0]["data_timestamp"] == "2026-08-11T10:00:00Z"


def test_bgs_state_signal_ranks_above_anarchy_only(repo):
    now = datetime.now(timezone.utc)
    _save(repo, 20, "Anarchy Only", "Faction M", government="Anarchy",
          data_timestamp=(now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    _save(repo, 21, "Unrest State", "Faction N", government="Democracy",
          active_states=[{"State": "CivilUnrest", "Trend": 0}],
          data_timestamp=(now - timedelta(days=20)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    result = repo.get_odyssey_farming_candidates()
    assert [r["system_name"] for r in result] == ["Unrest State", "Anarchy Only"]


def test_candidate_older_than_30_days_is_excluded(repo):
    _save(repo, 12, "Stale System", "Faction O", government="Anarchy",
          data_timestamp="2026-07-01T00:00:00Z")
    result = repo.get_odyssey_farming_candidates()
    assert result == []


def test_null_data_timestamp_candidate_is_excluded(repo):
    # Simulate a pre-data_timestamp-column legacy row, same pattern as
    # test_faction_snapshot_freshness.py's legacy-row fixture.
    repo.save_system_name_if_missing(13, "Legacy System")
    repo.db.conn.execute(
        """INSERT INTO faction_snapshots (system_address, faction_name, snapshot_date, government, is_controlling)
           VALUES (?, ?, ?, ?, ?)""",
        (13, "Faction P", "2026-08-12", "Anarchy", 1),
    )
    repo.db.conn.commit()
    result = repo.get_odyssey_farming_candidates()
    assert result == []
