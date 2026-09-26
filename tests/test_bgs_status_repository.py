"""Tests for system_bgs_status/system_res_sites save + radius search --
real SQLite (temp file), same fixture shape as
test_faction_snapshot_freshness.py."""
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


def _seed_coords(repo, system_name, x, y, z):
    repo.db.execute(
        "INSERT INTO system_coords (system_name, x, y, z) VALUES (?, ?, ?, ?)",
        (system_name, x, y, z),
    )


# --- save_system_bgs_status ---

def test_save_skips_when_nothing_relevant(repo):
    repo.save_system_bgs_status(1, "Sol", conflicts=[], factions=[{"Name": "A", "ActiveStates": []}],
                                 data_timestamp="2026-08-23T00:00:00Z", source="journal")
    row = repo.db.conn.execute("SELECT * FROM system_bgs_status WHERE system_address = 1").fetchone()
    assert row is None


def test_save_stores_war_and_election_conflicts_and_ignores_others(repo):
    conflicts = [
        {"WarType": "election", "Status": "", "Faction1": {"Name": "A", "WonDays": 1}, "Faction2": {"Name": "B", "WonDays": 0}},
        {"WarType": "war", "Status": "active", "Faction1": {"Name": "C", "WonDays": 2}, "Faction2": {"Name": "D", "WonDays": 1}},
        {"WarType": "", "Status": "", "Faction1": {"Name": "E"}, "Faction2": {"Name": "F"}},
    ]
    repo.save_system_bgs_status(1, "Sol", conflicts=conflicts, factions=[],
                                 data_timestamp="2026-08-23T00:00:00Z", source="journal")
    row = repo.db.conn.execute("SELECT * FROM system_bgs_status WHERE system_address = 1").fetchone()
    assert row is not None
    stored = json.loads(row["conflicts"])
    assert [c["war_type"] for c in stored] == ["election", "war"]
    assert stored[1] == {"faction1": "C", "faction2": "D", "war_type": "war", "status": "active",
                         "won_days1": 2, "won_days2": 1, "stake1": None, "stake2": None}


def test_save_stores_conflict_stakes(repo):
    conflicts = [{"WarType": "civilwar", "Status": "active",
                  "Faction1": {"Name": "A", "Stake": "Hahn Hub", "WonDays": 1},
                  "Faction2": {"Name": "B", "Stake": "", "WonDays": 0}}]
    repo.save_system_bgs_status(1, "Sol", conflicts=conflicts, factions=[],
                                 data_timestamp="2026-08-23T00:00:00Z", source="journal")
    row = repo.db.conn.execute("SELECT * FROM system_bgs_status WHERE system_address = 1").fetchone()
    stored = json.loads(row["conflicts"])[0]
    assert stored["stake1"] == "Hahn Hub"
    assert stored["stake2"] == ""


def test_save_stores_multistate_factions_only(repo):
    factions = [
        {"Name": "A", "ActiveStates": [], "PendingStates": [], "RecoveringStates": []},
        {"Name": "B", "FactionState": "War", "ActiveStates": [{"State": "War"}], "PendingStates": [], "RecoveringStates": [{"State": "Outbreak"}]},
    ]
    repo.save_system_bgs_status(1, "Sol", conflicts=[], factions=factions,
                                 data_timestamp="2026-08-23T00:00:00Z", source="journal")
    row = repo.db.conn.execute("SELECT * FROM system_bgs_status WHERE system_address = 1").fetchone()
    stored = json.loads(row["faction_states"])
    assert len(stored) == 1
    assert stored[0]["name"] == "B"


def test_save_excludes_faction_with_only_one_state_total(repo):
    # Single state in a single bucket -- was previously (buggily) included
    # because "any bucket non-empty" is true for nearly every faction; the
    # fix requires >=2 states total across all three buckets.
    factions = [{"Name": "A", "ActiveStates": [{"State": "Boom"}], "PendingStates": [], "RecoveringStates": []}]
    repo.save_system_bgs_status(1, "Sol", conflicts=[], factions=factions,
                                 data_timestamp="2026-08-23T00:00:00Z", source="journal")
    row = repo.db.conn.execute("SELECT * FROM system_bgs_status WHERE system_address = 1").fetchone()
    assert row is None


