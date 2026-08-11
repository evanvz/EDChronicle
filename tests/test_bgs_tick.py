"""Tests for fetch_latest_tick() -- mocked HTTP only, no live network call."""
from unittest.mock import Mock, patch

from edc.core.bgs_tick import fetch_latest_tick


def _fake_response(status_code=200, json_value="2026-08-11T10:51:03+00:00"):
    resp = Mock()
    resp.status_code = status_code
    if status_code == 200:
        resp.raise_for_status = Mock()
    else:
        resp.raise_for_status = Mock(side_effect=Exception(f"status {status_code}"))
    resp.json = Mock(return_value=json_value)
    return resp


def test_fetch_latest_tick_returns_string_on_success():
    with patch("edc.core.bgs_tick.requests.get", return_value=_fake_response()):
        result = fetch_latest_tick()
    assert result == "2026-08-11T10:51:03+00:00"


def test_fetch_latest_tick_returns_none_on_non_200():
    with patch("edc.core.bgs_tick.requests.get", return_value=_fake_response(status_code=500)):
        result = fetch_latest_tick()
    assert result is None


def test_fetch_latest_tick_returns_none_on_malformed_body():
    with patch(
        "edc.core.bgs_tick.requests.get",
        return_value=_fake_response(json_value={"not": "a string"}),
    ):
        result = fetch_latest_tick()
    assert result is None


def test_fetch_latest_tick_returns_none_on_empty_string():
    with patch("edc.core.bgs_tick.requests.get", return_value=_fake_response(json_value="")):
        result = fetch_latest_tick()
    assert result is None


def test_fetch_latest_tick_returns_none_on_network_error():
    with patch("edc.core.bgs_tick.requests.get", side_effect=Exception("connection refused")):
        result = fetch_latest_tick()
    assert result is None
