"""FSSBodySignals logs a warning for any signal Type it doesn't classify
into one of the known buckets (biological/geological/human/guardian/
thargoid/other/mining) instead of silently dropping it. Real EventEngine,
matching this repo's convention (see test_saasignals_unrecognized_type.py).

Surface Mining's "$PlanetaryMiningLocation_Name;" was the gap that
originally motivated this fix -- confirmed live 2026-09-02, real journal
data from system HR 8769: it arrives on THIS event, not SAASignalsFound
as a pre-release leak had claimed. Now that it's a recognized bucket
(see test_planetary_mining_location_signal.py), a genuinely unknown type
is used here instead to keep exercising the catch-all."""
import logging

from edc.core.event_engine import EventEngine
from edc.core.state import GameState


def _engine(tmp_path):
    return EventEngine(GameState(), tmp_path)


def _fss_body_signals_event(signals, body_name="HR 8769 A 1"):
    return {
        "event": "FSSBodySignals",
        "BodyName": body_name,
        "SystemAddress": 1281804437875,
        "BodyID": 5,
        "Signals": signals,
    }


def test_unrecognized_type_logs_warning(tmp_path, caplog):
    engine = _engine(tmp_path)
    with caplog.at_level(logging.WARNING, logger="edc.event_engine"):
        engine.process(_fss_body_signals_event([
            {"Type": "$SomeFutureSignalType_Name;", "Type_Localised": "Some Future Signal Type", "Count": 2},
        ]))
    assert any("Unrecognized FSSBodySignals signal type" in r.message for r in caplog.records)
    assert any("SomeFutureSignalType_Name" in r.message for r in caplog.records)


def test_mining_signal_does_not_warn(tmp_path, caplog):
    """Exact real signal set from HR 8769 A 1, 2026-09-02 -- mining is a
    recognized bucket now, no warning expected."""
    engine = _engine(tmp_path)
    with caplog.at_level(logging.WARNING, logger="edc.event_engine"):
        engine.process(_fss_body_signals_event([
            {"Type": "$PlanetaryMiningLocation_Name;", "Type_Localised": "Planetary Mining Location", "Count": 6},
            {"Type": "$SAA_SignalType_Geological;", "Type_Localised": "Geological", "Count": 3},
        ]))
    assert caplog.records == []
    assert engine.state.surface_mining_signals.get("HR 8769 A 1") == 6
    assert engine.state.geo_signals.get("HR 8769 A 1") == 3


def test_known_type_does_not_log_warning(tmp_path, caplog):
    engine = _engine(tmp_path)
    with caplog.at_level(logging.WARNING, logger="edc.event_engine"):
        engine.process(_fss_body_signals_event([
            {"Type": "$SAA_SignalType_Biological;", "Type_Localised": "Biological", "Count": 4},
        ]))
    assert caplog.records == []
    assert engine.state.bio_signals.get("HR 8769 A 1") == 4


def test_blank_type_does_not_warn(tmp_path, caplog):
    engine = _engine(tmp_path)
    with caplog.at_level(logging.WARNING, logger="edc.event_engine"):
        engine.process(_fss_body_signals_event([{"Type": "", "Type_Localised": "", "Count": 1}]))
    assert caplog.records == []
