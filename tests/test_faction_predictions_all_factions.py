"""Tests for Repository._predict_faction_in_system() and
get_all_faction_predictions_for_system() -- real SQLite (temp file), no
mocks, matching this repo's established pattern (see
tests/test_active_war_opponent.py)."""
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


def _faction(name, influence, faction_state=None, active_states=None):
    f = {"Name": name, "Influence": influence, "Government": "Democracy", "Allegiance": "Federation"}
    if faction_state is not None:
        f["FactionState"] = faction_state
    if active_states is not None:
        f["ActiveStates"] = active_states
    return f


def _save(repo, system_address, faction, snapshot_date="2026-08-13", is_controlling=True):
    repo.save_faction_snapshot(system_address, faction, snapshot_date, is_controlling, snapshot_date, "edsm")


# --- get_faction_predictions() must still work identically after the extraction ---

def test_get_faction_predictions_unchanged_after_refactor(repo):
    _save(repo, 1, _faction("Our Faction", 0.6, faction_state="War"))
    _save(repo, 1, _faction("Rival Faction", 0.2, faction_state="War"))
    predictions = repo.get_faction_predictions("Our Faction")
    assert len(predictions) == 1
    assert predictions[0]["system_address"] == 1
    assert predictions[0]["influence"] == 0.6
    assert predictions[0]["active_war"] == {"faction_name": "Rival Faction", "influence": 0.2}


# --- _predict_faction_in_system() ---

def test_predict_faction_in_system_matches_single_faction_shape(repo):
    _save(repo, 1, _faction("Our Faction", 0.6, faction_state="War"))
    _save(repo, 1, _faction("Rival Faction", 0.2, faction_state="War"))
    result = repo._predict_faction_in_system(1, "Our Faction")
    assert result["influence"] == 0.6
    assert result["active_war"] == {"faction_name": "Rival Faction", "influence": 0.2}
    assert "system_address" not in result
    assert "system_name" not in result


def test_predict_faction_in_system_no_history_returns_none_fields(repo):
    result = repo._predict_faction_in_system(999, "Nobody Here")
    assert result["influence"] is None
    assert result["trend"] is None
    assert result["days_in_expansion_range"] is None
    assert result["days_in_retreat_range"] is None
    assert result["conflict_risk"] is None
    assert result["active_war"] is None


# --- get_all_faction_predictions_for_system() ---

def test_all_factions_in_system_returns_every_faction(repo):
    _save(repo, 1, _faction("Faction A", 0.6, faction_state="War"))
    _save(repo, 1, _faction("Faction B", 0.2, faction_state="War"))
    _save(repo, 1, _faction("Faction C", 0.1))
    predictions = repo.get_all_faction_predictions_for_system(1)
    names = {p["faction_name"] for p in predictions}
    assert names == {"Faction A", "Faction B", "Faction C"}


def test_all_factions_sorted_by_influence_descending(repo):
    _save(repo, 1, _faction("Low", 0.1))
    _save(repo, 1, _faction("High", 0.7))
    _save(repo, 1, _faction("Mid", 0.4))
    predictions = repo.get_all_faction_predictions_for_system(1)
    assert [p["faction_name"] for p in predictions] == ["High", "Mid", "Low"]


def test_all_factions_none_influence_sorted_last(repo):
    # Faction only ever seen with influence=None (e.g. malformed snapshot)
    # must not crash the sort and must land after every known-influence entry.
    _save(repo, 1, _faction("Known", 0.5))
    _save(repo, 2, _faction("Unrelated System Faction", 0.3))  # different system, must not appear
    repo.db.execute(
        """
        INSERT INTO faction_snapshots (system_address, faction_name, snapshot_date, influence, is_controlling)
        VALUES (1, 'Unknown Influence', '2026-08-13', NULL, 0)
        """
    )
    predictions = repo.get_all_faction_predictions_for_system(1)
    names = [p["faction_name"] for p in predictions]
    assert names == ["Known", "Unknown Influence"]


def test_all_factions_reflects_per_faction_forecast_independently(repo):
    _save(repo, 1, _faction("Expanding Faction", 0.75))
    _save(repo, 1, _faction("Retreating Faction", 0.02))
    predictions = repo.get_all_faction_predictions_for_system(1)
    by_name = {p["faction_name"]: p for p in predictions}
    assert by_name["Expanding Faction"]["days_in_expansion_range"] == 1
    assert by_name["Retreating Faction"]["days_in_retreat_range"] == 1
