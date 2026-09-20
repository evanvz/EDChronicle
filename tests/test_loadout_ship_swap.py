"""EventEngine's Loadout handler -- state.ship was only ever set from
Commander/LoadGame (both session-start-only), so swapping ships
mid-session left the header showing the old ship indefinitely despite
ShipyardSwap+Loadout both firing correctly with the new one. Confirmed
live: Imperial Cutter -> Krait Mk II via ShipyardSwap, header still said
Cutter. Loadout fires on every ship swap (and docking, and any module
change) and must keep state.ship/state.ship_id current."""
from edc.core.event_engine import EventEngine
from edc.core.state import GameState


def _engine(tmp_path):
    return EventEngine(GameState(), tmp_path)


def _loadout(ship, ship_id, modules=None):
    return {
        "timestamp": "2026-09-11T17:04:09Z", "event": "Loadout",
        "Ship": ship, "ShipID": ship_id, "Modules": modules or [],
    }


def test_loadout_updates_ship_and_ship_id(tmp_path):
    engine = _engine(tmp_path)
    engine.process(_loadout("cutter", 22))
    assert engine.state.ship == "cutter"
    assert engine.state.ship_id == 22


def test_loadout_updates_ship_on_swap(tmp_path):
    engine = _engine(tmp_path)
    engine.process(_loadout("cutter", 22))
    engine.process(_loadout("krait_mkii", 7))
    assert engine.state.ship == "krait_mkii"
    assert engine.state.ship_id == 7


def test_loadout_missing_ship_field_keeps_previous_value(tmp_path):
    engine = _engine(tmp_path)
    engine.process(_loadout("cutter", 22))
    engine.process({"event": "Loadout", "Modules": []})
    assert engine.state.ship == "cutter"
    assert engine.state.ship_id == 22


def test_loadout_sets_ship_has_dss_true_when_fitted(tmp_path):
    engine = _engine(tmp_path)
    engine.process(_loadout("asp_explorer", 1, modules=[
        {"Slot": "Slot08_Size1", "Item": "int_detailedsurfacescanner_tiny"},
    ]))
    assert engine.state.ship_has_dss is True


def test_loadout_sets_ship_has_dss_false_when_not_fitted(tmp_path):
    engine = _engine(tmp_path)
    engine.process(_loadout("cutter", 22, modules=[
        {"Slot": "MediumHardpoint1", "Item": "hpt_pulselaser_fixed_medium"},
    ]))
    assert engine.state.ship_has_dss is False


def test_ship_has_dss_is_none_before_any_loadout_event(tmp_path):
    engine = _engine(tmp_path)
    assert engine.state.ship_has_dss is None
