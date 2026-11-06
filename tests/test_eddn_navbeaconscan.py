"""navbeaconscan/1: the event only has SystemAddress and NumBodies; name and position
are added from the tracked system, only when the address matches."""
from edc.core.eddn_publisher import EddnPublisher

EVT = {"timestamp": "2026-10-23T16:36:38Z", "event": "NavBeaconScan", "SystemAddress": 164098653, "NumBodies": 15}


def _pub():
    pub = EddnPublisher()
    pub.observe({"event": "LoadGame", "Commander": "CMDR", "Horizons": True, "Odyssey": True,
                 "gameversion": "4.4", "build": "r1"})
    return pub


def test_message_matches_the_schema_exactly():
    pub = _pub()
    pub.maybe_publish_navbeaconscan(EVT, "Sol", (1.0, 2.0, 3.0), 164098653)
    payload = pub._queue.get_nowait()
    assert payload["$schemaRef"] == "https://eddn.edcd.io/schemas/navbeaconscan/1"
    assert payload["message"] == {"timestamp": EVT["timestamp"], "event": "NavBeaconScan", "StarSystem": "Sol",
                                  "StarPos": [1.0, 2.0, 3.0], "SystemAddress": 164098653, "NumBodies": 15,
                                  "horizons": True, "odyssey": True}


def test_other_system_or_missing_data_is_not_sent():
    for args in (("Sol", (1.0, 2.0, 3.0), 999),            # tracked system differs: failed cross-check
                 ("", (1.0, 2.0, 3.0), 164098653),
                 ("Sol", (None, None, None), 164098653),
                 ("Sol", None, 164098653)):
        pub = _pub()
        pub.maybe_publish_navbeaconscan(EVT, *args)
        assert pub._queue.empty()


def test_no_body_count_is_not_sent():
    pub = _pub()
    pub.maybe_publish_navbeaconscan({**EVT, "NumBodies": None}, "Sol", (1.0, 2.0, 3.0), 164098653)
    assert pub._queue.empty()


def test_beta_is_not_sent():
    pub = _pub()
    pub.observe({"event": "Fileheader", "gameversion": "4.4 beta", "build": "r1"})
    pub.maybe_publish_navbeaconscan(EVT, "Sol", (1.0, 2.0, 3.0), 164098653)
    assert pub._queue.empty()
