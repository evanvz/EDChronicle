"""Repository.get_known_construction_sites() -- distinct (system_name,
station_name) pairs from our own personal station_info for any station
whose name marks it a colonisation construction site. Backs the
Colonisation tab's "Known Sites" autocomplete, which exists so a manually
typed site name can't drift from the exact string a real dock will later
report (see save_colonisation_depot_visit's own docstring for the
consequence when it does)."""
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL


def _repo(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return Repository(db)


def _seed_station(repo, system_name, station_name):
    repo.db.execute(
        "INSERT INTO net.station_info (market_id, station_name, system_name, station_type) VALUES (?, ?, ?, ?)",
        (hash((system_name, station_name)) % 2_000_000_000, station_name, system_name, "SpaceConstructionDepot"),
    )


def test_returns_only_construction_sites(tmp_path):
    repo = _repo(tmp_path)
    _seed_station(repo, "HIP 105879", "Orbital Construction Site: Asling's Gift")
    _seed_station(repo, "Sol", "Abraham Lincoln")  # ordinary station -- not a construction site
    sites = repo.get_known_construction_sites()
    assert sites == [{"system_name": "HIP 105879", "station_name": "Orbital Construction Site: Asling's Gift"}]


def test_returns_distinct_pairs(tmp_path):
    repo = _repo(tmp_path)
    _seed_station(repo, "HIP 105879", "Orbital Construction Site: Asling's Gift")
    repo.db.execute(
        "UPDATE net.station_info SET last_visited = ? WHERE market_id = ?",
        ("2026-09-22T00:00:00Z", hash(("HIP 105879", "Orbital Construction Site: Asling's Gift")) % 2_000_000_000),
    )
    sites = repo.get_known_construction_sites()
    assert len(sites) == 1


def test_no_construction_sites_returns_empty_list(tmp_path):
    repo = _repo(tmp_path)
    _seed_station(repo, "Sol", "Abraham Lincoln")
    assert repo.get_known_construction_sites() == []


def test_empty_database_returns_empty_list(tmp_path):
    repo = _repo(tmp_path)
    assert repo.get_known_construction_sites() == []
