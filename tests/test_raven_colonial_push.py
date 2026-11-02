import logging
from datetime import datetime

import pytest
import requests

from edc.core import raven_colonial_push as rc
from edc.core.raven_colonial_push import (
    RavenColonialPusher, commodity_key, contribution_payload, needs_payload,
)

DEPOT = {"timestamp": "2026-11-01T18:06:00Z", "event": "ColonisationConstructionDepot", "MarketID": 4224896003,
         "ResourcesRequired": [{"Name": "$aluminium_name;", "RequiredAmount": 40536, "ProvidedAmount": 40000},
                               {"Name": "$steel_name;", "RequiredAmount": 100, "ProvidedAmount": 100}]}
CONTRIB = {"timestamp": "2026-11-01T18:01:37Z", "event": "ColonisationContribution", "MarketID": 4224896003,
           "Contributions": [{"Name": "$Aluminium_name;", "Amount": 71}, {"Name": "$Steel_name;", "Amount": 1147}]}


class _Resp:
    status_code = 200


@pytest.fixture
def env(monkeypatch):
    posts, status = [], []
    monkeypatch.setattr(rc, "get_project_for_station",
                        lambda sa, mid: {"buildId": "b-1", "commodities": {"aluminium": 999, "steel": 0}})
    monkeypatch.setattr(rc.requests, "post", lambda url, **kw: posts.append((url, kw)) or _Resp())
    monkeypatch.setattr(rc, "_now", lambda: datetime(2026, 11, 2, 18, 6))
    p = RavenColonialPusher("secret-k", "B0B R0GERS", status.append)
    return p, posts, status


def test_commodity_key_mixed_case():
    assert commodity_key("$Aluminium_name;") == "aluminium"


def test_needs_payload_shape():
    p = needs_payload(DEPOT, "b-1")
    assert p["commodities"] == {"aluminium": 536, "steel": 0}
    assert p["maxNeed"] == 40636 and p["buildId"] == "b-1"
    assert p["colonisationConstructionDepot"]["timestamp"] == DEPOT["timestamp"]
    assert p["colonisationConstructionDepot"]["event"] == "ColonisationConstructionDepot"


def test_contribution_payload():
    assert contribution_payload(CONTRIB) == {"aluminium": 71, "steel": 1147}


def test_needs_sent_only_when_changed(env):
    p, posts, _ = env
    for _ in range(3):
        p._handle(DEPOT, 1)
    assert [u for u, _ in posts] == [f"{rc._BASE_URL}/api/project/b-1"]


def test_contribution_posts_under_cmdr(env):
    p, posts, _ = env
    p._handle(CONTRIB, 1)
    url, kw = posts[0]
    assert url.endswith("/contribute/B0B%20R0GERS") and kw["json"] == {"aluminium": 71, "steel": 1147}


def test_unknown_build_skips_and_reports(env, monkeypatch):
    p, posts, status = env
    monkeypatch.setattr(rc, "get_project_for_station", lambda sa, mid: None)
    p._handle(DEPOT, 1)
    assert posts == [] and "Build not on Raven Colonial" in status


def test_missing_build_lookup_retried_after_ttl(env, monkeypatch):
    p, posts, status = env
    now, lookups = [1000.0], []
    proj = {"buildId": "b-1", "commodities": {"aluminium": 999, "steel": 0}}

    def lookup(sa, mid):
        lookups.append(1)
        return None if len(lookups) == 1 else proj
    monkeypatch.setattr(rc, "get_project_for_station", lookup)
    monkeypatch.setattr(rc, "_clock", lambda: now[0])
    p._handle(DEPOT, 1)
    assert posts == [] and status == ["Build not on Raven Colonial"]
    now[0] += 599
    p._handle(DEPOT, 1)
    assert len(lookups) == 1 and posts == []
    now[0] += 2
    p._handle(DEPOT, 1)
    assert len(lookups) == 2 and len(posts) == 1


def test_contribution_ignores_miss_cache(env, monkeypatch):
    p, posts, status = env
    lookups = []
    proj = {"buildId": "b-1", "commodities": {}}

    def lookup(sa, mid):
        lookups.append(1)
        return None if len(lookups) == 1 else proj
    monkeypatch.setattr(rc, "get_project_for_station", lookup)
    monkeypatch.setattr(rc, "_clock", lambda: 1000.0)
    p._handle(DEPOT, 1)
    p._handle(CONTRIB, 1)
    assert len(lookups) == 2 and posts[0][0].endswith("/contribute/B0B%20R0GERS")


