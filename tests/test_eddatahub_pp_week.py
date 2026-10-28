"""fetch_system_powerplay: the hub's PP readings per system, in the app's reading shape."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from edc.core.eddatahub_client import fetch_system_powerplay

ROW = {"system": 77, "time": "2026-10-23T10:00:00+00:00", "state": "Exploited",
       "reinforcement": 10, "undermining": 5, "control": 0.3}


@pytest.fixture
def hub():
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps([ROW] if self.path.startswith("/api/system-powerplay") else []).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_readings_come_back_per_system_in_app_shape(hub):
    got = fetch_system_powerplay(hub, [77, 88], "2026-10-22T07:00:00Z")
    assert got[77] == [{"observed_at": "2026-10-23T10:00:00Z", "pp_state": "Exploited", "reinforcement": 10,
                        "undermining": 5, "control": 0.3, "source": "hub"}]
    assert got[88] == []                     # asked for, hub has nothing: empty, not missing


def test_no_hub_means_none():
    assert fetch_system_powerplay("", [77], "2026-10-22T07:00:00Z") is None
    assert fetch_system_powerplay("http://127.0.0.1:9", [77], "2026-10-22T07:00:00Z") is None
