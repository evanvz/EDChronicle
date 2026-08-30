"""fetch_latest_headline() parses Frontier's official GalNet news feed."""
from unittest.mock import patch

from edc.core.galnet_news import fetch_latest_headline


def _resp(json_data):
    class _Resp:
        def raise_for_status(self):
            pass
        def json(self):
            return json_data
    return _Resp()


def test_latest_headline_parses():
    payload = {"data": [{"attributes": {
        "title": "Research Sheds New Light on Industrial Mining",
        "field_galnet_guid": "6a8c1a983531540f830c1532",
    }}]}
    with patch("edc.core.galnet_news.requests.get", return_value=_resp(payload)):
        result = fetch_latest_headline()
    assert result == (
        "Research Sheds New Light on Industrial Mining",
        "https://community.elitedangerous.com/en/galnet/uid/6a8c1a983531540f830c1532",
    )


def test_missing_guid_returns_title_with_none_url():
    payload = {"data": [{"attributes": {"title": "Research Sheds New Light on Industrial Mining"}}]}
    with patch("edc.core.galnet_news.requests.get", return_value=_resp(payload)):
        result = fetch_latest_headline()
    assert result == ("Research Sheds New Light on Industrial Mining", None)


def test_empty_data_returns_none():
    with patch("edc.core.galnet_news.requests.get", return_value=_resp({"data": []})):
        result = fetch_latest_headline()
    assert result is None


def test_network_error_returns_none():
    with patch("edc.core.galnet_news.requests.get", side_effect=Exception("timeout")):
        result = fetch_latest_headline()
    assert result is None


def test_blank_title_returns_none():
    payload = {"data": [{"attributes": {"title": "   "}}]}
    with patch("edc.core.galnet_news.requests.get", return_value=_resp(payload)):
        result = fetch_latest_headline()
    assert result is None
