# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the GNU General Public License v3.0 or later (GPL-3.0-or-later).
# See the LICENSE file in the project root for full terms.

from pathlib import Path

from edc.core.event_engine import EventEngine
from edc.core.exo_predictor import load_rules, predict_system
from edc.core.exo_values import ExoValueTable
from edc.core.state import GameState


def _engine(tmp_path):
    return EventEngine(GameState(), tmp_path)


def _loc(name, addr, ev="FSDJump"):
    return {"event": ev, "timestamp": "2026-11-06T10:00:00Z", "StarSystem": name, "SystemAddress": addr}


def _star(engine):
    engine.process({"event": "Scan", "timestamp": "2026-11-06T10:01:00Z", "BodyName": "Sol", "BodyID": 0,
                    "StarType": "K", "Luminosity": "Va", "DistanceFromArrivalLS": 0.0})


def test_star_scan_kept(tmp_path):
    e = _engine(tmp_path)
    e.process(_loc("Sol", 1))
    _star(e)
    assert e.state.system_stars[0] == {"StarType": "K", "Luminosity": "Va", "DistanceLS": 0.0}
    assert "Sol" not in e.state.bodies


def test_planet_scan_keeps_parents(tmp_path):
    e = _engine(tmp_path)
    e.process(_loc("Sol", 1))
    e.process({"event": "Scan", "timestamp": "2026-11-06T10:02:00Z", "BodyName": "Sol 1", "BodyID": 1,
               "PlanetClass": "Rocky body", "Parents": [{"Star": 0}], "DistanceFromArrivalLS": 5.0})
    assert e.state.bodies["Sol 1"]["Parents"] == [{"Star": 0}]


def test_fsdjump_clears_stars(tmp_path):
    e = _engine(tmp_path)
    e.process(_loc("Sol", 1))
    _star(e)
    e.process(_loc("Alpha", 2))
    assert e.state.system_stars == {}


def test_location_new_system_clears_stars_and_fss_complete(tmp_path):
    e = _engine(tmp_path)
    e.process(_loc("Sol", 1, "Location"))
    _star(e)
    e.state.fss_complete = True
    e.process(_loc("Alpha", 2, "Location"))
    assert e.state.system_stars == {}
    assert e.state.fss_complete is False


def _bio_planet_scan():
    return {"event": "Scan", "timestamp": "2026-11-06T10:03:00Z", "BodyName": "Sol 1", "BodyID": 1,
            "PlanetClass": "Rocky body", "Parents": [{"Star": 0}], "DistanceFromArrivalLS": 5.0,
            "SurfaceGravity": 1.0, "SurfaceTemperature": 177.0, "SurfacePressure": 2000.0,
            "AtmosphereType": "CarbonDioxide", "AtmosphereComposition": [{"Name": "CarbonDioxide", "Percent": 99.0}],
            "OrbitalPeriod": 80000.0, "Volcanism": "", "Landable": True, "MassEM": 0.1, "Radius": 1000.0,
            "Materials": [{"Name": "iron", "Percent": 20.0}]}


def test_bio_planet_scan_reaches_predict_system_end_to_end(tmp_path):
    e = _engine(tmp_path)
    e.process(_loc("Sol", 1))
    e.process({"event": "FSSBodySignals", "timestamp": "2026-11-06T10:02:00Z", "BodyName": "Sol 1", "BodyID": 1,
               "SystemAddress": 1, "Signals": [{"Type": "$SAA_SignalType_Biological;", "Count": 2}]})
    e.process(_bio_planet_scan())
    root = Path(__file__).resolve().parent.parent / "settings"
    out = predict_system(e.state, load_rules(root / "exo_habitat.json"),
                         ExoValueTable.load_from_paths(root / "exo_values.json"), {})
    assert "Aleoida" in out["Sol 1"].possible and out["Sol 1"].up_to > 0


def test_scan_keeps_engine_facts_and_handler_keys(tmp_path):
    e = _engine(tmp_path)
    e.process(_loc("Sol", 1))
    e.process(_bio_planet_scan())
    rec = e.state.bodies["Sol 1"]
    assert rec["SurfaceGravity"] == 1.0 and rec["SurfaceTemperature"] == 177.0 and rec["SurfacePressure"] == 2000.0
    assert rec["AtmosphereType"] == "CarbonDioxide" and rec["OrbitalPeriod"] == 80000.0
    assert rec["AtmosphereComposition"] == [{"Name": "CarbonDioxide", "Percent": 99.0}]
    assert rec["Materials"] == {"iron": 20.0} and rec["DistanceLS"] == 5.0 and rec["Landable"] is True
