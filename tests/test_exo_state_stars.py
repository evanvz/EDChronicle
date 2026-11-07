from edc.core.event_engine import EventEngine
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
