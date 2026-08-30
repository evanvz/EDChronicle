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
    payload = {"data": [{"attributes": {"title": "Research Sheds New Light on Industrial Mining"}}]}
    with patch("edc.core.galnet_news.requests.get", return_value=_resp(payload)):
        title = fetch_latest_headline()
    assert title == "Research Sheds New Light on Industrial Mining"


def test_empty_data_returns_none():
    with patch("edc.core.galnet_news.requests.get", return_value=_resp({"data": []})):
        title = fetch_latest_headline()
    assert title is None


def test_network_error_returns_none():
    with patch("edc.core.galnet_news.requests.get", side_effect=Exception("timeout")):
        title = fetch_latest_headline()
    assert title is None


def test_blank_title_returns_none():
    payload = {"data": [{"attributes": {"title": "   "}}]}
    with patch("edc.core.galnet_news.requests.get", return_value=_resp(payload)):
        title = fetch_latest_headline()
    assert title is None
