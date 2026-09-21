"""GuardianTechBrokerTable (settings loader) and
Repository.get_known_guardian_tech_broker_stations() -- Frontier's own
StationServices data has no Guardian/Human sub-type for "techBroker", so
this cross-references a curated (system_name, station_name) reference
list against real net.station_info sightings, same shape as
get_known_rare_goods()."""
import json

from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL
from edc.core.guardian_tech_broker_stations import GuardianTechBrokerTable


def _repo(tmp_path):
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return Repository(db)


def _seed_station(repo, system_name, station_name, x, y, z, station_type="Coriolis"):
    repo.db.execute(
        """INSERT INTO station_info (market_id, station_name, system_name, station_type)
           VALUES (?, ?, ?, ?)""",
        (hash((system_name, station_name)) % 2_000_000_000, station_name, system_name, station_type),
    )
    repo.db.execute(
        "INSERT INTO system_coords (system_name, x, y, z) VALUES (?, ?, ?, ?)",
        (system_name, x, y, z),
    )


# --- GuardianTechBrokerTable loader ---

def test_loads_stations_from_settings_json(tmp_path):
    (tmp_path / "guardian_tech_broker_stations.json").write_text(
        json.dumps({"stations": [{"system_name": "Sol", "station_name": "Abraham Lincoln"}]}),
        encoding="utf-8",
    )
    table = GuardianTechBrokerTable(tmp_path)
    assert table.all() == [{"system_name": "Sol", "station_name": "Abraham Lincoln"}]


def test_missing_file_returns_empty_list_not_an_error(tmp_path):
    table = GuardianTechBrokerTable(tmp_path)
    assert table.all() == []


def test_malformed_json_returns_empty_list_not_an_error(tmp_path):
    (tmp_path / "guardian_tech_broker_stations.json").write_text("not valid json", encoding="utf-8")
    table = GuardianTechBrokerTable(tmp_path)
    assert table.all() == []


# --- Repository.get_known_guardian_tech_broker_stations ---

def test_returns_station_seen_via_eddn(tmp_path):
    repo = _repo(tmp_path)
    _seed_station(repo, "Shinrarta Dezhra", "Jameson Memorial", 55.71, 17.59, 27.16)
    stations = [{"system_name": "Shinrarta Dezhra", "station_name": "Jameson Memorial"}]
    results = repo.get_known_guardian_tech_broker_stations(stations, 0.0, 0.0, 0.0)
    assert len(results) == 1
    assert results[0]["station_name"] == "Jameson Memorial"
    assert results[0]["system_name"] == "Shinrarta Dezhra"
    assert results[0]["distance_ly"] > 0


def test_station_never_reported_via_eddn_is_omitted_not_guessed(tmp_path):
    repo = _repo(tmp_path)
    stations = [{"system_name": "Never Visited", "station_name": "Nobody's Station"}]
    results = repo.get_known_guardian_tech_broker_stations(stations, 0.0, 0.0, 0.0)
    assert results == []


def test_matches_case_insensitively(tmp_path):
    repo = _repo(tmp_path)
    _seed_station(repo, "sol", "abraham lincoln", 0.0, 0.0, 0.0)
    stations = [{"system_name": "Sol", "station_name": "Abraham Lincoln"}]
    results = repo.get_known_guardian_tech_broker_stations(stations, 0.0, 0.0, 0.0)
    assert len(results) == 1


def test_empty_reference_list_returns_empty_without_querying(tmp_path):
    repo = _repo(tmp_path)
    assert repo.get_known_guardian_tech_broker_stations([], 0.0, 0.0, 0.0) == []


def test_results_sorted_by_distance(tmp_path):
    repo = _repo(tmp_path)
    _seed_station(repo, "Far System", "Far Station", 100.0, 0.0, 0.0)
    _seed_station(repo, "Near System", "Near Station", 1.0, 0.0, 0.0)
    stations = [
        {"system_name": "Far System", "station_name": "Far Station"},
        {"system_name": "Near System", "station_name": "Near Station"},
    ]
    results = repo.get_known_guardian_tech_broker_stations(stations, 0.0, 0.0, 0.0)
    assert [r["station_name"] for r in results] == ["Near Station", "Far Station"]
