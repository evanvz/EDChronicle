"""Sell Here's "Sell at a loss here" mode: hinder a station's owner by
selling goods that cost more elsewhere than the station pays (SINC Complete
BGS Guide 2024, "Unprofitable Trade Loops", printed p37: high demand first,
a big loss)."""
import time
from types import SimpleNamespace
from unittest.mock import patch

from PyQt6.QtWidgets import QApplication

from edc.core.trade_routes import find_loss_supply, station_accepts_from_market_items

TS = "2026-10-18T12:00:00Z"
ITEMS = [{"symbol": "gold", "name": "Gold", "sell_price": 40000, "demand": 500, "demand_bracket": 2},
         {"symbol": "tritium", "name": "Tritium", "sell_price": 45000, "demand": 1, "demand_bracket": 0},  # accept only
         {"symbol": "water", "name": "Water", "sell_price": 0, "demand": 0, "demand_bracket": 0}]           # not taken
SUPPLY = {
    1: {"station_name": "Dear Port", "system_name": "A", "x": 1.0, "y": 0.0, "z": 0.0,
        "buys": {"Gold": (43000, 900, TS), "Tritium": (49000, 900, TS)}},
    2: {"station_name": "Dearer Port", "system_name": "B", "x": 2.0, "y": 0.0, "z": 0.0,
        "buys": {"Gold": (47000, 900, TS)}},
    3: {"station_name": "Cheap Port", "system_name": "C", "x": 1.0, "y": 0.0, "z": 0.0,
        "buys": {"Gold": (30000, 900, TS)}},                                           # profit, not a loss
}


def test_accepts_include_zero_demand_items():
    accepts = station_accepts_from_market_items(ITEMS, TS)
    assert set(accepts["sells"]) == {"gold", "tritium"}


def test_biggest_loss_source_and_high_demand_first():
    """SINC (printed p37): a loss in high-demand goods beats medium/low, aiming for a big loss."""
    rows = find_loss_supply(station_accepts_from_market_items(ITEMS, TS), (0.0, 0.0, 0.0), SUPPLY, 100)
    assert [(r["commodity"], r["buy_station_name"], r["total_profit"], r["zero_demand"]) for r in rows] == [
        ("gold", "Dearer Port", -700_000, False),       # medium demand first, the bigger loss (7,000/t)
        ("tritium", "Dear Port", -400_000, True)]       # zero demand last


def test_panel_loss_mode_switches_search(tmp_path):
    from edc.ui.panels.trade_route_panel import TradeRoutePanel
    from persistence.database import Database
    from persistence.repository import Repository
    from persistence.schema import SCHEMA_SQL
    app = QApplication.instance() or QApplication([])
    db = Database(tmp_path / "t.db"); db.executescript(SCHEMA_SQL); db.run_migrations()
    p = TradeRoutePanel(Repository(db)); p._names_thread.wait(10000); app.processEvents()
    supply = {k: dict(v, pad_size="L") for k, v in SUPPLY.items()}
    state = SimpleNamespace(system="Target", system_x=0.0, system_y=0.0, system_z=0.0, cargo_capacity=100,
                            pp_power=None, station_name="Rival Settlement", current_market_id=9,
                            current_market_station="Rival Settlement", current_market_system="Target",
                            route_destination_system="",
                            current_market_items=[dict(i, buy_price=0, stock=0) for i in ITEMS])

    def wait():
        deadline = time.time() + 10
        while p._sell_thread.isRunning() and time.time() < deadline:
            app.processEvents(); time.sleep(0.02)
        p._sell_thread.wait(5000); app.processEvents()

    with patch.object(Repository, "get_market_snapshot_in_radius", lambda self, *a: supply):
        p.refresh(state); wait()
        assert p._sell_table.item(0, 1).text() == "Cheap Port"          # normal mode: profitable source
        p._sell_loss_check.setChecked(True); wait()
    assert [p._sell_table.item(r, 0).text() for r in range(p._sell_table.rowCount())] == ["Gold", "Tritium"]
    assert p._sell_table.item(1, 7).text().startswith("Zero")
    assert "at a loss" in p._sell_status_label.text()
    db.close()