def test_save_includes_civil_unrest_even_as_only_state(repo):
    # Civil Unrest/Infrastructure Failure indicate reduced/no settlement
    # security -- worth tracking even alone, unlike ordinary single states
    # (see test_save_excludes_faction_with_only_one_state_total above).
    factions = [{"Name": "A", "ActiveStates": [{"State": "CivilUnrest"}], "PendingStates": [], "RecoveringStates": []}]
    repo.save_system_bgs_status(1, "Sol", conflicts=[], factions=factions,
                                 data_timestamp="2026-08-23T00:00:00Z", source="journal")
    row = repo.db.conn.execute("SELECT * FROM system_bgs_status WHERE system_address = 1").fetchone()
    stored = json.loads(row["faction_states"])
    assert len(stored) == 1 and stored[0]["name"] == "A"


def test_save_includes_infrastructure_failure_even_as_only_state(repo):
    factions = [{"Name": "A", "ActiveStates": [{"State": "InfrastructureFailure"}], "PendingStates": [], "RecoveringStates": []}]
    repo.save_system_bgs_status(1, "Sol", conflicts=[], factions=factions,
                                 data_timestamp="2026-08-23T00:00:00Z", source="journal")
    row = repo.db.conn.execute("SELECT * FROM system_bgs_status WHERE system_address = 1").fetchone()
    stored = json.loads(row["faction_states"])
    assert len(stored) == 1 and stored[0]["name"] == "A"


def test_save_includes_faction_with_two_states_in_same_bucket(repo):
    factions = [{"Name": "A", "ActiveStates": [{"State": "War"}, {"State": "Outbreak"}], "PendingStates": [], "RecoveringStates": []}]
    repo.save_system_bgs_status(1, "Sol", conflicts=[], factions=factions,
                                 data_timestamp="2026-08-23T00:00:00Z", source="journal")
    row = repo.db.conn.execute("SELECT * FROM system_bgs_status WHERE system_address = 1").fetchone()
    stored = json.loads(row["faction_states"])
    assert len(stored) == 1 and stored[0]["name"] == "A"


def test_save_includes_faction_with_one_state_in_each_of_two_buckets(repo):
    factions = [{"Name": "A", "ActiveStates": [{"State": "War"}], "PendingStates": [{"State": "Election"}], "RecoveringStates": []}]
    repo.save_system_bgs_status(1, "Sol", conflicts=[], factions=factions,
                                 data_timestamp="2026-08-23T00:00:00Z", source="journal")
    row = repo.db.conn.execute("SELECT * FROM system_bgs_status WHERE system_address = 1").fetchone()
    stored = json.loads(row["faction_states"])
    assert len(stored) == 1 and stored[0]["name"] == "A"


# --- prune_stale_system_bgs_status / prune_stale_system_res_sites ---

def test_prune_stale_system_bgs_status_deletes_old_keeps_fresh(repo):
    repo.save_system_bgs_status(1, "Old", conflicts=[{"WarType": "war", "Faction1": {"Name": "A"}, "Faction2": {"Name": "B"}}],
                                 factions=[], data_timestamp="2000-01-01T00:00:00Z", source="journal")
    repo.save_system_bgs_status(2, "Fresh", conflicts=[{"WarType": "war", "Faction1": {"Name": "C"}, "Faction2": {"Name": "D"}}],
                                 factions=[], data_timestamp="2099-01-01T00:00:00Z", source="journal")
    deleted = repo.prune_stale_system_bgs_status()
    assert deleted == 1
    remaining = repo.db.conn.execute("SELECT system_name FROM system_bgs_status").fetchall()
    assert [r["system_name"] for r in remaining] == ["Fresh"]


def test_prune_stale_system_res_sites_deletes_old_keeps_fresh(repo):
    repo.save_system_res_tiers(1, "Old", tiers=["High"], data_timestamp="2000-01-01T00:00:00Z", source="journal")
    repo.save_system_res_tiers(2, "Fresh", tiers=["Low"], data_timestamp="2099-01-01T00:00:00Z", source="journal")
    deleted = repo.prune_stale_system_res_sites()
    assert deleted == 1
    remaining = repo.db.conn.execute("SELECT system_name FROM system_res_sites").fetchall()
    assert [r["system_name"] for r in remaining] == ["Fresh"]


def test_save_older_data_does_not_overwrite_newer(repo):
    repo.save_system_bgs_status(1, "Sol", conflicts=[{"WarType": "war", "Faction1": {"Name": "A"}, "Faction2": {"Name": "B"}}],
                                 factions=[], data_timestamp="2026-08-23T10:00:00Z", source="eddn")
    repo.save_system_bgs_status(1, "Sol", conflicts=[{"WarType": "civilwar", "Faction1": {"Name": "X"}, "Faction2": {"Name": "Y"}}],
                                 factions=[], data_timestamp="2026-08-22T10:00:00Z", source="journal")
    row = repo.db.conn.execute("SELECT * FROM system_bgs_status WHERE system_address = 1").fetchone()
    stored = json.loads(row["conflicts"])
    assert stored[0]["faction1"] == "A"  # the newer (eddn) write, not overwritten by the older journal write


