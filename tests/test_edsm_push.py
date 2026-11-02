import json
import logging
from datetime import datetime

import requests

from edc.core import edsm_push as ep
from edc.core.edsm_push import EdsmPusher, check_key, should_send, with_transient

GAME = ("4.0", "r1")


class _Resp:
    def __init__(self, body=None, status=200, headers=None):
        self.body = body if body is not None else {"msgnum": 100}
        self.status_code, self.headers = status, headers or {}

    def json(self):
        return self.body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("boom secret-k")


def _make(monkeypatch, replies=None, discards=("Music",)):
    posts, status = [], []
    monkeypatch.setattr(ep, "_now", lambda: datetime(2026, 11, 2, 18, 6))
    queued = list(replies or [])
    monkeypatch.setattr(ep.requests, "get", lambda url, **kw: _Resp(list(discards)))
    monkeypatch.setattr(ep.requests, "post",
                        lambda url, **kw: posts.append(kw["data"]) or (queued.pop(0) if queued else _Resp()))
    p = EdsmPusher("B0B", "secret-k", "EDChronicle", "1.0", status.append)
    assert p._fetch_discards()
    return p, posts, status


def _names(post):
    return [e["event"] for e in json.loads(post["message"])]


def test_should_send_docked_always(): assert should_send([{"event": "Docked"}], "Docked", False)
def test_should_send_skips_moduleBuy_alone(): assert not should_send([{"event": "ModuleBuy"}], "ModuleBuy", False)
def test_should_send_cargo_after_newgame_docked(): assert not should_send([{"event": "Cargo"}], "Cargo", True)
def test_should_send_shutdown(): assert should_send([{"event": "ModuleBuy"}], "Shutdown", False)


def test_transient_fields():
    evt = {"event": "FSDJump"}
    out = with_transient(evt, "Sol", (0, 0, 0), None, 3)
    assert out["_systemName"] == "Sol" and out["_systemCoordinates"] == (0, 0, 0)
    assert out["_stationName"] is None and out["_shipId"] == 3
    assert evt == {"event": "FSDJump"}


def test_discarded_event_not_sent(monkeypatch):
    p, posts, _ = _make(monkeypatch)
    p._handle({"event": "Music"}, GAME)
    p._handle({"event": "FSDJump"}, GAME)
    assert _names(posts[0]) == ["FSDJump"]


def test_batch_posts_form_fields(monkeypatch):
    p, posts, status = _make(monkeypatch)
    p._handle({"event": "FSDJump"}, GAME)
    assert set(posts[0]) == {"commanderName", "apiKey", "fromSoftware", "fromSoftwareVersion",
                             "fromGameVersion", "fromGameBuild", "message"}
    assert isinstance(json.loads(posts[0]["message"]), list)
    assert status[-1] == "18:06 EDSM: sent 1 events"


def test_msgnum_5xx_clears_pending(monkeypatch):
    p, posts, _ = _make(monkeypatch, [_Resp({"msgnum": 500})])
    p._handle({"event": "FSDJump"}, GAME)
    p._handle({"event": "Scan"}, GAME)
    assert _names(posts[1]) == ["Scan"]


def test_msgnum_2xx_drops(monkeypatch):
    p, posts, status = _make(monkeypatch, [_Resp({"msgnum": 201})])
    p._handle({"event": "FSDJump"}, GAME)
    p._handle({"event": "Scan"}, GAME)
    assert _names(posts[1]) == ["Scan"]
    assert status[0] == "EDSM: refused (201)"


def test_429_waits_then_retries(monkeypatch):
    p, posts, _ = _make(monkeypatch, [_Resp(status=429, headers={"X-Rate-Limit-Reset": "1005"})])
    waits = []
    monkeypatch.setattr(ep, "_clock", lambda: 1000)
    monkeypatch.setattr(p._stop, "wait", lambda t: waits.append(t))
    p._handle({"event": "FSDJump"}, GAME)
    assert waits == [5] and len(posts) == 2 and p._pending == []


def test_docked_tracking_suppresses_cargo(monkeypatch):
    p, posts, _ = _make(monkeypatch)
    p._handle({"event": "LoadGame", "Docked": True}, GAME)
    n = len(posts)
    p._handle({"event": "Cargo"}, GAME)
    assert len(posts) == n


def test_stop_flushes_pending_once(monkeypatch):
    p, posts, _ = _make(monkeypatch, [_Resp(status=500)] * 3)
    p._handle({"event": "FSDJump"}, GAME)
    p._stop.set()
    p._worker_loop()
    assert len(posts) == 4 and _names(posts[3]) == ["FSDJump"]


def test_check_key(monkeypatch):
    monkeypatch.setattr(ep.requests, "post", lambda url, **kw: _Resp({"msgnum": 100}))
    assert check_key("B0B", "k")
    monkeypatch.setattr(ep.requests, "post", lambda url, **kw: _Resp({"msgnum": 203}))
    assert not check_key("B0B", "k")


def test_check_key_sends_software_version(monkeypatch):
    sent = {}
    monkeypatch.setattr(ep.requests, "post", lambda url, **kw: sent.update(kw["data"]) or _Resp({"msgnum": 100}))
    check_key("B0B", "k")
    assert sent["fromSoftwareVersion"] == ep.APP_VERSION   # EDSM 204 without it


def test_key_never_logged(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    p, _, status = _make(monkeypatch, [_Resp(status=500)] * 3 + [_Resp({"msgnum": 201})])
    p._handle({"event": "FSDJump"}, GAME)
    p._handle({"event": "Scan"}, GAME)

    def boom(url, **kw):
        raise requests.ConnectionError("secret-k")
    monkeypatch.setattr(ep.requests, "post", boom)
    p._handle({"event": "Scan"}, GAME)
    check_key("B0B", "secret-k")
    assert "secret-k" not in caplog.text and not any("secret-k" in s for s in status)


def test_stop_without_wait_returns_while_request_blocked(monkeypatch):
    import threading
    import time
    entered, release = threading.Event(), threading.Event()
    monkeypatch.setattr(ep.requests, "get", lambda url, **kw: entered.set() or release.wait(10) and _Resp([]))
    p = EdsmPusher("B0B", "k", "EDChronicle", "1.0", lambda msg: None)
    p.start()
    assert entered.wait(5)
    t0 = time.monotonic()
    p.stop(wait=False)
    assert time.monotonic() - t0 < 0.5
    release.set()
