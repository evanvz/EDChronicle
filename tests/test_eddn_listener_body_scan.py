"""EDDN's journal-v1.0 schema's event enum includes "Scan" and
"SAASignalsFound" alongside the 5 events our listener previously kept
(_RELEVANT_EVENTS). Confirmed live: Scan messages carrying real body
physical stats were arriving over EDDN's relay and being silently
dropped at the event-filter line before any handling ran. SAASignalsFound
stays dropped -- fssbodysignals/1 is the correct/complete source for
that data already. This covers the Scan gap: other commanders' live
body scans feed net.spansh_bodies, the same cache Spansh's own crawl
populates. Real EddnPowerPlayWorker._pump() driven by a fake socket,
matching this repo's convention (see test_eddn_listener_watchdog.py)."""
import json
import zlib

import zmq

from edc.core.eddn_listener import EddnPowerPlayWorker, _RELEVANT_EVENTS


def test_scan_is_relevant():
    assert "Scan" in _RELEVANT_EVENTS


def test_saasignalsfound_stays_dropped():
    # Not a regression to fix -- fssbodysignals/1 already covers this data.
    assert "SAASignalsFound" not in _RELEVANT_EVENTS


class _OneMessageThenTimesOutSocket:
    def __init__(self, payload):
        self._payload = payload
        self._sent = False

    def recv(self):
        if not self._sent:
            self._sent = True
            return zlib.compress(json.dumps(self._payload).encode("utf-8"))
        raise zmq.error.Again()


def _journal_payload(message):
    return {"$schemaRef": "https://eddn.edcd.io/schemas/journal/1", "message": message}


def test_planetary_scan_emits_body_scan_seen(monkeypatch):
    import edc.core.eddn_listener as eddn_listener
    monkeypatch.setattr(eddn_listener, "_STALE_CONNECTION_TIMEOUT_S", 0)

    msg = {
        "timestamp": "2026-09-02T15:04:29Z", "event": "Scan", "ScanType": "Detailed",
        "BodyName": "HR 8769 A 1", "BodyID": 5, "StarSystem": "HR 8769",
        "SystemAddress": 1281804437875, "PlanetClass": "High metal content body",
    }
    worker = EddnPowerPlayWorker()
    seen = []
    worker.body_scan_seen.connect(lambda m: seen.append(m))

    worker._pump(_OneMessageThenTimesOutSocket(_journal_payload(msg)))

    assert len(seen) == 1
    assert seen[0]["BodyName"] == "HR 8769 A 1"
    assert seen[0]["PlanetClass"] == "High metal content body"


def test_star_scan_does_not_emit_body_scan_seen(monkeypatch):
    import edc.core.eddn_listener as eddn_listener
    monkeypatch.setattr(eddn_listener, "_STALE_CONNECTION_TIMEOUT_S", 0)

    # Real star Scan events have StarType, not PlanetClass.
    msg = {
        "timestamp": "2026-09-02T15:04:29Z", "event": "Scan", "ScanType": "Detailed",
        "BodyName": "HR 8769 A", "BodyID": 2, "StarSystem": "HR 8769",
        "SystemAddress": 1281804437875, "StarType": "K",
    }
    worker = EddnPowerPlayWorker()
    seen = []
    worker.body_scan_seen.connect(lambda m: seen.append(m))

    worker._pump(_OneMessageThenTimesOutSocket(_journal_payload(msg)))

    assert seen == []
