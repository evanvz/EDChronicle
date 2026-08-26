"""Station economies / DistFromStarLS / government / allegiance capture
from EDDN Docked sightings (extends station_info)."""
import pytest

from edc.core.station_pads import extract_station_info
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL


def _repo(tmp_path) -> Repository:
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return Repository(db)


def _docked_event(**over):
    ev = {
        "event": "Docked",
        "timestamp": "2026-08-26T18:00:00Z",
        "MarketID": 3702356736,
        "StationName": "Jameson Memorial",
        "StarSystem": "Shinrarta Dezhra",
        "StationType": "Orbis",
        "StationServices": ["Commodity Exchange", "Outfitting"],
        "StationEconomies": [
            {"Name": "High Tech", "Proportion": 0.9},
            {"Name": "Refinery", "Proportion": 0.1},
        ],
        "DistFromStarLS": 1234.5,
        "StationGovernment": "$government_Democracy;",
        "StationAllegiance": "Federation",
        "LandingPads": {"Small": 6, "Medium": 9, "Large": 12},
    }
    ev.update(over)
    return ev


def test_extract_station_info_new_fields():
    info = extract_station_info(_docked_event())
    assert info["economies"] == "High Tech:0.9|Refinery:0.1"
    assert info["dist_from_star_ls"] == 1234.5
    assert info["station_government"] == "$government_Democracy;"
    assert info["station_allegiance"] == "Federation"


def test_extract_station_info_missing_fields_tolerated():
    info = extract_station_info(_docked_event(StationEconomies=None, DistFromStarLS=None))
    assert info["economies"] is None
    assert info["dist_from_star_ls"] is None


def test_save_station_info_persists_new_fields(tmp_path):
    repo = _repo(tmp_path)
    info = extract_station_info(_docked_event())
    repo.save_station_info_batch([info])
    row = repo.get_station_info(3702356736)
    assert row is not None
    assert row["dist_from_star_ls"] == 1234.5
    assert "High Tech" in row["economies"]
    assert row["station_allegiance"] == "Federation"


def test_resights_overwrite(tmp_path):
    repo = _repo(tmp_path)
    repo.save_station_info_batch([extract_station_info(_docked_event())])
    ev = _docked_event(DistFromStarLS=999.0)
    repo.save_station_info_batch([extract_station_info(ev)])
    assert repo.get_station_info(3702356736)["dist_from_star_ls"] == 999.0
