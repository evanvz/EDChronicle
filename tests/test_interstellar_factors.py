"""Tests for find_closest_interstellar_factors()'s exclusion rule --
confirmed against Elite Dangerous's actual mechanic (cross-checked
multiple sources): Interstellar Factors refuses to clear a bounty/fine
if the issuing faction has ANY presence in that system, not merely if
it controls the specific station offering the service. Real SQLite
(temp file), same fixture shape as test_bgs_status_repository.py."""
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


def _add_station(repo, market_id, station_name, system_name, station_faction, x, y, z):
    repo.db.execute(
        """INSERT INTO station_info
           (market_id, station_name, system_name, station_type, station_faction, station_services, last_visited)
           VALUES (?, ?, ?, 'Coriolis', ?, 'Facilitator', '2026-08-24T00:00:00Z')""",
        (market_id, station_name, system_name, station_faction),
    )
    repo.db.execute(
        "INSERT INTO system_coords (system_name, x, y, z) VALUES (?, ?, ?, ?)",
        (system_name, x, y, z),
    )


def _add_system_faction_presence(repo, system_address, system_name, faction_name):
    repo.db.execute(
        "INSERT INTO systems (system_address, system_name) VALUES (?, ?)",
        (system_address, system_name),
    )
    repo.save_faction_snapshot(
        system_address, {"Name": faction_name, "Influence": 0.1}, "2026-08-24", False, "2026-08-24T00:00:00Z", "journal",
    )


def test_excludes_station_controlled_by_issuing_faction(repo):
    _add_station(repo, 1, "Bad Station", "SysA", "Enemy Faction", 0.0, 0.0, 0.0)
    result = repo.find_closest_interstellar_factors(0.0, 0.0, 0.0, exclude_factions=["Enemy Faction"])
    assert result is None


def test_excludes_station_in_system_where_faction_has_non_controlling_presence(repo):
    # Real rule: a 5%-influence minor presence still blocks Interstellar
    # Factors, even though this station is controlled by someone else
    # entirely -- this is the exact case the old station-only check missed.
    _add_station(repo, 1, "Good-Looking Station", "SysA", "Some Other Faction", 0.0, 0.0, 0.0)
    _add_system_faction_presence(repo, 111, "SysA", "Enemy Faction")
    result = repo.find_closest_interstellar_factors(0.0, 0.0, 0.0, exclude_factions=["Enemy Faction"])
    assert result is None


def test_allows_station_in_system_with_no_excluded_faction_presence(repo):
    _add_station(repo, 1, "Clear Station", "SysB", "Some Other Faction", 0.0, 0.0, 0.0)
    _add_system_faction_presence(repo, 222, "SysB", "Unrelated Faction")
    result = repo.find_closest_interstellar_factors(0.0, 0.0, 0.0, exclude_factions=["Enemy Faction"])
    assert result is not None
    assert result["station_name"] == "Clear Station"


def test_no_exclusions_returns_closest_station(repo):
    _add_station(repo, 1, "Near", "SysNear", "Faction X", 0.0, 0.0, 0.0)
    _add_station(repo, 2, "Far", "SysFar", "Faction Y", 500.0, 0.0, 0.0)
    result = repo.find_closest_interstellar_factors(0.0, 0.0, 0.0, exclude_factions=None)
    assert result["station_name"] == "Near"
