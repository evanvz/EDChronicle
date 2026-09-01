"""SpanshClient.fetch_system_bodies() -- name-only lookup (no
system_address) must NOT send a "sort" clause or "comparison" on the name
filter. Confirmed live against the real API: either one makes Spansh
silently ignore the name filter entirely (falls back to a generic
nearest-to-Sol result, wrong system). The id64 path is unaffected and
keeps both -- confirmed working as-is."""
from unittest.mock import patch

from edc.core.spansh_client import SpanshClient


def _sample_response():
    return {
        "results": [{
            "bodies": [
                {"name": "Test System", "type": "Star", "subtype": "G (White-Yellow) Star", "distance_to_arrival": 0.0},
            ],
        }],
    }


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


def test_name_only_lookup_sends_bare_name_filter_no_sort():
    captured = {}

    def _fake_post(url, json=None, timeout=None):
        captured.update(json)
        return _FakeResponse(_sample_response())

    with patch("edc.core.spansh_client.requests.post", side_effect=_fake_post):
        bodies, error = SpanshClient().fetch_system_bodies("Test System")

    assert error == ""
    assert len(bodies) == 1
    assert captured["filters"] == {"name": {"value": "Test System"}}
    assert "sort" not in captured


def test_id64_lookup_keeps_comparison_and_sort():
    captured = {}

    def _fake_post(url, json=None, timeout=None):
        captured.update(json)
        return _FakeResponse(_sample_response())

    with patch("edc.core.spansh_client.requests.post", side_effect=_fake_post):
        bodies, error = SpanshClient().fetch_system_bodies("Test System", 12345)

    assert error == ""
    assert captured["filters"] == {"id64": {"value": 12345, "comparison": "="}}
    assert captured["sort"] == [{"distance": {"direction": "asc"}}]


def test_fetch_system_id64_resolves_and_uses_bare_name_filter():
    captured = {}

    def _fake_post(url, json=None, timeout=None):
        captured.update(json)
        return _FakeResponse({"results": [{"id64": 11667681191425}]})

    with patch("edc.core.spansh_client.requests.post", side_effect=_fake_post):
        id64, error = SpanshClient().fetch_system_id64("Test System")

    assert error == ""
    assert id64 == 11667681191425
    assert captured["filters"] == {"name": {"value": "Test System"}}
    assert "sort" not in captured


def test_fetch_system_id64_not_found():
    with patch("edc.core.spansh_client.requests.post", return_value=_FakeResponse({"results": []})):
        id64, error = SpanshClient().fetch_system_id64("Nowhere System")
    assert id64 is None
    assert error != ""
