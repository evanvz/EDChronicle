"""EDDataHub's EDDN pass-through (eddn_relay_url) is read first; when it stays
silent the listener falls back to the EDDN relay directly and says which feed
it is on (feed_source), for the status bar."""
import json
import threading
import time
import zlib

import zmq
from PyQt6.QtCore import Qt

import edc.core.eddn_listener as eddn_listener
from edc.core.eddn_listener import EddnPowerPlayWorker


def _publisher(url, stop):
    ctx = zmq.Context.instance()
    pub = ctx.socket(zmq.PUB)
    pub.setsockopt(zmq.LINGER, 0)
    pub.bind(url)
    raw = zlib.compress(json.dumps({"$schemaRef": "x", "message": {"event": "Other"}}).encode())
    while not stop.is_set():
        pub.send(raw)
        time.sleep(0.05)
    pub.close()


def _run_until_source(worker, timeout=15):
    seen = []
    worker.feed_source.connect(lambda s: (seen.append(s), setattr(worker, "_stop", True)),
                               type=Qt.ConnectionType.DirectConnection)
    worker.tick_detector.save = lambda: None
    t = threading.Thread(target=worker.run, daemon=True)
    t.start()
    t.join(timeout)
    worker._stop = True
    return seen


def test_silent_hub_falls_back_to_eddn_direct(monkeypatch):
    stop = threading.Event()
    threading.Thread(target=_publisher, args=("tcp://127.0.0.1:59501", stop), daemon=True).start()
    monkeypatch.setattr(eddn_listener, "_RELAY_URL", "tcp://127.0.0.1:59501")
    monkeypatch.setattr(eddn_listener, "_HUB_SILENT_S", 0.5)
    monkeypatch.setattr(eddn_listener, "_RECV_TIMEOUT_MS", 200)
    monkeypatch.setattr(eddn_listener, "_RECONNECT_DELAY_S", 0)
    try:
        # nothing listens on 59502: the hub stays silent
        assert _run_until_source(EddnPowerPlayWorker(relay_url="tcp://127.0.0.1:59502", direct=True)) == ["direct"]
    finally:
        stop.set()


def test_live_hub_is_used(monkeypatch):
    stop = threading.Event()
    threading.Thread(target=_publisher, args=("tcp://127.0.0.1:59503", stop), daemon=True).start()
    monkeypatch.setattr(eddn_listener, "_RELAY_URL", "tcp://127.0.0.1:1")   # never reached
    monkeypatch.setattr(eddn_listener, "_RECV_TIMEOUT_MS", 200)
    try:
        assert _run_until_source(EddnPowerPlayWorker(relay_url="tcp://127.0.0.1:59503")) == ["hub"]
    finally:
        stop.set()


def test_silent_hub_never_goes_direct_when_direct_is_off(monkeypatch):
    stop = threading.Event()
    threading.Thread(target=_publisher, args=("tcp://127.0.0.1:59505", stop), daemon=True).start()
    monkeypatch.setattr(eddn_listener, "_RELAY_URL", "tcp://127.0.0.1:59505")   # would answer if tried
    monkeypatch.setattr(eddn_listener, "_HUB_SILENT_S", 0.3)
    monkeypatch.setattr(eddn_listener, "_RECV_TIMEOUT_MS", 100)
    monkeypatch.setattr(eddn_listener, "_RECONNECT_DELAY_S", 0)
    try:
        assert _run_until_source(EddnPowerPlayWorker(relay_url="tcp://127.0.0.1:59506"), timeout=3) == []
    finally:
        stop.set()


def test_no_hub_and_direct_off_does_not_listen():
    w = EddnPowerPlayWorker()
    done = []
    w.finished.connect(lambda: done.append(1), type=Qt.ConnectionType.DirectConnection)
    w.tick_detector.save = lambda: None
    t = threading.Thread(target=w.run, daemon=True)
    t.start()
    t.join(5)
    assert done == [1] and not t.is_alive()


def test_no_hub_and_direct_off_says_off():
    w = EddnPowerPlayWorker()
    seen = []
    w.feed_source.connect(seen.append, type=Qt.ConnectionType.DirectConnection)
    w.tick_detector.save = lambda: None
    w.run()
    assert seen == ["off"]
