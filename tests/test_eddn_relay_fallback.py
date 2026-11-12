"""EDDataHub's EDDN pass-through (eddn_relay_url) is the only feed: the listener
never connects to EDDN itself, and says what it is on (feed_source: hub,
hub_silent or off) for the status bar."""
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


def test_live_hub_is_used(monkeypatch):
    stop = threading.Event()
    threading.Thread(target=_publisher, args=("tcp://127.0.0.1:59503", stop), daemon=True).start()
    monkeypatch.setattr(eddn_listener, "_RECV_TIMEOUT_MS", 200)
    try:
        assert _run_until_source(EddnPowerPlayWorker(relay_url="tcp://127.0.0.1:59503")) == ["hub"]
    finally:
        stop.set()


def test_no_public_eddn_address_in_the_listener():
    """Evan/Artie: the app never listens to EDDN itself, only to EDDataHub's relay."""
    import inspect
    assert "tcp://eddn.edcd.io" not in inspect.getsource(eddn_listener)
    assert "direct" not in inspect.signature(EddnPowerPlayWorker.__init__).parameters


def test_silent_hub_says_hub_silent(monkeypatch):
    """2026-11-03: the hub went offline, the status bar kept "EDDN via EDDataHub"."""
    monkeypatch.setattr(eddn_listener, "_STALE_CONNECTION_TIMEOUT_S", 0.3)
    monkeypatch.setattr(eddn_listener, "_RECV_TIMEOUT_MS", 100)
    monkeypatch.setattr(eddn_listener, "_RECONNECT_DELAY_S", 0)
    # nothing listens on 59509: the hub stays silent
    assert _run_until_source(EddnPowerPlayWorker(relay_url="tcp://127.0.0.1:59509"), timeout=5) == ["hub_silent"]


def test_no_hub_does_not_listen():
    w = EddnPowerPlayWorker()
    done = []
    w.finished.connect(lambda: done.append(1), type=Qt.ConnectionType.DirectConnection)
    w.tick_detector.save = lambda: None
    t = threading.Thread(target=w.run, daemon=True)
    t.start()
    t.join(5)
    assert done == [1] and not t.is_alive()


def test_no_hub_says_off():
    w = EddnPowerPlayWorker()
    seen = []
    w.feed_source.connect(seen.append, type=Qt.ConnectionType.DirectConnection)
    w.tick_detector.save = lambda: None
    w.run()
    assert seen == ["off"]


def test_stop_ends_the_listener_quickly(monkeypatch):
    """2026-10-29 11:07: closing waited 2 s for the listener, then deleted its still-running
    QThread (Qt fatal). A 5 s recv timeout or the 5 s reconnect pause outlasted that wait."""
    for stale in (0, 300):   # 0: sits in the reconnect pause; 300: blocks in recv
        monkeypatch.setattr(eddn_listener, "_STALE_CONNECTION_TIMEOUT_S", stale)
        w = EddnPowerPlayWorker(relay_url="tcp://127.0.0.1:59508")   # nothing listens: silent
        w.tick_detector.save = lambda: None
        t = threading.Thread(target=w.run, daemon=True)
        t.start()
        time.sleep(0.5)
        stopped = time.monotonic()
        w.stop()
        t.join(5)
        assert not t.is_alive() and time.monotonic() - stopped < 1.5