def test_failed_contribution_retried_once(env, monkeypatch):
    p, _, status = env
    calls = []

    def boom(url, **kw):
        calls.append(url)
        raise requests.ConnectionError("down")
    monkeypatch.setattr(rc.requests, "post", boom)
    p._handle(CONTRIB, 1)
    while not p._queue.empty():
        p._handle(*p._queue.get_nowait())
    assert len(calls) == 2 and status[-1] == "Raven Colonial: send failed"


def test_success_status(env):
    p, _, status = env
    p._handle(CONTRIB, 1)
    assert status[-1] == "18:06 Delivered 1218 units (2 commodities)"
    p._handle(DEPOT, 1)
    assert status[-1] == "18:06 Build progress sent"


def _key_resp(monkeypatch, status=200, body=None, record=None):
    class R:
        status_code = status

        def json(self):
            if body is None:
                raise ValueError("no json")
            return body

    def get(url, **kw):
        if record is not None:
            record.append(kw)
        return R()
    monkeypatch.setattr(rc.requests, "get", get)


def test_check_key_returns_display_name(monkeypatch):
    _key_resp(monkeypatch, body={"displayName": "B0B R0GERS"})
    assert rc.check_key("k") == "B0B R0GERS"


def test_check_key_non_200_is_none(monkeypatch):
    _key_resp(monkeypatch, status=401, body={"displayName": "x"})
    assert rc.check_key("k") is None


@pytest.mark.parametrize("body", [{}, {"displayName": ""}, ["x"], None])
def test_check_key_bad_body_is_none(monkeypatch, body):
    _key_resp(monkeypatch, body=body)
    assert rc.check_key("k") is None


def test_check_key_sends_rcc_key(monkeypatch):
    sent = []
    _key_resp(monkeypatch, body={"displayName": "n"}, record=sent)
    rc.check_key("secret-k")
    assert sent[0]["headers"]["rcc-key"] == "secret-k"


def test_check_key_never_logged(monkeypatch, caplog):
    def boom(url, **kw):
        raise requests.ConnectionError(f"rcc-key={kw['headers']['rcc-key']}")
    monkeypatch.setattr(rc.requests, "get", boom)
    with caplog.at_level(logging.DEBUG):
        assert rc.check_key("secret-k") is None
    assert "secret-k" not in caplog.text


def test_post_failure_is_logged_not_raised(env, monkeypatch):
    p, _, status = env

    def boom(url, **kw):
        raise requests.ConnectionError("down")
    monkeypatch.setattr(rc.requests, "post", boom)
    p._handle(CONTRIB, 1)
    assert "Raven Colonial: send failed" in status


def test_key_never_logged(env, monkeypatch, caplog):
    p, _, status = env

    def boom(url, **kw):
        raise requests.ConnectionError(f"bad header rcc-key={kw['headers']['rcc-key']}")
    monkeypatch.setattr(rc.requests, "post", boom)
    with caplog.at_level(logging.DEBUG):
        p._handle(CONTRIB, 1)
    assert "secret-k" not in caplog.text and "secret-k" not in " ".join(status)


def test_writes_send_rcc_key_header(env):
    p, posts, _ = env
    p._handle(DEPOT, 1)
    p._handle(CONTRIB, 1)
    assert [kw["headers"]["rcc-key"] for _, kw in posts] == ["secret-k", "secret-k"]


def test_stop_without_wait_returns_while_request_blocked(monkeypatch):
    import threading
    import time
    entered, release = threading.Event(), threading.Event()
    monkeypatch.setattr(rc, "get_project_for_station",
                        lambda sa, mid: entered.set() or release.wait(10) and None)
    p = RavenColonialPusher("k", "B0B R0GERS", lambda msg: None)
    p.start()
    p.submit(DEPOT, 1)
    assert entered.wait(5)
    t0 = time.monotonic()
    p.stop(wait=False)
    assert time.monotonic() - t0 < 0.5
    release.set()
