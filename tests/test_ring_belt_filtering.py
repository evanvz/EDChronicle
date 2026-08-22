"""A star/planet's Scan event Rings array lists asteroid Belts (e.g.
"...A Belt") alongside real scannable rings (e.g. "...A Ring") -- Belts
have no hotspots and can't be SAA-probed, so they don't belong in the
Exploration tab's "Rings in this system" list. Confirmed via real journal
data (a star's own Scan event carrying a Belt in its Rings array). Real
EventEngine, matching this repo's convention (see test_footfall_tracking.py)."""
from edc.core.event_engine import EventEngine
from edc.core.state import GameState


def _engine(tmp_path):
    return EventEngine(GameState(), tmp_path)


def test_belt_in_rings_array_is_not_tracked(tmp_path):
    engine = _engine(tmp_path)
    engine.process({
        "event": "Scan", "ScanType": "AutoScan",
        "BodyName": "ICZ OS-T b3-3", "BodyID": 0,
        "StarSystem": "ICZ OS-T b3-3", "SystemAddress": 7269097547193,
        "DistanceFromArrivalLS": 0.0, "StarType": "TTS",
        "Rings": [
            {"Name": "ICZ OS-T b3-3 A Belt", "RingClass": "eRingClass_Rocky",
             "MassMT": 8.3673e13, "InnerRad": 7.1423e8, "OuterRad": 1.7814e9},
        ],
        "WasDiscovered": True,
    })
    assert engine.state.rings == {}


def test_real_ring_in_rings_array_is_tracked(tmp_path):
    engine = _engine(tmp_path)
    engine.process({
        "event": "Scan", "ScanType": "Detailed",
        "BodyName": "HIP 110376 A 2", "BodyID": 5,
        "StarSystem": "HIP 110376", "SystemAddress": 1,
        "DistanceFromArrivalLS": 100.0, "PlanetClass": "Icy body",
        "Rings": [
            {"Name": "HIP 110376 A 2 B Ring", "RingClass": "eRingClass_Icy",
             "MassMT": 1.0e10, "InnerRad": 1.0e6, "OuterRad": 2.0e6},
        ],
        "WasDiscovered": True,
    })
    assert "HIP 110376 A 2 B Ring" in engine.state.rings
