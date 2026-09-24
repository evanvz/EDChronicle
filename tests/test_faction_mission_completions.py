"""Repository.record_faction_mission_completion / get_faction_mission_
completion_counts -- backs the Faction Expansion tracker's "missions
completed today / last 7 days" display, plus a weighted score from
Frontier's own qualitative "+" to "+++++" influence-impact rating
(no exact point value is ever exposed by the game). Primary/secondary
mirrors BGS-Tally: primary is the effect on the mission's own issuing
faction, secondary is every other faction FactionEffects names (e.g. a
destination/target faction). active_missions discards a mission's
faction/system the instant it completes (see mission_events.py), so
this is the only durable record. Real SQLite (temp file), matching
this repo's convention."""
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


def _bucket(count=0, weighted=0, primary_count=0, primary_weighted=0, secondary_count=0, secondary_weighted=0):
    return {
        "count": count, "weighted": weighted,
        "primary_count": primary_count, "primary_weighted": primary_weighted,
        "secondary_count": secondary_count, "secondary_weighted": secondary_weighted,
    }


def _counts(today=None, last_7_days=None):
    return {"today": today or _bucket(), "last_7_days": last_7_days or _bucket()}


def test_counts_zero_with_no_completions(tmp_path):
    repo = _repo(tmp_path)
    assert repo.get_faction_mission_completion_counts(123, "Test Faction") == _counts()


def test_a_completion_today_counts_in_both_buckets(tmp_path):
    repo = _repo(tmp_path)
    repo.record_faction_mission_completion(123, "Test Faction", _iso(0))
    counts = repo.get_faction_mission_completion_counts(123, "Test Faction")
    b = _bucket(count=1, primary_count=1)
    assert counts == _counts(today=b, last_7_days=b)


def test_a_completion_three_days_ago_counts_only_in_weekly(tmp_path):
    repo = _repo(tmp_path)
    repo.record_faction_mission_completion(123, "Test Faction", _iso(3))
    counts = repo.get_faction_mission_completion_counts(123, "Test Faction")
    assert counts == _counts(last_7_days=_bucket(count=1, primary_count=1))


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
    b = _bucket(count=1, primary_count=1)
    assert counts == _counts(today=b, last_7_days=b)


def test_multiple_completions_accumulate(tmp_path):
    repo = _repo(tmp_path)
    for _ in range(3):
        repo.record_faction_mission_completion(123, "Test Faction", _iso(0))
    repo.record_faction_mission_completion(123, "Test Faction", _iso(2))
    counts = repo.get_faction_mission_completion_counts(123, "Test Faction")
    assert counts == _counts(
        today=_bucket(count=3, primary_count=3),
        last_7_days=_bucket(count=4, primary_count=4),
    )


# --- influence_tier weighting ---

def test_tier_length_is_summed_into_weighted_score(tmp_path):
    repo = _repo(tmp_path)
    repo.record_faction_mission_completion(123, "Test Faction", _iso(0), influence_tier="+++")
    repo.record_faction_mission_completion(123, "Test Faction", _iso(0), influence_tier="+")
    counts = repo.get_faction_mission_completion_counts(123, "Test Faction")
    b = _bucket(count=2, weighted=4, primary_count=2, primary_weighted=4)
    assert counts == _counts(today=b, last_7_days=b)


def test_missing_tier_contributes_zero_weight_but_still_counts(tmp_path):
    repo = _repo(tmp_path)
    repo.record_faction_mission_completion(123, "Test Faction", _iso(0), influence_tier=None)
    counts = repo.get_faction_mission_completion_counts(123, "Test Faction")
    b = _bucket(count=1, primary_count=1)
    assert counts == _counts(today=b, last_7_days=b)


def test_weighted_score_respects_the_same_time_windows_as_the_count(tmp_path):
    repo = _repo(tmp_path)
    repo.record_faction_mission_completion(123, "Test Faction", _iso(0), influence_tier="+++++")
    repo.record_faction_mission_completion(123, "Test Faction", _iso(3), influence_tier="++")
    repo.record_faction_mission_completion(123, "Test Faction", _iso(10), influence_tier="+")
    counts = repo.get_faction_mission_completion_counts(123, "Test Faction")
    assert counts == _counts(
        today=_bucket(count=1, weighted=5, primary_count=1, primary_weighted=5),
        last_7_days=_bucket(count=2, weighted=7, primary_count=2, primary_weighted=7),
    )


# --- primary/secondary split ---

def test_secondary_completion_is_split_out(tmp_path):
    repo = _repo(tmp_path)
    repo.record_faction_mission_completion(123, "Test Faction", _iso(0), influence_tier="++", is_primary=True)
    repo.record_faction_mission_completion(123, "Test Faction", _iso(0), influence_tier="+", is_primary=False)
    counts = repo.get_faction_mission_completion_counts(123, "Test Faction")
    b = _bucket(count=2, weighted=3, primary_count=1, primary_weighted=2, secondary_count=1, secondary_weighted=1)
    assert counts == _counts(today=b, last_7_days=b)


def test_defaults_to_primary_when_not_specified(tmp_path):
    repo = _repo(tmp_path)
    repo.record_faction_mission_completion(123, "Test Faction", _iso(0))
    counts = repo.get_faction_mission_completion_counts(123, "Test Faction")
    b = _bucket(count=1, primary_count=1)
    assert counts == _counts(today=b, last_7_days=b)
