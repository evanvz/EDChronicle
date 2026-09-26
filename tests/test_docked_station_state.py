"""EventEngine tracks the docked station's owning faction and type --
trade/data sales credit the station owner (not the system controller),
and fleet carriers carry no BGS weight at all."""
from edc.core.event_engine import EventEngine
from edc.core.state import GameState


def _engine(tmp_path):
    return EventEngine(GameState(), tmp_path)


def test_docked_sets_station_faction_and_type(tmp_path):
    engine = _engine(tmp_path)
    engine.process({"event": "Docked", "StationName": "Hahn Hub", "StationType": "Coriolis",
                    "StationFaction": {"Name": "Hungarian Wolves", "FactionState": "Boom"},
                    "StarSystem": "Ekono", "SystemAddress": 12345})
    assert engine.state.station_faction == "Hungarian Wolves"
    assert engine.state.station_type == "Coriolis"


def test_undocked_clears_station(tmp_path):
    engine = _engine(tmp_path)
    engine.process({"event": "Docked", "StationType": "Coriolis", "StationFaction": {"Name": "Hungarian Wolves"}})
    engine.process({"event": "Undocked", "StationName": "Hahn Hub"})
    assert engine.state.station_faction is None
    assert engine.state.station_type is None


def test_location_while_docked_sets_station(tmp_path):
    engine = _engine(tmp_path)
    engine.process({"event": "Location", "Docked": True, "StationType": "FleetCarrier",
                    "StationFaction": {"Name": "FleetCarrier"}, "StarSystem": "Ekono", "SystemAddress": 12345})
    assert engine.state.station_faction == "FleetCarrier"
    assert engine.state.station_type == "FleetCarrier"


def test_location_not_docked_clears_station(tmp_path):
    engine = _engine(tmp_path)
    engine.process({"event": "Docked", "StationType": "Coriolis", "StationFaction": {"Name": "Hungarian Wolves"}})
    engine.process({"event": "Location", "Docked": False, "StarSystem": "Ekono", "SystemAddress": 12345})
    assert engine.state.station_faction is None
