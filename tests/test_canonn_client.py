"""Tests for CanonnClient.get_compres() -- response shape confirmed live
against the real endpoint during development: a flat JSON array of
{"system": ..., "interesting": ...} pairs, one per known RES/CNB site."""
from unittest.mock import patch

import requests

from edc.core.canonn_client import CanonnClient


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


def test_get_compres_groups_by_system():
    payload = [
        {"system": "Merope", "interesting": "Resource Extraction Site [High]"},
        {"system": "Merope", "interesting": "Resource Extraction Site [Hazardous]"},
        {"system": "Sol", "interesting": "Compromised Nav Beacon"},
    ]
    with patch("edc.core.canonn_client.requests.get", return_value=_FakeResponse(payload)):
        result, error = CanonnClient().get_compres(["Merope", "Sol"])
    assert error == ""
    assert result["Merope"] == ["Resource Extraction Site [High]", "Resource Extraction Site [Hazardous]"]
    assert result["Sol"] == ["Compromised Nav Beacon"]


def test_get_compres_empty_systems_list():
    result, error = CanonnClient().get_compres([])
    assert result == {}
    assert error != ""


def test_get_compres_no_data_for_queried_system():
    with patch("edc.core.canonn_client.requests.get", return_value=_FakeResponse([])):
        result, error = CanonnClient().get_compres(["Nowhere Special"])
    assert error == ""
    assert result == {}


def test_get_compres_network_failure():
    with patch("edc.core.canonn_client.requests.get", side_effect=requests.RequestException("network error")):
        result, error = CanonnClient().get_compres(["Sol"])
    assert result == {}
    assert error != ""


def test_get_compres_unexpected_shape_is_not_none():
    with patch("edc.core.canonn_client.requests.get", return_value=_FakeResponse({"not": "a list"})):
        result, error = CanonnClient().get_compres(["Sol"])
    assert result == {}
    assert error != ""
