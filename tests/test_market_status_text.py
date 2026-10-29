"""2026-10-29: the Market search status line had the verbs swapped -- a BUY search
(stations with stock, where you buy) said "stations buying", a SELL search "selling"."""
from types import SimpleNamespace

from PyQt6.QtWidgets import QApplication, QLabel, QTableWidget

from edc.ui.panels.market_panel import MarketPanel


def _status(buy_mode):
    app = QApplication.instance() or QApplication([])  # noqa: F841
    label = QLabel()
    fake = SimpleNamespace(
        _last_results=[], _last_search_desc=("Gold", 30, buy_mode), _last_near_label="Delta Indi", _system=None,
        _filter_min_pad=lambda r: r, _filter_enemy_pp=lambda r: (r, 0), _filter_faction_only=lambda r: r,
        _cargo_qty_of=lambda name: 0, _status_label=label, _table=QTableWidget(0, 7))
    MarketPanel._render_results(fake)
    return label.text()


def test_buy_search_finds_stations_selling():
    assert _status(True) == "Found 0 stations selling Gold within 30 ly of Delta Indi."


def test_sell_search_finds_stations_buying():
    assert _status(False) == "Found 0 stations buying Gold within 30 ly of Delta Indi."
