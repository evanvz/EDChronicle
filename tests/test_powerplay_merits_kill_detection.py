"""PowerplayMerits with a large gain is treated as a PP-kill signal, but PP
commodity-trade delivery also grants large merit chunks -- confirmed live:
a dockside MarketSell of a PP trade good produced a 3960-merit gain,
miscounted as a phantom session kill. Kills can't happen while docked, so
is_docked must gate the heuristic. Real EventEngine, matching this repo's
convention (see test_footfall_tracking.py)."""
from edc.core.event_engine import EventEngine
from edc.core.state import GameState


def _engine(tmp_path):
    return EventEngine(GameState(), tmp_path)


def test_large_merit_gain_while_docked_is_not_counted_as_kill(tmp_path):
    engine = _engine(tmp_path)
    engine.process({"event": "Docked", "StationName": "Softley Landing"})

    engine.process({
        "event": "PowerplayMerits", "Power": "Aisling Duval",
        "MeritsGained": 3960, "TotalMerits": 1170762,
    })

    assert engine.state.session_kills == 0


def test_large_merit_gain_while_undocked_is_counted_as_kill(tmp_path):
    engine = _engine(tmp_path)
    engine.process({"event": "Undocked", "StationName": "Softley Landing"})

    engine.process({
        "event": "PowerplayMerits", "Power": "Aisling Duval",
        "MeritsGained": 3960, "TotalMerits": 1170762,
    })

    assert engine.state.session_kills == 1


def test_location_event_sets_docked_state(tmp_path):
    engine = _engine(tmp_path)
    engine.process({"event": "Location", "Docked": True, "StarSystem": "Kamitra"})
    assert engine.state.is_docked is True

    engine.process({"event": "Location", "Docked": False, "StarSystem": "Kamitra"})
    assert engine.state.is_docked is False
