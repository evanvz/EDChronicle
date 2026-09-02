"""Surface Mining's "Planetary Mining Location" signal (Update 4.4,
confirmed live 2026-09-02) is tracked the same way Guardian/Thargoid/
Other signals already are: state.surface_mining_signals[body] plus
rec["SurfaceMiningSignals"] on the body record, feeding the Exploration tab's
per-body card -- not persisted to the DB like was_mapped/was_footfalled,
matching the existing live-only tier those other signal types are in.
Real EventEngine, real journal data from system HR 8769."""
from edc.core.event_engine import EventEngine
from edc.core.state import GameState


def _engine(tmp_path):
    return EventEngine(GameState(), tmp_path)


def test_fssbodysignals_tracks_mining_count(tmp_path):
    engine = _engine(tmp_path)
    engine.process({
        "event": "FSSBodySignals",
        "BodyName": "HR 8769 A 1",
        "SystemAddress": 1281804437875,
        "BodyID": 5,
        "Signals": [
            {"Type": "$PlanetaryMiningLocation_Name;", "Type_Localised": "Planetary Mining Location", "Count": 6},
            {"Type": "$SAA_SignalType_Geological;", "Type_Localised": "Geological", "Count": 3},
        ],
    })
    assert engine.state.surface_mining_signals.get("HR 8769 A 1") == 6
    assert engine.state.bodies["HR 8769 A 1"]["SurfaceMiningSignals"] == 6
    # Geological in the same event still counted correctly alongside it.
    assert engine.state.geo_signals.get("HR 8769 A 1") == 3
    assert engine.state.bodies["HR 8769 A 1"]["GeoSignals"] == 3


def test_fssbodysignals_no_mining_signal_defaults_to_zero(tmp_path):
    engine = _engine(tmp_path)
    engine.process({
        "event": "FSSBodySignals",
        "BodyName": "Some Other Body",
        "SystemAddress": 1,
        "BodyID": 1,
        "Signals": [{"Type": "$SAA_SignalType_Geological;", "Type_Localised": "Geological", "Count": 1}],
    })
    assert engine.state.surface_mining_signals.get("Some Other Body") == 0
    assert engine.state.bodies["Some Other Body"]["SurfaceMiningSignals"] == 0


def test_saasignalsfound_tracks_mining_count(tmp_path):
    engine = _engine(tmp_path)
    engine.process({
        "event": "SAASignalsFound",
        "BodyName": "HR 8769 A 1",
        "SystemAddress": 1281804437875,
        "BodyID": 5,
        "Signals": [
            {"Type": "$PlanetaryMiningLocation_Name;", "Type_Localised": "Planetary Mining Location", "Count": 6},
        ],
        "Genuses": [],
    })
    assert engine.state.surface_mining_signals.get("HR 8769 A 1") == 6
    assert engine.state.bodies["HR 8769 A 1"]["SurfaceMiningSignals"] == 6
