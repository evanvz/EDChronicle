"""fetch_latest_headlines() parses Frontier's official GalNet news feed."""
from unittest.mock import patch

from edc.core.galnet_news import fetch_latest_headlines


def _resp(json_data):
    class _Resp:
        def raise_for_status(self):
            pass
        def json(self):
            return json_data
    return _Resp()


def test_latest_headlines_parses():
    payload = {"data": [
        {"attributes": {
            "title": "Research Sheds New Light on Industrial Mining",
            "field_galnet_guid": "6a8c1a983531540f830c1532",
        }},
        {"attributes": {"title": "Second Article", "field_galnet_guid": "abc123"}},
    ]}
    with patch("edc.core.galnet_news.requests.get", return_value=_resp(payload)):
        result = fetch_latest_headlines()
    assert result == [
        (
            "Research Sheds New Light on Industrial Mining",
            "https://community.elitedangerous.com/en/galnet/uid/6a8c1a983531540f830c1532",
        ),
        ("Second Article", "https://community.elitedangerous.com/en/galnet/uid/abc123"),
    ]


def test_missing_guid_returns_title_with_none_url():
    payload = {"data": [{"attributes": {"title": "Research Sheds New Light on Industrial Mining"}}]}
    with patch("edc.core.galnet_news.requests.get", return_value=_resp(payload)):
        result = fetch_latest_headlines()
    assert result == [("Research Sheds New Light on Industrial Mining", None)]


def test_skips_entries_with_blank_title():
    payload = {"data": [
        {"attributes": {"title": "   "}},
        {"attributes": {"title": "Real Article"}},
    ]}
    with patch("edc.core.galnet_news.requests.get", return_value=_resp(payload)):
        result = fetch_latest_headlines()
    assert result == [("Real Article", None)]


def test_empty_data_returns_empty_list():
    with patch("edc.core.galnet_news.requests.get", return_value=_resp({"data": []})):
        result = fetch_latest_headlines()
    assert result == []


def test_network_error_returns_empty_list():
    with patch("edc.core.galnet_news.requests.get", side_effect=Exception("timeout")):
        result = fetch_latest_headlines()
    assert result == []


def test_blank_title_only_returns_empty_list():
    payload = {"data": [{"attributes": {"title": "   "}}]}
    with patch("edc.core.galnet_news.requests.get", return_value=_resp(payload)):
        result = fetch_latest_headlines()
    assert result == []
