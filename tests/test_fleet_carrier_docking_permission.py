"""Tests for the CarrierDockingPermission handler in
edc/engine/handlers/fleet_carrier.py -- real EventEngine, matching this
repo's established convention (see test_footfall_tracking.py)."""
from edc.core.event_engine import EventEngine
from edc.core.state import GameState


def _engine(tmp_path):
    return EventEngine(GameState(), tmp_path)


def test_docking_permission_updates_own_carrier(tmp_path):
    engine = _engine(tmp_path)
    engine.state.carrier_owned_market_id = 3700005632

    engine.process({
        "event": "CarrierDockingPermission",
        "CarrierID": 3700005632,
        "DockingAccess": "squadron",
        "AllowNotorious": True,
    })

    assert engine.state.carrier_docking_access == "squadron"
    assert engine.state.carrier_allow_notorious is True


def test_docking_permission_for_other_carrier_is_ignored(tmp_path):
    engine = _engine(tmp_path)
    engine.state.carrier_owned_market_id = 3700005632
    engine.state.carrier_docking_access = "all"

    engine.process({
        "event": "CarrierDockingPermission",
        "CarrierID": 9999999999,
        "DockingAccess": "none",
        "AllowNotorious": False,
    })

    assert engine.state.carrier_docking_access == "all"


def test_docking_permission_for_squadron_carrier_updates_squadron_state_only(tmp_path):
    engine = _engine(tmp_path)
    engine.state.carrier_owned_market_id = 3700005632
    engine.state.carrier_docking_access = "all"
    engine.state.squadron_carrier = {"market_id": 1234567890, "docking_access": "friends"}

    engine.process({
        "event": "CarrierDockingPermission",
        "CarrierID": 1234567890,
        "DockingAccess": "squadronfriends",
        "AllowNotorious": True,
    })

    assert engine.state.squadron_carrier["docking_access"] == "squadronfriends"
    assert engine.state.squadron_carrier["allow_notorious"] is True
    assert engine.state.carrier_docking_access == "all"
