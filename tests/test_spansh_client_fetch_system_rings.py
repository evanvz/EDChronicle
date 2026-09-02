"""SpanshClient.fetch_system_rings() -- now also returns body_mining_signals
(body_name -> Planetary Mining Location signal count, Surface Mining
Update 4.4), read from the same bodies/search response's per-body
"signals" array that already carries ring hotspot data. One request
covers both rings and mining signals."""
from unittest.mock import patch

from edc.core.spansh_client import SpanshClient


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


def _sample_response():
    return {
        "results": [
            {
                "name": "HR 8769 A 1",
                "signals": [
                    {"count": 6, "name": "Mining"},
                    {"count": 3, "name": "Geological"},
                ],
                "rings": [],
            },
            {
                "name": "HR 8769 A 2 A Ring",
                "signals": [],
                "reserve_level": "Pristine",
                "rings": [
                    {"name": "HR 8769 A 2 A Ring", "type": "Metallic", "signals": [{"name": "Platinum", "count": 2}]},
                ],
            },
        ],
    }


def test_body_mining_signal_extracted():
    with patch("edc.core.spansh_client.requests.post", return_value=_FakeResponse(_sample_response())):
        rings, error, mining_signals = SpanshClient().fetch_system_rings(1281804437875)

    assert error == ""
    assert mining_signals == {"HR 8769 A 1": 6}
    assert len(rings) == 1
    assert rings[0]["ring_name"] == "HR 8769 A 2 A Ring"
    assert rings[0]["reserve_level"] == "Pristine"


def test_body_with_no_mining_signal_not_in_dict():
    data = {"results": [{"name": "Some Body", "signals": [{"count": 3, "name": "Geological"}], "rings": []}]}
    with patch("edc.core.spansh_client.requests.post", return_value=_FakeResponse(data)):
        rings, error, mining_signals = SpanshClient().fetch_system_rings(1)

    assert mining_signals == {}


def test_request_failure_returns_empty_mining_signals():
    import requests

    with patch("edc.core.spansh_client.requests.post", side_effect=requests.RequestException("boom")):
        rings, error, mining_signals = SpanshClient().fetch_system_rings(1)

    assert error == "boom"
    assert rings == []
    assert mining_signals == {}
