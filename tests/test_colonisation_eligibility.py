"""Tests for edc.core.colonisation_eligibility -- EDSM sphere-systems
response parsing, mocked (no live network call in the automated suite).
Real endpoint shape verified live during development: the queried center
system is always present at distance 0; an empty "information": {} object
is EDSM's own signal for "no known population"."""
import pytest
from unittest.mock import patch

from edc.core.colonisation_eligibility import (
    find_nearby_colonisation_candidates,
    check_system_eligibility,
    _query_sphere,
)


@pytest.fixture(autouse=True)
def _no_spansh_claims():
    """Every test in this file exercises EDSM behavior; default Spansh to
    "no data" (fail-open, keeps candidates) unless a test overrides it."""
    with patch("edc.core.colonisation_eligibility.requests.post", return_value=_FakeResponse({"results": []})):
        yield


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
    names = [r["name"] for r in result["candidates"]]
    assert "Sol" not in names
    assert "Populated Neighbor" not in names
    assert names == ["Empty One", "Empty Two"]  # closest first
    assert result["center_populated"] is True  # Sol is populated -> candidates are verified
    assert result["lookup_failed"] is False


def test_find_nearby_center_unpopulated_flags_unverified():
    payload = _sphere_response([
        ("Frontier System", 0, False),
        ("Empty One", 5.0, False),
    ])
    with patch("edc.core.colonisation_eligibility.requests.get", return_value=_FakeResponse(payload)):
        result = find_nearby_colonisation_candidates("Frontier System", radius_ly=15.0)
    assert result["center_populated"] is False
    assert [c["name"] for c in result["candidates"]] == ["Empty One"]


def test_find_nearby_caps_at_20():
    payload = _sphere_response([(f"System {i}", float(i), False) for i in range(1, 26)])
    with patch("edc.core.colonisation_eligibility.requests.get", return_value=_FakeResponse(payload)):
        result = find_nearby_colonisation_candidates("Sol", radius_ly=25.0)
    assert len(result["candidates"]) == 20
    assert result["candidates"][0]["name"] == "System 1"


def test_find_nearby_empty_result_on_no_candidates():
    payload = _sphere_response([("Sol", 0, True)])
    with patch("edc.core.colonisation_eligibility.requests.get", return_value=_FakeResponse(payload)):
        result = find_nearby_colonisation_candidates("Sol")
    assert result["candidates"] == []
    assert result["center_populated"] is True
    assert result["lookup_failed"] is False


def test_find_nearby_network_failure_reports_lookup_failed():
    with patch("edc.core.colonisation_eligibility.requests.get", side_effect=Exception("network error")):
        result = find_nearby_colonisation_candidates("Sol")
    assert result["candidates"] == []
    assert result["center_populated"] is None
    assert result["lookup_failed"] is True


def test_find_nearby_system_not_found_distinct_from_failure():
    with patch("edc.core.colonisation_eligibility.requests.get", return_value=_FakeResponse({})):
        result = find_nearby_colonisation_candidates("Totally Made Up System Name")
    assert result["candidates"] == []
    assert result["center_populated"] is None
    assert result["lookup_failed"] is False


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
    # EDSM's real "not found" response is a JSON object ({}), not a list.
    with patch("edc.core.colonisation_eligibility.requests.get", return_value=_FakeResponse({})):
        result = check_system_eligibility("Totally Made Up System Name")
    assert result["eligible"] is None
    assert "not found" in result["reason"].lower()


def test_check_eligibility_network_failure():
    with patch("edc.core.colonisation_eligibility.requests.get", side_effect=Exception("network error")):
        result = check_system_eligibility("Target System")
    assert result["eligible"] is None
    assert "unreachable" in result["reason"].lower()


def test_query_sphere_dict_response_is_not_found_not_none():
    with patch("edc.core.colonisation_eligibility.requests.get", return_value=_FakeResponse({})):
        result = _query_sphere("Totally Made Up System Name", 15.0)
    assert result == []  # distinct sentinel, not None


def test_query_sphere_exception_is_real_failure():
    with patch("edc.core.colonisation_eligibility.requests.get", side_effect=Exception("network error")):
        result = _query_sphere("Sol", 15.0)
    assert result is None


def test_find_nearby_includes_chained_expansion_from_own_colony():
    main_payload = _sphere_response([("Sol", 0, True), ("Empty One", 5.0, False)])
    colony_payload = _sphere_response([("My Colony", 0, True), ("Chain Candidate", 4.0, False)])

    def _fake_get(url, params=None, **kwargs):
        if params["systemName"] == "My Colony":
            return _FakeResponse(colony_payload)
        return _FakeResponse(main_payload)

    with patch("edc.core.colonisation_eligibility.requests.get", side_effect=_fake_get):
        result = find_nearby_colonisation_candidates("Sol", own_colony_names=["My Colony"])
    by_name = {c["name"]: c for c in result["candidates"]}
    assert "Chain Candidate" in by_name
    assert by_name["Chain Candidate"]["via"] == "My Colony"
    assert by_name["Empty One"]["via"] is None


def test_find_nearby_dedupes_keeping_shortest_distance():
    main_payload = _sphere_response([("Sol", 0, True), ("Shared", 6.0, False)])
    colony_payload = _sphere_response([("My Colony", 0, True), ("Shared", 3.0, False)])

    def _fake_get(url, params=None, **kwargs):
        if params["systemName"] == "My Colony":
            return _FakeResponse(colony_payload)
        return _FakeResponse(main_payload)

    with patch("edc.core.colonisation_eligibility.requests.get", side_effect=_fake_get):
        result = find_nearby_colonisation_candidates("Sol", own_colony_names=["My Colony"])
    shared = next(c for c in result["candidates"] if c["name"] == "Shared")
    assert shared["distance_ly"] == 3.0
    assert shared["via"] == "My Colony"


def test_find_nearby_drops_candidate_spansh_says_already_claimed():
    payload = _sphere_response([("Sol", 0, True), ("Claimed Elsewhere", 5.0, False), ("Still Free", 6.0, False)])

    def _fake_post(url, json=None, **kwargs):
        name = json["filters"]["name"]["value"]
        claimed = name == "Claimed Elsewhere"
        return _FakeResponse({"results": [{"is_colonised": claimed, "is_being_colonised": False}]})

    with patch("edc.core.colonisation_eligibility.requests.get", return_value=_FakeResponse(payload)), \
         patch("edc.core.colonisation_eligibility.requests.post", side_effect=_fake_post):
        result = find_nearby_colonisation_candidates("Sol")
    names = [c["name"] for c in result["candidates"]]
    assert "Claimed Elsewhere" not in names
    assert "Still Free" in names


def test_check_eligibility_no_populated_neighbor_but_within_chain_radius():
    payload = _sphere_response([("Target System", 0, False), ("Also Empty", 10.0, False)])
    colony_payload = _sphere_response([("My Colony", 0, True), ("Target System", 7.0, False)])

    def _fake_get(url, params=None, **kwargs):
        if params["systemName"] == "My Colony":
            return _FakeResponse(colony_payload)
        return _FakeResponse(payload)

    with patch("edc.core.colonisation_eligibility.requests.get", side_effect=_fake_get):
        result = check_system_eligibility("Target System", own_colony_names=["My Colony"])
    assert result["eligible"] is True
    assert "My Colony" in result["reason"]
