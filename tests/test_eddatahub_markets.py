"""Market catch-up at startup: EDDataHub streams the newest market of each station
it received while the app was closed (gzip NDJSON); the worker writes them through
the live EDDN market path, and an older reading never replaces a newer one."""
import gzip
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from edc.ui.main_window import _HubMarketCatchUpWorker
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL


def _market(mid, price, ts):
    return {"marketId": mid, "stationName": f"S{mid}", "systemName": "Sol", "stationType": "Coriolis",
            "timestamp": ts, "commodities": [{"name": "gold", "sellPrice": price, "buyPrice": 0,
                                              "meanPrice": 0, "demand": 1, "demandBracket": 1,
                                              "stock": 0, "stockBracket": 0}]}


def _serve(messages, asked):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            asked.append(self.path)
            body = gzip.compress(b"".join(json.dumps(m).encode() + b"\n" for m in messages))
            self.send_response(200)
            self.send_header("Content-Encoding", "gzip")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_catch_up_writes_missed_markets_and_keeps_newer_ones(tmp_path):
    path = tmp_path / "t.db"
    db = Database(path); db.executescript(SCHEMA_SQL); db.run_migrations()
    repo = Repository(db)
    repo.save_market_snapshot_batch([(2, "gold", "S2", "Coriolis", "Sol", 900, 0, 0, 1, 1, 0, 0, "2026-10-25T09:00:00Z")])
    db.close()
    asked = []
    srv = _serve([_market(1, 100, "2026-10-25T08:00:00Z"), _market(2, 50, "2026-10-25T07:00:00Z")], asked)
    try:
        _HubMarketCatchUpWorker(path, f"http://127.0.0.1:{srv.server_address[1]}", "2026-10-25T10:00:00Z").run()
    finally:
        srv.shutdown()
    assert "since=2026-10-25T08%3A50%3A00Z" in asked[0]          # newest stored row, less 10 min
    db = Database(path)
    rows = db.conn.execute("SELECT market_id, sell_price FROM net.market_prices ORDER BY 1").fetchall()
    assert [tuple(r) for r in rows] == [(1, 100), (2, 900)]     # 2's older hub reading lost to the newer one
    db.close()


def test_far_future_timestamp_cannot_freeze_a_market():
    from datetime import datetime, timezone
    from edc.core.eddn_market import _normalize_ts
    assert _normalize_ts("2099-01-01T00:00:00Z") <= datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert _normalize_ts("2026-10-25T08:00:00.123Z") == "2026-10-25T08:00:00Z"
