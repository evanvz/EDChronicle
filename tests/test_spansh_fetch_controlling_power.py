"""spansh_client.fetch_controlling_power() -- live per-system fallback for
systems EDSM's PowerPlay dump has no data for at all (confirmed live: a
system under live enemy control had zero rows anywhere in the dump)."""
from unittest.mock import patch

from edc.core.spansh_client import fetch_controlling_power


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


def test_returns_controlling_power_from_first_result():
    payload = {"results": [{"name": "Arcadian", "controlling_power": "Zemina Torval"}]}
    with patch("edc.core.spansh_client.requests.post", return_value=_FakeResponse(payload)):
        assert fetch_controlling_power("Arcadian") == "Zemina Torval"


def test_sends_bare_name_filter():
    captured = {}

    def _fake_post(url, json=None, timeout=None):
        captured.update(json)
        return _FakeResponse({"results": []})

    with patch("edc.core.spansh_client.requests.post", side_effect=_fake_post):
        fetch_controlling_power("Arcadian")
    assert captured["filters"] == {"name": {"value": "Arcadian"}}


def test_no_results_returns_none():
    with patch("edc.core.spansh_client.requests.post", return_value=_FakeResponse({"results": []})):
        assert fetch_controlling_power("Nonexistent System") is None


def test_uncontrolled_system_returns_none():
    payload = {"results": [{"name": "Neutral System", "controlling_power": None}]}
    with patch("edc.core.spansh_client.requests.post", return_value=_FakeResponse(payload)):
        assert fetch_controlling_power("Neutral System") is None


def test_request_exception_returns_none():
    def _raise(*args, **kwargs):
        raise ConnectionError("no network")

    with patch("edc.core.spansh_client.requests.post", side_effect=_raise):
        assert fetch_controlling_power("Arcadian") is None
