"""Repository.save_system_profile()/get_system_profile_by_name() -- real
economy/government/security/population/allegiance crowd-sourced from
EDDN, sharing net.system_bgs_status with save_system_bgs_status() but
via its own profile_timestamp column so the two write paths (BGS
conflicts vs economy profile) can never clobber each other's freshness
ordering or fields."""
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL


def _repo(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return Repository(db)


def test_save_and_get_system_profile(tmp_path):
    repo = _repo(tmp_path)
    repo.save_system_profile(
        3205949786483, "Ekono", "$economy_Agri;", "$economy_HighTech;",
        "$government_Patronage;", "$SYSTEM_SECURITY_medium;", 2474591197, "Empire",
        "2026-09-02T15:30:25Z", "eddn",
    )

    row = repo.get_system_profile_by_name("Ekono")
    assert row is not None
    assert row["economy"] == "$economy_Agri;"
    assert row["second_economy"] == "$economy_HighTech;"
    assert row["government"] == "$government_Patronage;"
    assert row["security"] == "$SYSTEM_SECURITY_medium;"
    assert row["population"] == 2474591197
    assert row["allegiance"] == "Empire"


def test_get_system_profile_by_name_unknown_system_returns_none(tmp_path):
    repo = _repo(tmp_path)
    assert repo.get_system_profile_by_name("Nowhere") is None


def test_save_system_profile_does_not_clobber_bgs_status(tmp_path):
    repo = _repo(tmp_path)
    conflicts = [{"WarType": "war", "Status": "active", "Faction1": {"Name": "A", "WonDays": 1}, "Faction2": {"Name": "B", "WonDays": 0}}]
    repo.save_system_bgs_status(1, "Sol", conflicts, [], "2026-09-01T00:00:00Z", "eddn")

    repo.save_system_profile(
        1, "Sol", "$economy_Agri;", "", "$government_Patronage;", "$SYSTEM_SECURITY_medium;",
        1000, "Empire", "2026-09-02T00:00:00Z", "eddn",
    )

    row = repo.get_system_profile_by_name("Sol")
    assert row["economy"] == "$economy_Agri;"

    import json
    bgs_row = repo.db.conn.execute(
        "SELECT * FROM net.system_bgs_status WHERE system_address = 1"
    ).fetchone()
    assert json.loads(bgs_row["conflicts"])[0]["faction1"] == "A"


def test_stale_profile_does_not_overwrite_newer(tmp_path):
    repo = _repo(tmp_path)
    repo.save_system_profile(1, "Sol", "$economy_HighTech;", "", "", "", None, "", "2026-09-02T00:00:00Z", "eddn")
    repo.save_system_profile(1, "Sol", "$economy_Agri;", "", "", "", None, "", "2026-08-01T00:00:00Z", "eddn")

    row = repo.get_system_profile_by_name("Sol")
    assert row["economy"] == "$economy_HighTech;"


def test_empty_economy_is_skipped(tmp_path):
    repo = _repo(tmp_path)
    repo.save_system_profile(1, "Sol", "", "", "", "", None, "", "2026-09-02T00:00:00Z", "eddn")

    assert repo.get_system_profile_by_name("Sol") is None
