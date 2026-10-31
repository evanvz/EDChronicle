"""Hub colonisation client: query building and None on any failure."""
import pytest
import requests

from edc.core import eddatahub_client as c


class Resp:
    def __init__(self, data, status=200):
        self.data, self.status = data, status

    def raise_for_status(self):
        if self.status >= 400:
            raise requests.HTTPError(str(self.status))

    def json(self):
        return self.data


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def fake(url, params=None, headers=None, timeout=None):
        seen.append((url, params, headers, timeout))
        return Resp([{"id64": 1}])
    monkeypatch.setattr(c.requests, "get", fake)
    return seen


def test_search_builds_params(calls):
    got = c.fetch_colonisation_search("http://hub/", 1.0, 2.0, 3.0, 20, ["Coriolis", "Outpost"], ["Agri"],
                                      "Elite United Worlds", 12.5, 50, min_planets=10)
    assert got == [{"id64": 1}]
    url, params, headers, timeout = calls[0]
    assert url == "http://hub/api/colonisation-search"
    assert params == {"x": 1.0, "y": 2.0, "z": 3.0, "radius": 20, "limit": 50, "min_planets": 10,
                      "port_type": ["Coriolis", "Outpost"], "economy": ["Agri"], "faction": "Elite United Worlds", "near_max": 12.5}
    assert headers == {"User-Agent": c.USER_AGENT} and timeout == c._TIMEOUT


def test_search_omits_empty_params(calls):
    c.fetch_colonisation_search("http://hub", 0, 0, 0, 10, [], [], None, None)
    assert set(calls[0][1]) == {"x", "y", "z", "radius", "limit", "min_planets"}


def test_search_timeout_is_none(monkeypatch):
    def boom(*a, **k):
        raise requests.Timeout()
    monkeypatch.setattr(c.requests, "get", boom)
    assert c.fetch_colonisation_search("http://hub", 0, 0, 0, 10, [], [], None, None) is None
    assert c.fetch_colonisation_system("http://hub", 1) is None


def test_search_non_list_is_none(monkeypatch):
    monkeypatch.setattr(c.requests, "get", lambda *a, **k: Resp({"error": "x"}))
    assert c.fetch_colonisation_search("http://hub", 0, 0, 0, 10, [], [], None, None) is None


def test_system_dict_and_shapes(monkeypatch):
    monkeypatch.setattr(c.requests, "get", lambda *a, **k: Resp({"id64": 1, "bodies": []}))
    assert c.fetch_colonisation_system("http://hub", 1) == {"id64": 1, "bodies": []}
    monkeypatch.setattr(c.requests, "get", lambda *a, **k: Resp([]))
    assert c.fetch_colonisation_system("http://hub", 1) is None
    monkeypatch.setattr(c.requests, "get", lambda *a, **k: Resp({}, 404))
    assert c.fetch_colonisation_system("http://hub", 1) is None


def test_system_sends_faction_only_when_set(calls):
    c.fetch_colonisation_system("http://hub", 1)
    c.fetch_colonisation_system("http://hub", 1, "Us")
    assert [p for _, p, _, _ in calls] == [{"id64": 1}, {"id64": 1, "faction": "Us"}]


def test_put_colonisation_mark_sends_json_and_reports_refusal(monkeypatch):
    seen, status = [], [202]

    def fake(url, json=None, headers=None, timeout=None):
        seen.append((url, json))
        return Resp({"ok": True}, status[0])
    monkeypatch.setattr(c.requests, "put", fake)
    assert c.put_colonisation_mark("http://hub/", 7, "bad", "S 3", "no moons", "Evan") is True
    assert seen == [("http://hub/api/colonisation-mark",
                     {"id64": 7, "verdict": "bad", "primary_body": "S 3", "note": "no moons", "cmdr": "Evan"})]
    status[0] = 404                                         # hub not updated yet
    assert c.put_colonisation_mark("http://hub", 7, None, None, None, None) is False
    assert c.put_colonisation_mark("", 7, "bad", None, None, None) is False
