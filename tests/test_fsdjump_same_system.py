"""FSDJump can re-fire for the system the player is already in (e.g.
journal replay after a disconnect/reconnect). The handler must not wipe
resolved_body_ids in that case -- only on a genuine system change, matching
Location's existing guard. Real EventEngine, matching this repo's
convention (see test_footfall_tracking.py)."""
from edc.core.event_engine import EventEngine
from edc.core.state import GameState


def _engine(tmp_path):
    return EventEngine(GameState(), tmp_path)


def test_fsdjump_same_system_preserves_resolved_body_ids(tmp_path):
    engine = _engine(tmp_path)
    engine.state.system = "Cowini"
    engine.state.system_address = 123
    engine.state.resolved_body_ids = {1, 2, 3, 4, 5}

    engine.process({
        "event": "FSDJump",
        "StarSystem": "Cowini",
        "SystemAddress": 123,
        "BodyID": 1,
    })

    assert engine.state.resolved_body_ids == {1, 2, 3, 4, 5}


def test_fsdjump_new_system_clears_resolved_body_ids(tmp_path):
    engine = _engine(tmp_path)
    engine.state.system = "Cowini"
    engine.state.system_address = 123
    engine.state.resolved_body_ids = {1, 2, 3, 4, 5}

    engine.process({
        "event": "FSDJump",
        "StarSystem": "Deciat",
        "SystemAddress": 456,
        "BodyID": 9,
    })

    assert engine.state.resolved_body_ids == {9}
