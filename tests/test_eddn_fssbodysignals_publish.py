"""Tests for build_fssbodysignals_message() and
EddnPublisher.maybe_publish_fssbodysignals() -- transforms a real
FSSBodySignals event (the event Surface Mining's "Planetary Mining
Location" signal actually arrives on, Update 4.4) into an EDDN
fssbodysignals/1-compliant message body. Schema requirements (exact
required fields, additionalProperties: false) verified directly against
EDCD/EDDN's schema repo. Real journal data from system HR 8769."""
from edc.core.eddn_publisher import (
    build_fssbodysignals_message, EddnPublisher, _FSSBODYSIGNALS_SCHEMA_REF,
)

_STAR_POS = (10.0, 20.0, 30.0)


def _event(**overrides):
    evt = {
        "timestamp": "2026-09-02T15:04:28Z",
        "event": "FSSBodySignals",
        "BodyName": "HR 8769 A 1",
        "BodyID": 5,
        "SystemAddress": 1281804437875,
        "Signals": [
            {"Type": "$PlanetaryMiningLocation_Name;", "Type_Localised": "Planetary Mining Location", "Count": 6},
            {"Type": "$SAA_SignalType_Geological;", "Type_Localised": "Geological", "Count": 3},
        ],
    }
    evt.update(overrides)
    return evt


def test_valid_event_produces_compliant_message():
    msg = build_fssbodysignals_message(_event(), "HR 8769", _STAR_POS, 1281804437875)
    assert msg == {
        "timestamp": "2026-09-02T15:04:28Z",
        "event": "FSSBodySignals",
        "StarSystem": "HR 8769",
        "StarPos": [10.0, 20.0, 30.0],
        "SystemAddress": 1281804437875,
        "BodyID": 5,
        "BodyName": "HR 8769 A 1",
        "Signals": [
            {"Type": "$PlanetaryMiningLocation_Name;", "Count": 6},
            {"Type": "$SAA_SignalType_Geological;", "Count": 3},
        ],
    }


def test_type_localised_dropped_from_signals():
    msg = build_fssbodysignals_message(_event(), "HR 8769", _STAR_POS, 1281804437875)
    for sig in msg["Signals"]:
        assert "Type_Localised" not in sig


def test_non_fssbodysignals_event_returns_none():
    assert build_fssbodysignals_message(
        {"event": "SAASignalsFound", "Signals": []}, "HR 8769", _STAR_POS, 1281804437875,
    ) is None


def test_missing_timestamp_returns_none():
    evt = _event()
    del evt["timestamp"]
    assert build_fssbodysignals_message(evt, "HR 8769", _STAR_POS, 1281804437875) is None


def test_missing_body_id_returns_none():
    evt = _event()
    del evt["BodyID"]
    assert build_fssbodysignals_message(evt, "HR 8769", _STAR_POS, 1281804437875) is None


def test_missing_star_system_returns_none():
    assert build_fssbodysignals_message(_event(), "", _STAR_POS, 1281804437875) is None


def test_missing_star_pos_returns_none():
    assert build_fssbodysignals_message(_event(), "HR 8769", None, 1281804437875) is None


def test_missing_system_address_returns_none():
    assert build_fssbodysignals_message(_event(), "HR 8769", _STAR_POS, None) is None


def test_empty_signals_returns_none():
    assert build_fssbodysignals_message(
        _event(Signals=[]), "HR 8769", _STAR_POS, 1281804437875,
    ) is None


def test_maybe_publish_fssbodysignals_queues_compliant_envelope():
    pub = EddnPublisher()
    pub.observe({"event": "Commander", "Name": "CMDR Test"})
    pub.observe({
        "event": "LoadGame", "Commander": "CMDR Test", "gameversion": "4.0", "build": "r300000",
        "Horizons": False, "Odyssey": True,
    })

    pub.maybe_publish_fssbodysignals(_event(), "HR 8769", _STAR_POS, 1281804437875)

    payload = pub._queue.get_nowait()
    assert payload["$schemaRef"] == _FSSBODYSIGNALS_SCHEMA_REF
    assert payload["header"]["uploaderID"] == "CMDR Test"
    assert payload["message"]["StarSystem"] == "HR 8769"
    assert payload["message"]["Signals"][0]["Type"] == "$PlanetaryMiningLocation_Name;"
    assert payload["message"]["horizons"] is False
    assert payload["message"]["odyssey"] is True


def test_maybe_publish_fssbodysignals_skips_when_no_commander_known():
    pub = EddnPublisher()
    pub.maybe_publish_fssbodysignals(_event(), "HR 8769", _STAR_POS, 1281804437875)
    assert pub._queue.empty()


def test_maybe_publish_fssbodysignals_skips_beta_build():
    pub = EddnPublisher()
    pub.observe({"event": "Commander", "Name": "CMDR Test"})
    pub.observe({"event": "LoadGame", "Commander": "CMDR Test", "gameversion": "4.0 beta 1", "build": "r300000"})

    pub.maybe_publish_fssbodysignals(_event(), "HR 8769", _STAR_POS, 1281804437875)

    assert pub._queue.empty()
