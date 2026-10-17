"""Trade Routes rework (2026-10-17): Point-to-Point Search enables as you type
and takes a From; system/station autocomplete matching anywhere in the name;
BGS Supply Run accepts a typed station; Sell Here can keep its destination
while you fly to a buy station."""
import time
from types import SimpleNamespace
from unittest.mock import patch

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from edc.ui.panels.trade_route_panel import TradeRoutePanel, _PointToPointWorker
from persistence.database import Database
from persistence.repository import Repository
from persistence.schema import SCHEMA_SQL

TS = "2026-10-17T10:00:00Z"


def _panel(tmp_path):
    app = QApplication.instance() or QApplication([])
    db = Database(tmp_path / "t.db"); db.executescript(SCHEMA_SQL); db.run_migrations()
    panel = TradeRoutePanel(Repository(db))
    panel._names_thread.wait(10000)   # Qt aborts if a test drops the panel while the name loader runs
    app.processEvents()
    return app, panel


def _state(**kw):
    base = dict(system="Ekono", system_x=0.0, system_y=0.0, system_z=0.0, cargo_capacity=100, pp_power=None,
                station_name=None, current_market_id=None, current_market_station="", current_market_system="",
                route_destination_system="", current_market_items=[])
    base.update(kw)
    return SimpleNamespace(**base)


def test_p2p_search_enables_as_you_type_with_a_from(tmp_path):
    app, p = _panel(tmp_path)
    p.refresh(_state())                       # undocked: no origin market
    assert not p._p2p_search_btn.isEnabled()
    p._dest_edit.setText("Sol")
    assert not p._p2p_search_btn.isEnabled()  # still no origin
    p._from_edit.setText("Ekono — Lundmark Terminal")
    assert p._p2p_search_btn.isEnabled()      # no refresh needed


def test_autocomplete_matches_anywhere(tmp_path):
    app, p = _panel(tmp_path)
    p._place_model.setStringList(["ICZ VE-Q b5-4", "ICZ VE-Q b5-4 — H.g.wells Landing", "Sol"])
    c = p._dest_edit.completer()
    c.setCompletionPrefix("ve-q")
    assert c.completionCount() == 2
    assert c.filterMode() == Qt.MatchFlag.MatchContains
    assert p._bgs_dest_combo.completer().filterMode() == Qt.MatchFlag.MatchContains


def test_worker_from_eddn_station_to_destination_station():
    snaps = {
        "Ekono": {1: {"station_name": "Lundmark Terminal", "system_name": "Ekono",
                      "buys": {"gold": (8000, 500, TS)}, "sells": {}},
                  2: {"station_name": "Other Port", "system_name": "Ekono",
                      "buys": {"gold": (7000, 500, TS)}, "sells": {}}},
        "Sol": {3: {"station_name": "Abraham Lincoln", "system_name": "Sol", "sells": {"gold": (9500, 1000, TS)},
                    "buys": {}},
                4: {"station_name": "Daedalus", "system_name": "Sol", "sells": {"gold": (9900, 1000, TS)},
                    "buys": {}}},
    }
    repo = SimpleNamespace(resolve_system_name_case_insensitive=lambda n: {"ekono": "Ekono", "sol": "Sol"}.get(n.lower()),
                           get_market_snapshot_for_systems=lambda names: dict(snaps.get(names[0], {})),
                           get_commodity_display_name_map=lambda: {"gold": "Gold"})
    w = _PointToPointWorker("x", [], "sol — Abraham Lincoln", 100, origin="ekono — Lundmark Terminal")
    dest, label = w._stations(repo, "sol — Abraham Lincoln")
    assert [v["station_name"] for v in dest.values()] == ["Abraham Lincoln"] and label == "Abraham Lincoln (Sol)"
    out = []
    w.finished.connect(lambda r, e: out.append((r, e)))
    with patch("persistence.database.Database", lambda *_: SimpleNamespace(close=lambda: None)), \
         patch("persistence.repository.Repository", lambda *_: repo):
        w.run()
    results, err = out[0]
    assert err == "" and len(results) == 1
    r = results[0]
    assert (r["buy_station_name"], r["sell_station_name"], r["total_profit"]) == ("Lundmark Terminal", "Abraham Lincoln", 150_000)


def test_bgs_typed_station_name_resolves(tmp_path):
    app, p = _panel(tmp_path)
    p._bgs_destinations = [{"system_name": "Ekono", "station_name": "Lundmark Terminal", "pp_status": "ok",
                            "pp_label": "Fortified"}]
    p._bgs_dest_combo.setEditText("lundmark terminal")
    dest, reason = p._resolve_bgs_destination()
    assert reason is None and dest["station_name"] == "Lundmark Terminal"


def test_sell_here_keeps_destination_and_highlights_buy_station(tmp_path):
    app, p = _panel(tmp_path)
    supply = {7: {"station_name": "Cheap Gold Port", "system_name": "Near", "pad_size": "L", "x": 3.0, "y": 0.0,
                  "z": 0.0, "buys": {"Gold": (8000, 500, TS)}}}
    hub = _state(station_name="Ekono Hub", current_market_id=42, current_market_station="Ekono Hub",
                 current_market_system="Ekono",
                 current_market_items=[{"symbol": "gold", "name": "Gold", "sell_price": 9500, "demand": 1200,
                                        "demand_bracket": 3, "buy_price": 0, "stock": 0}])
    with patch.object(Repository, "get_market_snapshot_in_radius", lambda self, *a: supply):
        p.refresh(hub)
        deadline = time.time() + 10
        while p._sell_table.rowCount() == 0 and time.time() < deadline:
            app.processEvents(); time.sleep(0.02)
        p._sell_thread.wait(5000); app.processEvents()
        p._sell_pin_check.setChecked(True)
        port = _state(system="Near", system_x=3.0, station_name="Cheap Gold Port", current_market_id=7,
                      current_market_station="Cheap Gold Port", current_market_system="Near",
                      current_market_items=[{"symbol": "gold", "name": "Gold", "sell_price": 7800, "demand": 0,
                                             "demand_bracket": 0, "buy_price": 8000, "stock": 500}])
        p.refresh(port)
        app.processEvents()
    assert p._sell_market["station"] == "Ekono Hub"                       # destination kept
    assert p._sell_station_label.text().startswith("Selling at Ekono Hub (Ekono) — kept")
    assert p._sell_table.item(0, 0).background().color().name() == "#1f3d1f"
    assert "buy here and sell at Ekono Hub" in p._sell_status_label.text()
    p._sell_pin_check.setChecked(False)
    assert p._sell_table.item(0, 0).background().style() == Qt.BrushStyle.NoBrush
