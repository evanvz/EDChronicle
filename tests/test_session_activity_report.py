"""Repository.get_session_activity_report(since) -- aggregates missions,
combat bonds, CZ kills, and trade/exploration/exobiology sales into
{system_name: {faction_name: {...}}}, for the session BGS activity
report (a whole-session, all-faction view -- distinct from the Faction
Expansion tracker, which is scoped to one target faction/system). Real
SQLite (temp file), matching this repo's convention."""
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


def test_missions_are_grouped_by_system_and_faction(tmp_path):
    repo = _repo(tmp_path)
    _seed_system(repo, 12345, "Ekono")
    repo.record_faction_mission_completion(12345, "Elite United Worlds", "2026-09-25T10:00:00Z", influence_tier="++", is_primary=True)
    report = repo.get_session_activity_report("2026-09-25T00:00:00Z")
    assert report["Ekono"]["Elite United Worlds"]["missions"] == {
        "count": 1, "weighted": 2, "primary_count": 1, "secondary_count": 0,
    }


def test_combat_bonds_are_summed_per_faction(tmp_path):
    repo = _repo(tmp_path)
    _seed_system(repo, 12345, "Ekono")
    repo.record_faction_combat_bond(12345, "Elite United Worlds", 15000, "2026-09-25T10:00:00Z")
    repo.record_faction_combat_bond(12345, "Elite United Worlds", 5000, "2026-09-25T11:00:00Z")
    report = repo.get_session_activity_report("2026-09-25T00:00:00Z")
    assert report["Ekono"]["Elite United Worlds"]["combat_bonds_total"] == 20000


def test_cz_kills_are_bucketed_by_zone_and_size(tmp_path):
    repo = _repo(tmp_path)
    _seed_system(repo, 12345, "Ekono")
    repo.record_faction_cz_kill(12345, "Elite United Worlds", "space", "h", "2026-09-25T10:00:00Z")
    repo.record_faction_cz_kill(12345, "Elite United Worlds", "space", "h", "2026-09-25T11:00:00Z")
    repo.record_faction_cz_kill(12345, "Elite United Worlds", "ground", "l", "2026-09-25T12:00:00Z")
    report = repo.get_session_activity_report("2026-09-25T00:00:00Z")
    cz = report["Ekono"]["Elite United Worlds"]["cz_kills"]
    assert cz == {"ground_l": 1, "ground_m": 0, "ground_h": 0, "space_l": 0, "space_m": 0, "space_h": 2}


def test_trade_sold_is_bucketed_by_kind(tmp_path):
    repo = _repo(tmp_path)
    _seed_system(repo, 12345, "Ekono")
    repo.record_faction_trade_sold(12345, "Elite United Worlds", "commodity", 63085, "2026-09-25T10:00:00Z")
    repo.record_faction_trade_sold(12345, "Elite United Worlds", "exploration", 1305717, "2026-09-25T11:00:00Z")
    report = repo.get_session_activity_report("2026-09-25T00:00:00Z")
    trade = report["Ekono"]["Elite United Worlds"]["trade_sold"]
    assert trade == {"commodity": 63085, "exploration": 1305717, "exobiology": 0}


def test_multiple_systems_and_factions_stay_separate(tmp_path):
    repo = _repo(tmp_path)
    _seed_system(repo, 12345, "Ekono")
    _seed_system(repo, 999, "Aiga")
    repo.record_faction_combat_bond(12345, "Elite United Worlds", 1000, "2026-09-25T10:00:00Z")
    repo.record_faction_combat_bond(999, "Hungarian Wolves", 2000, "2026-09-25T10:00:00Z")
    report = repo.get_session_activity_report("2026-09-25T00:00:00Z")
    assert set(report.keys()) == {"Ekono", "Aiga"}
    assert report["Ekono"]["Elite United Worlds"]["combat_bonds_total"] == 1000
    assert report["Aiga"]["Hungarian Wolves"]["combat_bonds_total"] == 2000


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