# --- save_system_res_tiers ---

def test_save_res_tiers_skips_when_empty(repo):
    repo.save_system_res_tiers(1, "Sol", tiers=[], data_timestamp="2026-08-23T00:00:00Z", source="journal")
    row = repo.db.conn.execute("SELECT * FROM system_res_sites WHERE system_address = 1").fetchone()
    assert row is None


def test_save_res_tiers_dedupes_and_sorts(repo):
    repo.save_system_res_tiers(1, "Sol", tiers=["High", "Low", "High", "Nominal"],
                                data_timestamp="2026-08-23T00:00:00Z", source="journal")
    row = repo.db.conn.execute("SELECT * FROM system_res_sites WHERE system_address = 1").fetchone()
    assert json.loads(row["tiers"]) == ["High", "Low", "Nominal"]


# --- search_bgs_status_near / search_res_sites_near ---

def test_search_bgs_status_near_filters_by_radius(repo):
    # search_bgs_status_near applies a 7-day freshness cutoff (see
    # test_search_bgs_status_near_excludes_rows_past_7_day_war_cycle
    # below), so the seeded timestamp must stay relative to "now" --
    # a hardcoded absolute date silently ages out and starts failing
    # once real time catches up to it (confirmed live: this test broke
    # the day the fixed 2026-08-23 timestamp turned 7 days old).
    _seed_coords(repo, "Near", 0.0, 0.0, 0.0)
    _seed_coords(repo, "Far", 500.0, 0.0, 0.0)
    repo.save_system_bgs_status(1, "Near", conflicts=[{"WarType": "war", "Faction1": {"Name": "A"}, "Faction2": {"Name": "B"}}],
                                 factions=[], data_timestamp=_ts_days_ago(1), source="journal")
    repo.save_system_bgs_status(2, "Far", conflicts=[{"WarType": "war", "Faction1": {"Name": "C"}, "Faction2": {"Name": "D"}}],
                                 factions=[], data_timestamp=_ts_days_ago(1), source="journal")
    results = repo.search_bgs_status_near(0.0, 0.0, 0.0, radius_ly=50.0)
    assert [r["system_name"] for r in results] == ["Near"]


def test_search_res_sites_near_returns_tiers(repo):
    _seed_coords(repo, "Near", 0.0, 0.0, 0.0)
    repo.save_system_res_tiers(1, "Near", tiers=["Hazardous"], data_timestamp=_ts_days_ago(1), source="journal")
    results = repo.search_res_sites_near(0.0, 0.0, 0.0, radius_ly=50.0)
    assert results[0]["tiers"] == ["Hazardous"]
    assert results[0]["distance_ly"] == 0.0


