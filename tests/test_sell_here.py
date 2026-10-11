"""Sell here: the docked station's live market (Market.json) as the destination of
the destination-first supply search, and commodity names matched across the
formats the market cache holds ('gold', 'Gold', '$gold_name;', 'SothisCrystallineGold')."""
from edc.core.trade_routes import commodity_key, find_supply_for_destination, station_from_market_items


def test_commodity_key_matches_every_stored_format():
    keys = {commodity_key(n) for n in ("gold", "Gold", "$gold_name;", "$Gold_Name;")}
    assert keys == {"gold"}
    assert commodity_key("SothisCrystallineGold") == commodity_key("Sothis Crystalline Gold") \
        == commodity_key("$sothiscrystallinegold_name;") == "sothiscrystallinegold"


def test_station_from_market_items_keeps_what_the_station_buys():
    items = [
        {"symbol": "gold", "name": "Gold", "sell_price": 9500, "demand": 1200, "demand_bracket": 3},
        {"symbol": "water", "name": "Water", "sell_price": 300, "demand": 0, "demand_bracket": 0},   # no demand
        {"symbol": "tea", "name": "Tea", "sell_price": 0, "demand": 50, "demand_bracket": 1},          # not bought
        {"symbol": "algae", "name": "Algae", "sell_price": 22, "demand": 1, "demand_bracket": 0},      # only accepted
    ]
    station = station_from_market_items(items, "2026-10-11T12:00:00Z")
    assert station["sells"] == {"gold": (9500, 1200, "2026-10-11T12:00:00Z")}
    assert station["brackets"] == {"gold": 3} and station["names"] == {"gold": "Gold"}


def test_supply_matches_across_name_formats():
    dest = {"sells": {"gold": (9500, 1200, "2026-10-11T12:00:00Z"),
                      "sothiscrystallinegold": (40000, 10, "2026-10-11T12:00:00Z")}}
    supply = {
        1: {"station_name": "A", "system_name": "S1", "x": 1.0, "y": 0.0, "z": 0.0,
            "buys": {"Gold": (8000, 500, "2026-10-11T11:00:00Z")}},
        2: {"station_name": "B", "system_name": "S2", "x": 2.0, "y": 0.0, "z": 0.0,
            "buys": {"SothisCrystallineGold": (30000, 5, "2026-10-11T11:00:00Z")}},
    }
    results = find_supply_for_destination(dest, (0.0, 0.0, 0.0), supply, cargo_capacity=100)
    got = {r["commodity"]: (r["buy_station_name"], r["quantity"]) for r in results}
    assert got == {"gold": ("A", 100), "sothiscrystallinegold": ("B", 5)}


def test_panel_searches_once_per_docked_market_and_keeps_last_docked(tmp_path):
    import time
    from types import SimpleNamespace
    from unittest.mock import patch
    from PyQt6.QtWidgets import QApplication
    from edc.ui.panels.trade_route_panel import TradeRoutePanel
    from persistence.database import Database
    from persistence.repository import Repository
    from persistence.schema import SCHEMA_SQL
    app = QApplication.instance() or QApplication([])
    db = Database(tmp_path / "t.db"); db.executescript(SCHEMA_SQL); db.run_migrations()
    panel = TradeRoutePanel(Repository(db))
    supply = {7: {"station_name": "Cheap Gold Port", "system_name": "Near", "pad_size": "L", "x": 3.0, "y": 0.0,
                  "z": 0.0, "buys": {"Gold": (8000, 500, "2026-10-11T11:00:00Z")}}}
    state = SimpleNamespace(
        system="Ekono", system_x=0.0, system_y=0.0, system_z=0.0, cargo_capacity=100, pp_power=None,
        station_name="Ekono Hub", current_market_id=42, current_market_station="Ekono Hub",
        current_market_system="Ekono", route_destination_system="",
        current_market_items=[{"symbol": "gold", "name": "Gold", "sell_price": 9500, "demand": 1200,
                               "demand_bracket": 3, "buy_price": 0, "stock": 0, "category": "Metals"}])
    calls = []
    real = Repository.get_market_snapshot_in_radius

    def fake_snapshot(self, *a):
        calls.append(a)
        return supply

    with patch.object(Repository, "get_market_snapshot_in_radius", fake_snapshot):
        panel.refresh(state)
        deadline = time.time() + 10
        while panel._sell_table.rowCount() == 0 and time.time() < deadline:
            app.processEvents(); time.sleep(0.02)
        panel._sell_thread.wait(5000)
        app.processEvents()
        assert panel._sell_table.item(0, 0).text() == "Gold"
        assert panel._sell_table.item(0, 1).text() == "Cheap Gold Port"
        assert panel._sell_table.item(0, 7).text() == "High 1,200"        # this station's live demand
        assert panel._sell_table.item(0, 9).text() == f"{1500 * 100:,}"    # (9500-8000) x 100t
        assert panel._sell_station_label.text().startswith("Docked at Ekono Hub")

        panel.refresh(state)                                              # same market: no new search
        state.station_name = None                                         # undocked
        panel.refresh(state)
        app.processEvents()
    assert len(calls) == 1
    assert panel._sell_station_label.text().startswith("Last docked at Ekono Hub")
    assert real is Repository.get_market_snapshot_in_radius
