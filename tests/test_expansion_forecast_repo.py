"""Repository side of the Expansion Forecast: faction presence summary,
cube systems with population, and the candidate cache."""
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL

EUW = "Elite United Worlds"


def _repo(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return Repository(db)


def _snap(repo, addr, date_, inf, rec=None):
    f = {"Name": EUW, "Influence": inf}
    if rec:
        f["RecoveringStates"] = rec
    repo.save_faction_snapshot(addr, f, date_, True, f"{date_}T12:00:00Z", "edsm")


def test_presence_has_first_and_latest_reading(tmp_path):
    repo = _repo(tmp_path)
    repo.db.execute("INSERT INTO systems (system_address, system_name) VALUES (1, 'Ekono'), (2, 'YF-W')")
    _snap(repo, 1, "2026-10-06", 0.7895)
    _snap(repo, 1, "2026-10-07", 0.6789, [{"State": "Expansion", "Trend": 0}])
    _snap(repo, 2, "2026-10-07", 0.091)
    rows = {r["system_name"]: r for r in repo.get_squadron_presence(EUW)}
    assert rows["Ekono"]["first_seen"] == "2026-10-06" and rows["Ekono"]["last_seen"] == "2026-10-07"
    assert round(rows["Ekono"]["influence"], 4) == 0.6789
    assert "Expansion" in rows["Ekono"]["recovering_states"]
    assert rows["YF-W"]["first_seen"] == "2026-10-07"
    assert repo.get_squadron_presence("Nobody") == []


def test_cube_systems_with_population(tmp_path):
    repo = _repo(tmp_path)
    for name, xyz in (("In", (10.0, 0.0, 0.0)), ("Corner", (19.0, 19.0, 19.0)), ("Out", (25.0, 0.0, 0.0))):
        repo.db.execute("INSERT INTO system_coords (system_name, x, y, z) VALUES (?, ?, ?, ?)", (name, *xyz))
    repo.db.execute("INSERT INTO net.system_bgs_status (system_address, system_name, population) "
                    "VALUES (11, 'In', 5000)")
    got = {r["system_name"]: r for r in repo.get_cube_systems(0.0, 0.0, 0.0, 20.0)}
    assert set(got) == {"In", "Corner"}
    assert got["In"]["population"] == 5000 and got["In"]["system_address"] == 11
    assert got["Corner"]["population"] is None


def test_candidate_cache_replaces_per_source(tmp_path):
    repo = _repo(tmp_path)
    rows = [{"system_name": "Arimavante", "system_address": 4756911035114, "distance_ly": 10.9,
             "faction_count": 6, "faction_present": False}]
    repo.save_expansion_candidates(1, rows, "2026-10-08T10:00:00Z")
    repo.save_expansion_candidates(1, rows[:0] + [dict(rows[0], faction_count=7)], "2026-10-09T10:00:00Z")
    repo.save_expansion_candidates(2, rows, "2026-10-08T10:00:00Z")
    got = repo.get_expansion_candidates(1)
    assert len(got) == 1 and got[0]["faction_count"] == 7 and got[0]["fetched_at"] == "2026-10-09T10:00:00Z"
    assert got[0]["faction_present"] is False
    assert len(repo.get_expansion_candidates(2)) == 1
