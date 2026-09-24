"""Repository.record_faction_mission_completion / get_faction_mission_
completion_counts -- backs the Faction Expansion tracker's "missions
completed today / last 7 days" display, plus a weighted score from
Frontier's own qualitative "+" to "+++++" influence-impact rating
(no exact point value is ever exposed by the game). active_missions
discards a mission's faction/system the instant it completes (see
mission_events.py), so this is the only durable record. Real SQLite
(temp file), matching this repo's convention."""
from datetime import datetime, timedelta, timezone

from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL


def _repo(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return Repository(db)


def _iso(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


def _counts(today=0, last_7_days=0, weighted_today=0, weighted_last_7_days=0):
    return {
        "today": today, "last_7_days": last_7_days,
        "weighted_today": weighted_today, "weighted_last_7_days": weighted_last_7_days,
    }


def test_counts_zero_with_no_completions(tmp_path):
    repo = _repo(tmp_path)
    assert repo.get_faction_mission_completion_counts(123, "Test Faction") == _counts()


def test_a_completion_today_counts_in_both_buckets(tmp_path):
    repo = _repo(tmp_path)
    repo.record_faction_mission_completion(123, "Test Faction", _iso(0))
    counts = repo.get_faction_mission_completion_counts(123, "Test Faction")
    assert counts == _counts(today=1, last_7_days=1)


def test_a_completion_three_days_ago_counts_only_in_weekly(tmp_path):
    repo = _repo(tmp_path)
    repo.record_faction_mission_completion(123, "Test Faction", _iso(3))
    counts = repo.get_faction_mission_completion_counts(123, "Test Faction")
    assert counts == _counts(today=0, last_7_days=1)


def test_a_completion_ten_days_ago_counts_in_neither(tmp_path):
    repo = _repo(tmp_path)
    repo.record_faction_mission_completion(123, "Test Faction", _iso(10))
    counts = repo.get_faction_mission_completion_counts(123, "Test Faction")
    assert counts == _counts()


def test_counts_are_scoped_to_system_and_faction(tmp_path):
    repo = _repo(tmp_path)
    repo.record_faction_mission_completion(123, "Test Faction", _iso(0))
    repo.record_faction_mission_completion(456, "Test Faction", _iso(0))  # different system
    repo.record_faction_mission_completion(123, "Other Faction", _iso(0))  # different faction
    counts = repo.get_faction_mission_completion_counts(123, "Test Faction")
    assert counts == _counts(today=1, last_7_days=1)


def test_multiple_completions_accumulate(tmp_path):
    repo = _repo(tmp_path)
    for _ in range(3):
        repo.record_faction_mission_completion(123, "Test Faction", _iso(0))
    repo.record_faction_mission_completion(123, "Test Faction", _iso(2))
    counts = repo.get_faction_mission_completion_counts(123, "Test Faction")
    assert counts == _counts(today=3, last_7_days=4)


# --- influence_tier weighting ---

def test_tier_length_is_summed_into_weighted_score(tmp_path):
    repo = _repo(tmp_path)
    repo.record_faction_mission_completion(123, "Test Faction", _iso(0), influence_tier="+++")
    repo.record_faction_mission_completion(123, "Test Faction", _iso(0), influence_tier="+")
    counts = repo.get_faction_mission_completion_counts(123, "Test Faction")
    assert counts == _counts(today=2, last_7_days=2, weighted_today=4, weighted_last_7_days=4)


def test_missing_tier_contributes_zero_weight_but_still_counts(tmp_path):
    repo = _repo(tmp_path)
    repo.record_faction_mission_completion(123, "Test Faction", _iso(0), influence_tier=None)
    counts = repo.get_faction_mission_completion_counts(123, "Test Faction")
    assert counts == _counts(today=1, last_7_days=1, weighted_today=0, weighted_last_7_days=0)


def test_weighted_score_respects_the_same_time_windows_as_the_count(tmp_path):
    repo = _repo(tmp_path)
    repo.record_faction_mission_completion(123, "Test Faction", _iso(0), influence_tier="+++++")
    repo.record_faction_mission_completion(123, "Test Faction", _iso(3), influence_tier="++")
    repo.record_faction_mission_completion(123, "Test Faction", _iso(10), influence_tier="+")
    counts = repo.get_faction_mission_completion_counts(123, "Test Faction")
    assert counts == _counts(today=1, last_7_days=2, weighted_today=5, weighted_last_7_days=7)
