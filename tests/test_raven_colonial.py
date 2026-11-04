"""edc.core.raven_colonial -- read-only Raven Colonial client. Never pushes
our data; only the two GET lookups this app needs are covered."""
from unittest.mock import MagicMock, patch

from edc.core import raven_colonial


def test_parse_build_id_from_bare_uuid():
    assert raven_colonial.parse_build_id("4e6a044c-e8a5-44e8-b93a-2484a7e2a894") == \
        "4e6a044c-e8a5-44e8-b93a-2484a7e2a894"


def test_parse_build_id_from_pasted_link():
    text = "https://ravencolonial.com/#build=4e6a044c-e8a5-44e8-b93a-2484a7e2a894"
    assert raven_colonial.parse_build_id(text) == "4e6a044c-e8a5-44e8-b93a-2484a7e2a894"


def test_parse_build_id_returns_none_for_garbage():
    assert raven_colonial.parse_build_id("not a build id") is None
    assert raven_colonial.parse_build_id("") is None


def test_get_project_returns_none_on_404():
    resp = MagicMock(status_code=404)
    with patch("edc.core.raven_colonial.requests.get", return_value=resp) as mocked:
        result = raven_colonial.get_project("missing-build-id")
    assert result is None
    mocked.assert_called_once()


def test_get_project_returns_json_on_success():
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"buildId": "abc", "buildName": "Test Port"}
    resp.raise_for_status.return_value = None
    with patch("edc.core.raven_colonial.requests.get", return_value=resp):
        result = raven_colonial.get_project("abc")
    assert result == {"buildId": "abc", "buildName": "Test Port"}


def test_get_project_returns_none_on_request_exception():
    with patch("edc.core.raven_colonial.requests.get", side_effect=Exception("boom")):
        result = raven_colonial.get_project("abc")
    assert result is None


def test_get_project_for_station_returns_none_on_404():
    resp = MagicMock(status_code=404)
    with patch("edc.core.raven_colonial.requests.get", return_value=resp) as mocked:
        result = raven_colonial.get_project_for_station(123, 456)
    assert result is None
    args, _ = mocked.call_args
    assert "123/456" in args[0]


def test_get_project_for_station_returns_json_on_success():
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"buildId": "abc"}
    resp.raise_for_status.return_value = None
    with patch("edc.core.raven_colonial.requests.get", return_value=resp):
        result = raven_colonial.get_project_for_station(123, 456)
    assert result == {"buildId": "abc"}


def _slots(payload, status=200):
    resp = MagicMock(status_code=status)
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    with patch("edc.core.raven_colonial.requests.get", return_value=resp) as mocked:
        return raven_colonial.get_system_slots("Sol A"), mocked


def test_raven_slots_by_body_name():
    got, mocked = _slots({"bodies": [{"num": 3, "name": "X 3"}], "slots": {"3": [1, 2]}})
    assert got == {"X 3": (1, 2)}
    args, kw = mocked.call_args
    assert args[0] == f"{raven_colonial._BASE_URL}/api/v2/system/Sol%20A"
    assert kw["timeout"] == raven_colonial._TIMEOUT and "User-Agent" in kw["headers"]


def test_raven_slots_minus_one_is_none():
    got, _ = _slots({"bodies": [{"num": 3, "name": "X 3"}], "slots": {"3": [3, -1]}})
    assert got == {"X 3": (3, None)}


def test_raven_slots_skip_unmatched_names():
    got, _ = _slots({"bodies": [{"num": 3, "name": "X 3"}], "slots": {"3": [1, 2], "9": [1, 1]}})
    assert got == {"X 3": (1, 2)}


def test_raven_slots_404_none():
    got, _ = _slots({}, 404)
    assert got is None
    with patch("edc.core.raven_colonial.requests.get", side_effect=Exception("boom")):
        assert raven_colonial.get_system_slots("X") is None