def _ts_days_ago(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_search_bgs_status_near_excludes_rows_past_7_day_war_cycle(repo):
    # War/CivilWar conflicts resolve within a fixed 7-day cycle -- a
    # War/CivilWar row older than that is guaranteed already over, unlike
    # market_prices' looser 21-day cutoff which this table deliberately
    # does not reuse.
    _seed_coords(repo, "Fresh", 0.0, 0.0, 0.0)
    _seed_coords(repo, "Stale", 1.0, 0.0, 0.0)
    repo.save_system_bgs_status(1, "Fresh", conflicts=[{"WarType": "war", "Faction1": {"Name": "A"}, "Faction2": {"Name": "B"}}],
                                 factions=[], data_timestamp=_ts_days_ago(2), source="journal")
    repo.save_system_bgs_status(2, "Stale", conflicts=[{"WarType": "war", "Faction1": {"Name": "C"}, "Faction2": {"Name": "D"}}],
                                 factions=[], data_timestamp=_ts_days_ago(10), source="journal")
    results = repo.search_bgs_status_near(0.0, 0.0, 0.0, radius_ly=50.0)
    assert [r["system_name"] for r in results] == ["Fresh"]


def test_search_res_sites_near_keeps_rows_past_the_7_day_war_cutoff(repo):
    # RES tier presence isn't tied to the BGS war cycle -- confirms the two
    # search methods use their own independent cutoffs, not one shared
    # constant, so a future refactor can't silently unify them.
    _seed_coords(repo, "Near", 0.0, 0.0, 0.0)
    repo.save_system_res_tiers(1, "Near", tiers=["Hazardous"], data_timestamp=_ts_days_ago(10), source="journal")
    results = repo.search_res_sites_near(0.0, 0.0, 0.0, radius_ly=50.0)
    assert [r["system_name"] for r in results] == ["Near"]


# --- get_bgs_status_for_system ---

def test_get_bgs_status_for_system_returns_none_when_untracked(repo):
    assert repo.get_bgs_status_for_system(999) is None


def test_get_bgs_status_for_system_returns_saved_data_regardless_of_age(repo):
    # Unlike search_bgs_status_near, this is a targeted single-system
    # lookup with no freshness cutoff -- a stale-but-known row should
    # still come back, not be silently hidden.
    ts = _ts_days_ago(30)
    repo.save_system_bgs_status(1, "Sol", conflicts=[{"WarType": "war", "Faction1": {"Name": "A"}, "Faction2": {"Name": "B"}}],
                                 factions=[], data_timestamp=ts, source="journal")
    result = repo.get_bgs_status_for_system(1)
    assert result is not None
    assert result["conflicts"][0]["faction1"] == "A"
    assert result["data_timestamp"] == ts


# --- ended conflicts are cleared by a newer own-journal reading ---

_WAR = [{"WarType": "war", "Status": "active", "Faction1": {"Name": "A", "WonDays": 1}, "Faction2": {"Name": "B", "WonDays": 0}}]


def _stored_conflicts(repo):
    row = repo.db.conn.execute("SELECT conflicts FROM system_bgs_status WHERE system_address = 1").fetchone()
    return json.loads(row["conflicts"])


def test_newer_journal_reading_with_nothing_relevant_clears_ended_conflict(repo):
    repo.save_system_bgs_status(1, "Sol", _WAR, [], "2026-09-20T00:00:00Z", "journal")
    factions = [{"Name": "A", "ActiveStates": [], "PendingStates": [], "RecoveringStates": []}]
    repo.save_system_bgs_status(1, "Sol", [], factions, "2026-09-21T00:00:00Z", "journal")
    assert _stored_conflicts(repo) == []


def test_older_journal_reading_does_not_clear_newer_conflict(repo):
    repo.save_system_bgs_status(1, "Sol", _WAR, [], "2026-09-21T00:00:00Z", "journal")
    repo.save_system_bgs_status(1, "Sol", [], [], "2026-09-20T00:00:00Z", "journal")
    assert len(_stored_conflicts(repo)) == 1


def test_eddn_and_edsm_readings_never_clear(repo):
    repo.save_system_bgs_status(1, "Sol", _WAR, [], "2026-09-20T00:00:00Z", "journal")
    repo.save_system_bgs_status(1, "Sol", [], [], "2026-09-21T00:00:00Z", "eddn")
    repo.save_system_bgs_status(1, "Sol", [], [], "2026-09-22T00:00:00Z", "edsm")
    assert len(_stored_conflicts(repo)) == 1


def test_newer_journal_reading_with_empty_factions_list_does_not_clear(repo):
    repo.save_system_bgs_status(1, "Sol", _WAR, [], "2026-09-20T00:00:00Z", "journal")
    repo.save_system_bgs_status(1, "Sol", [], [], "2026-09-21T00:00:00Z", "journal")
    assert len(_stored_conflicts(repo)) == 1


def test_edsm_reading_does_not_overwrite_existing_conflicts(repo):
    election = [{"WarType": "election", "Status": "", "Faction1": {"Name": "A", "WonDays": 2}, "Faction2": {"Name": "B", "WonDays": 0}}]
    repo.save_system_bgs_status(1, "Sol", election, [], "2026-09-20T00:00:00Z", "journal")
    war = [{"WarType": "war", "Status": "active", "Faction1": {"Name": "C", "WonDays": 1}, "Faction2": {"Name": "D", "WonDays": 1}}]
    repo.save_system_bgs_status(1, "Sol", war, [], "2026-09-25T00:00:00Z", "edsm")
    stored = _stored_conflicts(repo)
    assert stored[0]["war_type"] == "election"
    assert stored[0]["won_days1"] == 2 and stored[0]["won_days2"] == 0


def test_edsm_reading_still_inserts_when_no_existing_row(repo):
    war = [{"WarType": "war", "Status": "active", "Faction1": {"Name": "C", "WonDays": 1}, "Faction2": {"Name": "D", "WonDays": 1}}]
    repo.save_system_bgs_status(1, "Sol", war, [], "2026-09-25T00:00:00Z", "edsm")
    stored = _stored_conflicts(repo)
    assert stored[0]["war_type"] == "war"
