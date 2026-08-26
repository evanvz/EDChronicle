"""EDDN outfitting/1 and shipyard/1 schema parsing + persistence.

Outfitting messages carry `modules: [{ModuleName: "hpt_pulselaser_fixed...", ...}]`;
shipyard carries `ships: [{ShipType: "sidewinder", ...}]`. Both share the
market/station/system header fields with commodity/3. Module/ship offerings
change over time — unlike commodity prices they're slow-moving, so a fresh
full snapshot replaces the station's entire previous offering set.
"""
import json

from edc.core.eddn_listener import _OUTFITTING_SCHEMA_PREFIX, _SHIPYARD_SCHEMA_PREFIX
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL


def _outfitting_msg(**over):
    msg = {
        "timestamp": "2026-08-26T19:00:00Z",
        "systemName": "Sol",
        "stationName": "Abraham Lincoln",
        "marketId": 3700448576,
        "modules": [
            {"ModuleName": "hpt_pulselaser_fixed_small", "Name_Localised": "Pulse Laser"},
            {"ModuleName": "int_shieldgenerator_size3_class3", "Name_Localised": "Shield Generator"},
        ],
    }
    msg.update(over)
    return msg


def _shipyard_msg(**over):
    msg = {
        "timestamp": "2026-08-26T19:00:00Z",
        "systemName": "Sol",
        "stationName": "Abraham Lincoln",
        "marketId": 3700448576,
        "ships": [
            {"ShipType": "sidewinder", "ShipType_Localised": "Sidewinder"},
            {"ShipType": "krait_mkii", "ShipType_Localised": "Krait Mk II"},
        ],
    }
    msg.update(over)
    return msg


def _repo(tmp_path) -> Repository:
    db = Database(tmp_path / "test.db")
    db.executescript(SCHEMA_SQL)
    db.run_migrations()
    return Repository(db)


def _schema_for(payload):
    return {"$schemaRef": _OUTFITTING_SCHEMA_PREFIX + "1", "message": payload}


def test_outfitting_roundtrip(tmp_path):
    repo = _repo(tmp_path)
    repo.save_system_coords_batch([("Sol", 0.0, 0.0, 0.0, "2026-08-26T19:00:00Z")])
    repo.save_station_module_listings(3700448576, "Abraham Lincoln", "Sol",
                                      ["hpt_pulselaser_fixed_small", "int_shieldgenerator_size3_class3"],
                                      "2026-08-26T19:00:00Z")
    rows = repo.find_stations_selling_module("pulselaser", 0.0, 0.0, 0.0)
    assert len(rows) == 1
    r = rows[0]
    assert r["station_name"] == "Abraham Lincoln"
    assert r["system_name"] == "Sol"
    assert r["market_id"] == 3700448576
    assert r["module_name"] == "hpt_pulselaser_fixed_small"


def test_outfitting_snapshot_replaces(tmp_path):
    """A fresh full snapshot removes modules no longer offered."""
    repo = _repo(tmp_path)
    repo.save_system_coords_batch([("SysA", 0.0, 0.0, 0.0, "2026-08-26T19:00:00Z")])
    repo.save_station_module_listings(1, "A", "SysA", ["mod1", "mod2"], "2026-08-26T19:00:00Z")
    repo.save_station_module_listings(1, "A", "SysA", ["mod2", "mod3"], "2026-08-26T19:30:00Z")
    assert repo.find_stations_selling_module("mod1", 0, 0, 0) == []
    assert len(repo.find_stations_selling_module("mod3", 0, 0, 0)) == 1


def test_shipyard_roundtrip(tmp_path):
    repo = _repo(tmp_path)
    repo.save_system_coords_batch([("SysA", 0.0, 0.0, 0.0, "2026-08-26T19:00:00Z")])
    repo.save_station_ship_listings(1, "A", "SysA", ["sidewinder", "krait_mkii"], "2026-08-26T19:00:00Z")
    rows = repo.find_stations_selling_ship("krait", 0, 0, 0)
    assert len(rows) == 1
    assert rows[0]["station_name"] == "A"
    assert rows[0]["ship_type"] == "krait_mkii"
    # radius filter: a distant second seller is excluded
    repo.save_system_coords_batch([("FarSys", 500.0, 0.0, 0.0, "2026-08-26T19:00:00Z")])
    repo.save_station_ship_listings(2, "B", "FarSys", ["krait_mkii"], "2026-08-26T19:00:00Z")
    near = repo.find_stations_selling_ship("krait", 0, 0, 0, radius_ly=100)
    assert [r["station_name"] for r in near] == ["A"]


def test_pruner_removes_stale_module_rows(tmp_path):
    repo = _repo(tmp_path)
    repo.save_station_module_listings(1, "A", "SysA", ["mod1"], "2020-01-01T00:00:00Z")
    deleted = repo.prune_stale_station_offerings()
    assert deleted > 0
    assert repo.find_stations_selling_module("mod1", 0, 0, 0) == []
