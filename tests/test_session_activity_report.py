"""Repository.get_session_activity_report(since) -- aggregates missions,
combat bonds, CZ kills, and trade/exploration/exobiology sales into
{date: {system_name: {faction_name: {...}}}}, for the session BGS
activity report (a whole-session, all-faction view -- distinct from the
Faction Expansion tracker, which is scoped to one target faction/system).
date is grouped first since a delayed BGS tick can make a single "since
last tick" window span more than one calendar day. Real SQLite (temp
file), matching this repo's convention."""
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL


def _repo(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return Repository(db)


def _seed_system(repo, system_address, system_name):
    repo.db.execute(
        "INSERT INTO systems (system_address, system_name) VALUES (?, ?)",
        (system_address, system_name),
    )


def test_empty_report_with_no_activity(tmp_path):
    repo = _repo(tmp_path)
    assert repo.get_session_activity_report("2026-09-25T00:00:00Z") == {}


def test_missions_are_grouped_by_date_system_and_faction(tmp_path):
    repo = _repo(tmp_path)
    _seed_system(repo, 12345, "Ekono")
    repo.record_faction_mission_completion(
        12345, "Elite United Worlds", "2026-09-25T10:00:00Z",
        influence_tier="++", is_primary=True, mission_type="Courier", reward=48200,
    )
    report = repo.get_session_activity_report("2026-09-25T00:00:00Z")
    assert report["2026-09-25"]["Ekono"]["Elite United Worlds"]["missions"] == {
        "count": 1, "weighted": 2, "primary_count": 1, "secondary_count": 0,
        "by_type": {"Courier": 1}, "reward_total": 48200, "reward_by_type": {"Courier": 48200},
    }


def test_missions_are_broken_down_by_type(tmp_path):
    repo = _repo(tmp_path)
    _seed_system(repo, 12345, "Ekono")
    repo.record_faction_mission_completion(
        12345, "Elite United Worlds", "2026-09-25T10:00:00Z", mission_type="Courier",
    )
    repo.record_faction_mission_completion(
        12345, "Elite United Worlds", "2026-09-25T11:00:00Z", mission_type="Courier",
    )
    repo.record_faction_mission_completion(
        12345, "Elite United Worlds", "2026-09-25T12:00:00Z", mission_type="Massacre Conflict CivilWar",
    )
    repo.record_faction_mission_completion(
        12345, "Elite United Worlds", "2026-09-25T13:00:00Z",
    )  # no mission_type -- older row shape
    report = repo.get_session_activity_report("2026-09-25T00:00:00Z")
    by_type = report["2026-09-25"]["Ekono"]["Elite United Worlds"]["missions"]["by_type"]
    assert by_type == {"Courier": 2, "Massacre Conflict CivilWar": 1, "Unknown": 1}


def test_reward_is_summed_by_type_from_primary_rows_only(tmp_path):
    repo = _repo(tmp_path)
    _seed_system(repo, 12345, "Ekono")
    repo.record_faction_mission_completion(
        12345, "Elite United Worlds", "2026-09-25T10:00:00Z",
        mission_type="Courier", reward=10000, is_primary=True,
    )
    repo.record_faction_mission_completion(
        12345, "Elite United Worlds", "2026-09-25T11:00:00Z",
        mission_type="Courier", reward=20000, is_primary=True,
    )
    # A secondary-effect row for the same faction/system, with the same
    # reward value as some primary mission elsewhere -- must NOT be summed.
    repo.record_faction_mission_completion(
        12345, "Elite United Worlds", "2026-09-25T12:00:00Z",
        mission_type="Courier", reward=99999, is_primary=False,
    )
    report = repo.get_session_activity_report("2026-09-25T00:00:00Z")
    m = report["2026-09-25"]["Ekono"]["Elite United Worlds"]["missions"]
    assert m["reward_total"] == 30000
    assert m["reward_by_type"] == {"Courier": 30000}


def test_missions_with_no_recorded_reward_contribute_zero(tmp_path):
    repo = _repo(tmp_path)
    _seed_system(repo, 12345, "Ekono")
    repo.record_faction_mission_completion(
        12345, "Elite United Worlds", "2026-09-25T10:00:00Z", mission_type="Courier",
    )  # reward=None, older row shape or missing journal field
    report = repo.get_session_activity_report("2026-09-25T00:00:00Z")
    m = report["2026-09-25"]["Ekono"]["Elite United Worlds"]["missions"]
    assert m["reward_total"] == 0
    assert m["reward_by_type"] == {"Courier": 0}


def test_combat_bonds_are_summed_per_faction(tmp_path):
    repo = _repo(tmp_path)
    _seed_system(repo, 12345, "Ekono")
    repo.record_faction_combat_bond(12345, "Elite United Worlds", 15000, "2026-09-25T10:00:00Z")
    repo.record_faction_combat_bond(12345, "Elite United Worlds", 5000, "2026-09-25T11:00:00Z")
    report = repo.get_session_activity_report("2026-09-25T00:00:00Z")
    assert report["2026-09-25"]["Ekono"]["Elite United Worlds"]["combat_bonds_total"] == 20000


def test_cz_kills_are_bucketed_by_zone_and_size(tmp_path):
    repo = _repo(tmp_path)
    _seed_system(repo, 12345, "Ekono")
    repo.record_faction_cz_kill(12345, "Elite United Worlds", "space", "h", "2026-09-25T10:00:00Z")
    repo.record_faction_cz_kill(12345, "Elite United Worlds", "space", "h", "2026-09-25T11:00:00Z")
    repo.record_faction_cz_kill(12345, "Elite United Worlds", "ground", "l", "2026-09-25T12:00:00Z")
    report = repo.get_session_activity_report("2026-09-25T00:00:00Z")
    cz = report["2026-09-25"]["Ekono"]["Elite United Worlds"]["cz_kills"]
    assert cz == {"ground_l": 1, "ground_m": 0, "ground_h": 0, "space_l": 0, "space_m": 0, "space_h": 2}


def test_trade_sold_is_bucketed_by_kind(tmp_path):
    repo = _repo(tmp_path)
    _seed_system(repo, 12345, "Ekono")
    repo.record_faction_trade_sold(12345, "Elite United Worlds", "commodity", 63085, "2026-09-25T10:00:00Z")
    repo.record_faction_trade_sold(12345, "Elite United Worlds", "exploration", 1305717, "2026-09-25T11:00:00Z")
    report = repo.get_session_activity_report("2026-09-25T00:00:00Z")
    trade = report["2026-09-25"]["Ekono"]["Elite United Worlds"]["trade_sold"]
    assert trade == {"commodity": 63085, "exploration": 1305717, "exobiology": 0}


def test_multiple_systems_and_factions_stay_separate(tmp_path):
    repo = _repo(tmp_path)
    _seed_system(repo, 12345, "Ekono")
    _seed_system(repo, 999, "Aiga")
    repo.record_faction_combat_bond(12345, "Elite United Worlds", 1000, "2026-09-25T10:00:00Z")
    repo.record_faction_combat_bond(999, "Hungarian Wolves", 2000, "2026-09-25T10:00:00Z")
    report = repo.get_session_activity_report("2026-09-25T00:00:00Z")
    assert set(report["2026-09-25"].keys()) == {"Ekono", "Aiga"}
    assert report["2026-09-25"]["Ekono"]["Elite United Worlds"]["combat_bonds_total"] == 1000
    assert report["2026-09-25"]["Aiga"]["Hungarian Wolves"]["combat_bonds_total"] == 2000


def test_activity_before_since_is_excluded(tmp_path):
    repo = _repo(tmp_path)
    _seed_system(repo, 12345, "Ekono")
    repo.record_faction_combat_bond(12345, "Elite United Worlds", 1000, "2026-09-24T10:00:00Z")
    report = repo.get_session_activity_report("2026-09-25T00:00:00Z")
    assert report == {}


def test_system_with_no_systems_row_is_skipped(tmp_path):
    repo = _repo(tmp_path)
    # No _seed_system call -- system_address 12345 has no systems row.
    repo.record_faction_combat_bond(12345, "Elite United Worlds", 1000, "2026-09-25T10:00:00Z")
    report = repo.get_session_activity_report("2026-09-25T00:00:00Z")
    assert report == {}


# --- day grouping specifically ---

def test_activity_on_different_days_stays_in_separate_day_buckets(tmp_path):
    """A delayed tick can make a single 'since last tick' window span more
    than one calendar day -- confirms each day's activity is kept apart,
    not merged into one flat total."""
    repo = _repo(tmp_path)
    _seed_system(repo, 12345, "Ekono")
    repo.record_faction_combat_bond(12345, "Elite United Worlds", 1000, "2026-09-24T22:00:00Z")
    repo.record_faction_combat_bond(12345, "Elite United Worlds", 2000, "2026-09-25T06:00:00Z")
    report = repo.get_session_activity_report("2026-09-24T00:00:00Z")
    assert set(report.keys()) == {"2026-09-24", "2026-09-25"}
    assert report["2026-09-24"]["Ekono"]["Elite United Worlds"]["combat_bonds_total"] == 1000
    assert report["2026-09-25"]["Ekono"]["Elite United Worlds"]["combat_bonds_total"] == 2000


def test_same_system_and_faction_on_the_same_day_still_accumulates(tmp_path):
    repo = _repo(tmp_path)
    _seed_system(repo, 12345, "Ekono")
    repo.record_faction_combat_bond(12345, "Elite United Worlds", 1000, "2026-09-25T09:00:00Z")
    repo.record_faction_combat_bond(12345, "Elite United Worlds", 2000, "2026-09-25T15:00:00Z")
    report = repo.get_session_activity_report("2026-09-25T00:00:00Z")
    assert report["2026-09-25"]["Ekono"]["Elite United Worlds"]["combat_bonds_total"] == 3000


# --- trend sign (2026-09-26: "DownBad" secondary effects were being
# counted as a flat positive with no sign) ---

def test_downbad_trend_subtracts_from_weighted(tmp_path):
    repo = _repo(tmp_path)
    _seed_system(repo, 12345, "Ekono")
    repo.record_faction_mission_completion(
        12345, "Cameron's Combat Services", "2026-09-25T10:00:00Z",
        influence_tier="+", is_primary=False, mission_type="Salvage Refinery", trend="DownBad",
    )
    report = repo.get_session_activity_report("2026-09-25T00:00:00Z")
    m = report["2026-09-25"]["Ekono"]["Cameron's Combat Services"]["missions"]
    assert m["weighted"] == -1
    assert m["count"] == 1  # count itself is unaffected by sign


def test_mixed_signed_and_unsigned_rows_sum_correctly(tmp_path):
    repo = _repo(tmp_path)
    _seed_system(repo, 12345, "Ekono")
    repo.record_faction_mission_completion(
        12345, "Elite United Worlds", "2026-09-25T10:00:00Z",
        influence_tier="+++++", is_primary=True, mission_type="Salvage Refinery", trend="UpGood",
    )
    repo.record_faction_mission_completion(
        12345, "Elite United Worlds", "2026-09-25T11:00:00Z",
        influence_tier="++", is_primary=True, mission_type="Courier",
    )  # no trend recorded -- defaults to positive
    report = repo.get_session_activity_report("2026-09-25T00:00:00Z")
    m = report["2026-09-25"]["Ekono"]["Elite United Worlds"]["missions"]
    assert m["weighted"] == 7  # 5 + 2, both positive
