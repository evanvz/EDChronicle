"""SAASignalsFound logs a warning for any signal Type it doesn't classify
into one of the known buckets (biological/geological/human/thargoid/other/
mining) instead of silently dropping it. Real EventEngine, matching this
repo's convention (see test_codex_phenomena.py).

Surface Mining's "$PlanetaryMiningLocation_Name;" was the gap that
originally motivated this fix. It's a recognized bucket now (see
test_planetary_mining_location_signal.py), so a genuinely unknown type is
used here instead to keep exercising the catch-all."""
import logging

from edc.core.event_engine import EventEngine
from edc.core.state import GameState


def _engine(tmp_path):
    return EventEngine(GameState(), tmp_path)


def _saa_event(signals, body_name="Test Body 1"):
    return {
        "event": "SAASignalsFound",
        "BodyName": body_name,
        "SystemAddress": 1,
        "BodyID": 1,
        "Signals": signals,
    }


def test_unrecognized_type_logs_warning(tmp_path, caplog):
    engine = _engine(tmp_path)
    with caplog.at_level(logging.WARNING, logger="edc.event_engine"):
        engine.process(_saa_event([
            {"Type": "$SomeFutureSignalType_Name;", "Type_Localised": "Some Future Signal Type", "Count": 18},
        ]))
    assert any("Unrecognized SAASignalsFound signal type" in r.message for r in caplog.records)
    assert any("SomeFutureSignalType_Name" in r.message for r in caplog.records)


def test_known_type_does_not_log_warning(tmp_path, caplog):
    engine = _engine(tmp_path)
    with caplog.at_level(logging.WARNING, logger="edc.event_engine"):
        engine.process(_saa_event([
            {"Type": "$SAA_SignalType_Geological;", "Type_Localised": "Geological", "Count": 2},
        ]))
    assert caplog.records == []
    assert engine.state.geo_signals.get("Test Body 1") == 2


def test_mining_type_does_not_log_warning(tmp_path, caplog):
    engine = _engine(tmp_path)
    with caplog.at_level(logging.WARNING, logger="edc.event_engine"):
        engine.process(_saa_event([
            {"Type": "$PlanetaryMiningLocation_Name;", "Type_Localised": "Planetary Mining Location", "Count": 18},
        ]))
    assert caplog.records == []
    assert engine.state.surface_mining_signals.get("Test Body 1") == 18


def test_mixed_known_and_unknown_types_only_warns_for_unknown(tmp_path, caplog):
    engine = _engine(tmp_path)
    with caplog.at_level(logging.WARNING, logger="edc.event_engine"):
        engine.process(_saa_event([
            {"Type": "$SAA_SignalType_Geological;", "Type_Localised": "Geological", "Count": 2},
            {"Type": "$SomeFutureSignalType_Name;", "Type_Localised": "Some Future Signal Type", "Count": 18},
            {"Type": "$SAA_SignalType_Human;", "Type_Localised": "Human", "Count": 1},
        ]))
    assert len(caplog.records) == 1
    assert "SomeFutureSignalType_Name" in caplog.records[0].message
    assert engine.state.geo_signals.get("Test Body 1") == 2
    assert engine.state.human_signals.get("Test Body 1") == 1


def test_blank_type_does_not_warn(tmp_path, caplog):
    engine = _engine(tmp_path)
    with caplog.at_level(logging.WARNING, logger="edc.event_engine"):
        engine.process(_saa_event([{"Type": "", "Type_Localised": "", "Count": 1}]))
    assert caplog.records == []
