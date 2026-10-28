"""fetch_market_search: hub rows as returned, None on any failure, 60 s skip after a failure."""
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import edc.core.eddatahub_client as client
from edc.core.eddatahub_client import fetch_market_search

ROW = {"market_id": 1, "commodity": "gold", "station_name": "A", "system_name": "S", "sell_price": 9}


@pytest.fixture(autouse=True)
def _reset_skip(monkeypatch):
    monkeypatch.setattr(client, "_skip_until", 0.0)


def _serve(status=200, body=b"[]"):
    paths = []

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            paths.append(self.path)
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}", paths


def test_fetch_market_search_returns_rows():
    srv, url, paths = _serve(body=b'[{"market_id": 1, "commodity": "gold", "station_name": "A", '
                                  b'"system_name": "S", "sell_price": 9}]')
    try:
        assert fetch_market_search(url, ["gold", "silver"], 1.5, 2.5, 3.5, 40) == [ROW]
        assert fetch_market_search(url, ["gold"], 1.5, 2.5, 3.5, 40, exclude_market_id=7) == [ROW]
    finally:
        srv.shutdown()
    assert paths[0].startswith("/api/market-search?")
    for part in ("commodity=gold,silver", "x=1.5", "y=2.5", "z=3.5", "radius=40"):
        assert part in paths[0].replace("%2C", ",")
    assert "exclude" not in paths[0]
    assert "exclude=7" in paths[1]


def test_fetch_market_search_non_200_is_none():
    srv, url, _ = _serve(status=503)
    try:
        assert fetch_market_search(url, ["gold"], 0, 0, 0, 40) is None
    finally:
        srv.shutdown()


@pytest.mark.parametrize("body", [b"not json", b'{"a": 1}'])
def test_fetch_market_search_bad_json_is_none(body):
    srv, url, _ = _serve(body=body)
    try:
        assert fetch_market_search(url, ["gold"], 0, 0, 0, 40) is None
    finally:
        srv.shutdown()


def test_fetch_market_search_skips_hub_after_failure(monkeypatch):
    srv, url, paths = _serve(body=b"[]")
    try:
        assert fetch_market_search("http://127.0.0.1:9", ["gold"], 0, 0, 0, 40) is None
        assert fetch_market_search(url, ["gold"], 0, 0, 0, 40) is None
        assert paths == []
        real = time.monotonic
        monkeypatch.setattr(time, "monotonic", lambda: real() + 61)
        assert fetch_market_search(url, ["gold"], 0, 0, 0, 40) == []
    finally:
        srv.shutdown()
