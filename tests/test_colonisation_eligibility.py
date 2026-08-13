"""Tests for edc.core.colonisation_eligibility -- EDSM sphere-systems
response parsing, mocked (no live network call in the automated suite).
Real endpoint shape verified live during development: the queried center
system is always present at distance 0; an empty "information": {} object
is EDSM's own signal for "no known population"."""
from unittest.mock import patch

from edc.core.colonisation_eligibility import (
    find_nearby_colonisation_candidates,
    check_system_eligibility,
)


def _sphere_response(entries):
    """entries: list of (name, distance, populated: bool)."""
    out = []
    for name, distance, populated in entries:
        info = {"population": 1000, "allegiance": "Independent"} if populated else {}
        out.append({"distance": distance, "bodyCount": 5, "name": name, "information": info})
    return out


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")


def test_find_nearby_excludes_self_and_populated(mocker=None):
    payload = _sphere_response([
        ("Sol", 0, True),
        ("Empty One", 5.0, False),
        ("Populated Neighbor", 3.0, True),
        ("Empty Two", 10.0, False),
    ])
    with patch("edc.core.colonisation_eligibility.requests.get", return_value=_FakeResponse(payload)):
        result = find_nearby_colonisation_candidates("Sol", radius_ly=15.0)
    names = [r["name"] for r in result]
    assert "Sol" not in names
    assert "Populated Neighbor" not in names
    assert names == ["Empty One", "Empty Two"]  # closest first


def test_find_nearby_caps_at_20():
    payload = _sphere_response([(f"System {i}", float(i), False) for i in range(1, 26)])
    with patch("edc.core.colonisation_eligibility.requests.get", return_value=_FakeResponse(payload)):
        result = find_nearby_colonisation_candidates("Sol", radius_ly=25.0)
    assert len(result) == 20
    assert result[0]["name"] == "System 1"


def test_find_nearby_empty_result_on_no_candidates():
    payload = _sphere_response([("Sol", 0, True)])
    with patch("edc.core.colonisation_eligibility.requests.get", return_value=_FakeResponse(payload)):
        result = find_nearby_colonisation_candidates("Sol")
    assert result == []


def test_find_nearby_network_failure_returns_empty_list():
    with patch("edc.core.colonisation_eligibility.requests.get", side_effect=Exception("network error")):
        result = find_nearby_colonisation_candidates("Sol")
    assert result == []


def test_check_eligibility_candidate_already_populated():
    payload = _sphere_response([("Target System", 0, True)])
    with patch("edc.core.colonisation_eligibility.requests.get", return_value=_FakeResponse(payload)):
        result = check_system_eligibility("Target System")
    assert result["eligible"] is False
    assert "populated" in result["reason"].lower()


def test_check_eligibility_unpopulated_with_populated_neighbor():
    payload = _sphere_response([
        ("Target System", 0, False),
        ("Nearby Hub", 8.5, True),
        ("Far Hub", 14.0, True),
    ])
    with patch("edc.core.colonisation_eligibility.requests.get", return_value=_FakeResponse(payload)):
        result = check_system_eligibility("Target System")
    assert result["eligible"] is True
    assert result["nearest_populated_ly"] == 8.5


def test_check_eligibility_unpopulated_no_populated_neighbor():
    payload = _sphere_response([
        ("Target System", 0, False),
        ("Also Empty", 10.0, False),
    ])
    with patch("edc.core.colonisation_eligibility.requests.get", return_value=_FakeResponse(payload)):
        result = check_system_eligibility("Target System")
    assert result["eligible"] is False
    assert result["nearest_populated_ly"] is None


def test_check_eligibility_system_not_found():
    with patch("edc.core.colonisation_eligibility.requests.get", return_value=_FakeResponse([])):
        result = check_system_eligibility("Totally Made Up System Name")
    assert result["eligible"] is None
    assert "not found" in result["reason"].lower()


def test_check_eligibility_network_failure():
    with patch("edc.core.colonisation_eligibility.requests.get", side_effect=Exception("network error")):
        result = check_system_eligibility("Target System")
    assert result["eligible"] is None
