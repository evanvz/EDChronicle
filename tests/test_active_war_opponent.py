"""Tests for Repository.get_faction_predictions()'s active_war field and
player_faction_panel._format_forecast()'s active-war rendering -- real
SQLite (temp file), not mocks, matching this repo's established pattern
(see tests/test_faction_snapshot_freshness.py)."""
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


# --- get_faction_predictions() -- active_war ---

def test_war_with_named_opponent(repo):
    _save(repo, 1, _faction("Our Faction", 0.6, faction_state="War"))
    _save(repo, 1, _faction("Rival Faction", 0.2, faction_state="War"))
    predictions = repo.get_faction_predictions("Our Faction")
    assert predictions[0]["active_war"] == {"faction_name": "Rival Faction", "influence": 0.2}


def test_war_detected_via_civilwar_state(repo):
    _save(repo, 1, _faction("Our Faction", 0.6, faction_state="CivilWar"))
    _save(repo, 1, _faction("Rival Faction", 0.2, faction_state="CivilWar"))
    predictions = repo.get_faction_predictions("Our Faction")
    assert predictions[0]["active_war"] == {"faction_name": "Rival Faction", "influence": 0.2}


def test_war_detected_via_active_states_not_faction_state(repo):
    _save(repo, 1, _faction("Our Faction", 0.6, active_states=[{"State": "War"}]))
    _save(repo, 1, _faction("Rival Faction", 0.2, active_states=[{"State": "War"}]))
    predictions = repo.get_faction_predictions("Our Faction")
    assert predictions[0]["active_war"] == {"faction_name": "Rival Faction", "influence": 0.2}


def test_war_no_matching_opponent_is_unknown(repo):
    _save(repo, 1, _faction("Our Faction", 0.6, faction_state="War"))
    _save(repo, 1, _faction("Peaceful Faction", 0.2, faction_state="None"))
    predictions = repo.get_faction_predictions("Our Faction")
    assert predictions[0]["active_war"] == {"faction_name": None, "influence": None}


def test_not_at_war_is_none(repo):
    _save(repo, 1, _faction("Our Faction", 0.6, faction_state="Boom"))
    _save(repo, 1, _faction("Rival Faction", 0.2, faction_state="War"))
    predictions = repo.get_faction_predictions("Our Faction")
    assert predictions[0]["active_war"] is None


def test_highest_influence_rival_picked_when_multiple_at_war(repo):
    _save(repo, 1, _faction("Our Faction", 0.6, faction_state="War"))
    _save(repo, 1, _faction("Small Rival", 0.1, faction_state="War"))
    _save(repo, 1, _faction("Big Rival", 0.3, faction_state="War"))
    predictions = repo.get_faction_predictions("Our Faction")
    assert predictions[0]["active_war"] == {"faction_name": "Big Rival", "influence": 0.3}


def test_low_influence_opponent_found_despite_large_gap(repo):
    # The real case that motivated this feature: 60% vs 20%, nowhere near
    # the existing conflict_risk predictor's 5-point proximity threshold.
    _save(repo, 1, _faction("Our Faction", 0.6, faction_state="War"))
    _save(repo, 1, _faction("Distant Rival", 0.2, faction_state="War"))
    predictions = repo.get_faction_predictions("Our Faction")
    assert predictions[0]["active_war"]["faction_name"] == "Distant Rival"
