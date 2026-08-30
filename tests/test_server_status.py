"""fetch_server_status() parses Frontier's official server-status endpoint."""
from unittest.mock import patch

from edc.core.server_status import fetch_server_status


def _resp(json_data, status_code=200):
    class _Resp:
        def raise_for_status(self):
            if status_code >= 400:
                raise Exception(f"HTTP {status_code}")
        def json(self):
            return json_data
    return _Resp()


def test_good_status_parses():
    with patch("edc.core.server_status.requests.get", return_value=_resp({"status": "Good", "message": ""})):
        status, message = fetch_server_status()
    assert status == "Good"
    assert message == ""


def test_bad_status_with_message_parses():
    with patch("edc.core.server_status.requests.get", return_value=_resp({"status": "Bad", "message": "Servers down for maintenance"})):
        status, message = fetch_server_status()
    assert status == "Bad"
    assert message == "Servers down for maintenance"


def test_network_error_returns_none_none():
    with patch("edc.core.server_status.requests.get", side_effect=Exception("timeout")):
        status, message = fetch_server_status()
    assert status is None
    assert message is None


def test_unexpected_response_shape_returns_none_none():
    with patch("edc.core.server_status.requests.get", return_value=_resp(["not", "a", "dict"])):
        status, message = fetch_server_status()
    assert status is None
    assert message is None
