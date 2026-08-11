"""Market panel — best sell price search across the galaxy-wide EDDN commodity feed."""
from __future__ import annotations

import logging
import re
from typing import Optional

from PyQt6.QtCore import Qt, QObject, QThread, QStringListModel, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication,
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QSpinBox, QComboBox, QCompleter, QTableWidget, QTableWidgetItem,
    QHeaderView, QFrame, QDialog, QSizePolicy, QCheckBox,
)

from edc.core.station_pads import pad_size_hint
from edc.ui import formatting as fmt
from edc.ui.busy_spinner import BusySpinner

log = logging.getLogger(__name__)

_CARD_STYLE = "QFrame { background:#0d1a2a; border:1px solid #1e3a5a; border-radius:5px; }"
_HDR_STYLE = "color:#7a7a7a; font-size:12px; font-weight:bold; letter-spacing:1px; background:transparent; border:none;"
_LABEL_STYLE = "background:transparent; border:none; color:#c8c8c8;"

# (required StationServices tags, button label, (bg, text) accent) —
# Pioneer Supplies needs Black Market too for contraband items like
# E-Breach specifically, not just the kiosk itself. Distinct colors so the
# row of buttons is scannable at a glance, not one undifferentiated block.
_CONCOURSE_SERVICES = [
    (["pioneersupplies", "blackmarket"], "Pioneer Supplies (+Black Market)", ("#3a1a1a", "#FF8080")),
    (["blackmarket"], "Black Market", ("#3a2410", "#FFA060")),
    (["apexinterstellar"], "Apex Interstellar", ("#1a2a3a", "#8CC8FF")),
    (["frontlinesolutions"], "Frontline Solutions", ("#1a3a1a", "#8CFF8C")),
    (["vistagenomics"], "Vista Genomics", ("#0d2a2a", "#6BE6D9")),
    (["bartender"], "Bartender", ("#3a3010", "#FFD93D")),
    (["materialtrader"], "Material Trader", ("#2a1a3a", "#C89CFF")),
    (["techBroker"], "Technology Broker", ("#1a3a30", "#6BFFB3")),
]


def normalize_commodity_name(name: str) -> str:
    """
    EDDN/journal commodity symbols are lowercase, no spaces/punctuation
    (e.g. "Low Temperature Diamonds" -> "lowtemperaturediamonds"). Applied
    to whatever the user types so free-text search matches stored data.
    """
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


_format_relative_time = fmt.relative_time


class _NumericTableWidgetItem(QTableWidgetItem):
    """Sorts by an actual numeric value instead of the displayed string
    (plain QTableWidgetItem sorting would put "1,200" before "300")."""

    def __init__(self, text: str, sort_value: float):
        super().__init__(text)
        self._sort_value = sort_value

    def __lt__(self, other):
        if isinstance(other, _NumericTableWidgetItem):
            return self._sort_value < other._sort_value
        return super().__lt__(other)


def _compute_trade_opportunities(repo, items, market_id, ref_x, ref_y, ref_z, radius_ly):
    """
    One batched query for every purchasable commodity in the current
    market, instead of a separate search_market_prices call per commodity
    — confirmed live that the per-commodity loop made a large station's
    market take minutes (100+ commodities x 1s+ each).
    """
    purchasable = {}  # commodity_name -> item
    for item in items:
        buy_price = item.get("buy_price") or 0
        if buy_price <= 0:
            continue  # not purchasable here — nothing to flip
        stock = item.get("stock") or 0
        if stock <= 0:
            continue  # sold here in principle, but currently out of stock
        commodity = normalize_commodity_name(item.get("name") or "")
        if not commodity:
            continue
        purchasable[commodity] = item

    if not purchasable:
        return []

    try:
        results_by_commodity = repo.search_market_prices_multi(
            list(purchasable.keys()), ref_x, ref_y, ref_z, float(radius_ly),
            exclude_market_id=market_id,
        )
    except Exception:
        log.exception("Trade opportunity batch search failed")
        return []

    opportunities = []
    for commodity, item in purchasable.items():
        results = results_by_commodity.get(commodity) or []
        if not results:
            continue
        best = results[0]
        buy_price = item.get("buy_price") or 0
        sell_price = best.get("sell_price") or 0
        if sell_price <= 0:
            continue
        profit_pct = (sell_price - buy_price) / buy_price * 100.0
        if profit_pct <= 0:
            continue
        opportunities.append({
            "name": item.get("name"),
            "buy_price": buy_price,
            "stock": item.get("stock") or 0,
            "sell_price": sell_price,
            "station_name": best.get("station_name"),
            "station_type": best.get("station_type"),
            "pad_size": best.get("pad_size"),
            "system_name": best.get("system_name"),
            "distance_ly": best.get("distance_ly", 0.0),
            "profit_pct": profit_pct,
        })

    opportunities.sort(key=lambda o: o["profit_pct"], reverse=True)
    return opportunities


class _TradeOpportunityWorker(QObject):
    """
    Opens its own SQLite connection rather than reusing the main thread's
    Repository — sqlite3 connections cannot be shared across threads.
    """
    finished = pyqtSignal(list, str)  # (opportunities, station_name)

    def __init__(self, db_path, items, market_id, station, ref_x, ref_y, ref_z, radius_ly):
        super().__init__()
        self._db_path = db_path
        self._items = items
        self._market_id = market_id
        self._station = station
        self._ref_x, self._ref_y, self._ref_z = ref_x, ref_y, ref_z
        self._radius_ly = radius_ly

    def run(self):
        from persistence.database import Database
        from persistence.repository import Repository

        db = Database(self._db_path)
        repo = Repository(db)
        try:
            opportunities = _compute_trade_opportunities(
                repo, self._items, self._market_id,
                self._ref_x, self._ref_y, self._ref_z, self._radius_ly,
            )
        finally:
            db.close()
        self.finished.emit(opportunities, self._station)


class _MarketSearchWorker(QObject):
    """
    Opens its own SQLite connection rather than reusing the main thread's
    Repository — sqlite3 connections cannot be shared across threads.
    market_prices' commodity_name lookup is index-backed but still scans a
    lot of scattered rows once the table reaches many millions of rows
    (confirmed: 20+ seconds for a common commodity) — too slow to run
    synchronously on the UI thread.
    """
    finished = pyqtSignal(list, str, int, bool)  # (results, raw_query_text, radius, buy_mode)

    def __init__(self, db_path, commodity, raw_query_text, x, y, z, radius, buy_mode):
        super().__init__()
        self._db_path = db_path
        self._commodity = commodity
        self._raw_query_text = raw_query_text
        self._x, self._y, self._z = x, y, z
        self._radius = radius
        self._buy_mode = buy_mode

    def run(self):
        from persistence.database import Database
        from persistence.repository import Repository

        db = Database(self._db_path)
        repo = Repository(db)
        try:
            if self._buy_mode:
                results = repo.search_market_buy_prices(self._commodity, self._x, self._y, self._z, float(self._radius))
            else:
                results = repo.search_market_prices(self._commodity, self._x, self._y, self._z, float(self._radius))
        except Exception:
            log.exception("Market price search failed")
            results = []
        finally:
            db.close()
        self.finished.emit(results, self._raw_query_text, self._radius, self._buy_mode)


class _NearSystemCoordsWorker(QObject):
    """
    Resolves a "Near" system name typed for a Market search. Our own
    system_coords cache is only ever populated passively from EDDN traffic
    (someone, somewhere, has to have jumped into/reported that exact system
    while our listener happened to be connected) — for a system nobody's
    reported recently, that lookup comes up empty even though the system is
    perfectly real. Falls back to EDSM's system endpoint (a real network
    call, hence its own thread) and saves any hit back into system_coords
    so the next lookup for the same system is instant.
    """
    finished = pyqtSignal(object, str)  # ((x, y, z) or None, system_name)

    def __init__(self, db_path, system_name: str):
        super().__init__()
        self._db_path = db_path
        self._system_name = system_name

    def run(self):
        from persistence.database import Database
        from persistence.repository import Repository
        from edc.core.edsm_faction_lookup import fetch_system_coords

        coords = fetch_system_coords(self._system_name)
        if coords:
            from datetime import datetime, timezone

            db = Database(self._db_path)
            try:
                repo = Repository(db)
                repo.save_system_coords_batch([
                    (self._system_name, coords[0], coords[1], coords[2], datetime.now(timezone.utc).isoformat())
                ])
            except Exception:
                log.exception("Failed to save EDSM-resolved coords for %r", self._system_name)
            finally:
                db.close()
        self.finished.emit(coords, self._system_name)


class MarketPanel(QWidget):
    """
    Owns all widgets and refresh logic for the Market tab.
    Receives state via refresh(state, radius_ly). Unlike most panels this
    one is constructed with a Repository directly, but the manual search
    itself runs on a background thread (_MarketSearchWorker) — at real
    scale (millions of rows in market_prices) it's not fast enough to run
    synchronously without freezing the UI. Trade Opportunities is likewise
    backgrounded (see refresh_trade_opportunities), one query per commodity
    in the current market.
    """

    # system_name, station_name, commodity, mode ("buy"/"sell") — emitted
    # when the user clicks a result row's Station/System cell, so the
    # destination can be pinned/persisted and shown elsewhere (Overview)
    # until they actually reach it.
    destination_selected = pyqtSignal(str, str, str, str)

    def __init__(self, repo, rare_table=None, edsm_powerplay=None, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._rare_table = rare_table
        self._edsm_powerplay = edsm_powerplay
        self._my_power: Optional[str] = None
        self._rare_dialog: Optional["_RareGoodsDialog"] = None
        self._system: str = ""
        self._ref_x: float = 0.0
        self._ref_y: float = 0.0
        self._ref_z: float = 0.0
        self._trade_thread: Optional[QThread] = None
        self._trade_worker: Optional[_TradeOpportunityWorker] = None
        self._search_thread: Optional[QThread] = None
        self._search_worker: Optional[_MarketSearchWorker] = None
        self._coords_thread: Optional[QThread] = None
        self._coords_worker: Optional[_NearSystemCoordsWorker] = None
        self._last_market_id_computed: Optional[int] = None
        self._last_results: Optional[list] = None
        self._last_search_desc = ("", 0, False)
        self._last_near_label: Optional[str] = None
        self._last_state = None
        self._last_radius_ly: int = 100

        # Remembers "where to sell X" per commodity across station visits —
        # merged (not replaced) on each new Trade Opportunities computation,
        # so a destination found at an earlier station isn't lost once you
        # undock and the current-market data clears.
        self._cargo_destinations: dict = {}
        self._last_trade_opportunities_raw: list = []
        self._last_trade_station: str = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 8)
        root.setSpacing(6)

        # ── In Cargo — Sell At (persists across jumps/undocking) ────────
        self._cargo_hdr = QLabel("IN CARGO — SELL AT")
        self._cargo_hdr.setStyleSheet(_HDR_STYLE)
        self._cargo_hdr.setVisible(False)
        root.addWidget(self._cargo_hdr)

        self._cargo_table = QTableWidget()
        self._cargo_table.setColumnCount(6)
        self._cargo_table.setHorizontalHeaderLabels(
            ["Commodity", "Qty", "Sell At", "Pad", "Dist (ly)", "Sell Price"]
        )
        self._cargo_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._cargo_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._cargo_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._cargo_table.verticalHeader().setVisible(False)
        self._cargo_table.verticalHeader().setDefaultSectionSize(18)
        self._cargo_table.setAlternatingRowColors(True)
        self._cargo_table.setStyleSheet(
            "QTableWidget { background:#0d1a0d; alternate-background-color:#0f1f0f;"
            " gridline-color:#1e3a1e; border:1px solid #2a5a2a; font-size:12px; }"
            "QTableWidget::item { padding:1px 4px; }"
            "QHeaderView::section { background:#0d1a0d; color:#6BCB77; border:none;"
            " padding:2px; font-size:12px; font-weight:bold; letter-spacing:1px; }"
            "QTableWidget::item:selected { background:#1a3a1a; color:#FFB347; }"
        )
        ch = self._cargo_table.horizontalHeader()
        ch.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        ch.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        ch.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        ch.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        ch.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        ch.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self._cargo_table.setMaximumHeight(130)
        self._cargo_table.setVisible(False)
        root.addWidget(self._cargo_table)

        # ── Search card ──────────────────────────────────────────────────
        search_frame = QFrame()
        search_frame.setStyleSheet(_CARD_STYLE)
        search_layout = QVBoxLayout(search_frame)
        search_layout.setContentsMargins(8, 6, 8, 8)
        search_layout.setSpacing(6)

        self._search_hdr = QLabel("MARKET — BEST SELL PRICE SEARCH")
        self._search_hdr.setStyleSheet(_HDR_STYLE)
        search_layout.addWidget(self._search_hdr)

        self._location_label = QLabel("Location: —")
        self._location_label.setStyleSheet(_LABEL_STYLE)
        search_layout.addWidget(self._location_label)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)
        mode_label = QLabel("I want to:")
        mode_label.setStyleSheet(_LABEL_STYLE + " font-weight:bold;")
        self._mode_combo = QComboBox()
        self._mode_combo.addItem("SELL — find the best price to sell a commodity", "sell")
        self._mode_combo.addItem("BUY — find the cheapest place to buy a commodity", "buy")
        self._mode_combo.setStyleSheet(
            "QComboBox { background:#0a1520; color:#FFB347; border:1px solid #FFB347;"
            " border-radius:3px; padding:3px 8px; font-weight:bold; }"
        )
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        mode_row.addWidget(mode_label)
        mode_row.addWidget(self._mode_combo, 1)
        search_layout.addLayout(mode_row)

        row = QHBoxLayout()
        row.setSpacing(8)

        self._commodity_edit = QLineEdit()
        self._commodity_edit.setPlaceholderText("Commodity (e.g. Gold, Painite, Low Temperature Diamonds...)")
        self._commodity_edit.setStyleSheet("background:#0a1520; color:#c8c8c8; border:1px solid #1e3a5a;")
        self._commodity_edit.returnPressed.connect(self._start_search)

        self._commodity_completer = QCompleter([])
        self._commodity_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._commodity_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._commodity_completer.popup().setStyleSheet(
            "QAbstractItemView { background:#0a1520; color:#c8c8c8; border:1px solid #1e3a5a;"
            " selection-background-color:#1a3a5a; selection-color:#FFB347; }"
        )
        self._commodity_edit.setCompleter(self._commodity_completer)
        self.refresh_commodity_names()

        near_label = QLabel("Near:")
        near_label.setStyleSheet(_LABEL_STYLE)
        self._near_edit = QLineEdit()
        self._near_edit.setPlaceholderText("Optional — system name, e.g. a delivery destination. Blank = current location.")
        self._near_edit.setStyleSheet("background:#0a1520; color:#c8c8c8; border:1px solid #1e3a5a;")
        self._near_edit.returnPressed.connect(self._start_search)

        self._exclude_enemy_pp_check = QCheckBox("Exclude enemy PowerPlay systems")
        self._exclude_enemy_pp_check.setStyleSheet(_LABEL_STYLE)
        self._exclude_enemy_pp_check.setToolTip(
            "Drops results in systems currently controlled by a Power other than "
            "yours (from EDSM's daily PowerPlay dump — systems with no known "
            "PowerPlay presence are left in, not treated as enemy)."
        )
        self._exclude_enemy_pp_check.setChecked(True)
        self._exclude_enemy_pp_check.toggled.connect(self._on_exclude_enemy_pp_toggled)

        self._faction_only_check = QCheckBox("Only my squadron faction's controlled stations")
        self._faction_only_check.setStyleSheet(_LABEL_STYLE)
        self._faction_only_check.setToolTip(
            "Same filter as Trade Route Loop Planner's equivalent checkbox — "
            "drops results at stations not controlled by your squadron's "
            "aligned faction."
        )
        self._faction_only_check.toggled.connect(self._on_faction_only_toggled)

        range_label = QLabel("Range:")
        range_label.setStyleSheet(_LABEL_STYLE)
        self._range_spin = QSpinBox()
        self._range_spin.setRange(10, 5000)
        self._range_spin.setSingleStep(10)
        self._range_spin.setValue(100)
        self._range_spin.setSuffix(" ly")
        self._range_spin.setStyleSheet("background:#0a1520; color:#c8c8c8; border:1px solid #1e3a5a;")

        pad_label = QLabel("Min pad:")
        pad_label.setStyleSheet(_LABEL_STYLE)
        self._pad_filter_combo = QComboBox()
        self._pad_filter_combo.addItem("Any", None)
        self._pad_filter_combo.addItem("Medium+", "M")
        self._pad_filter_combo.addItem("Large only", "L")
        self._pad_filter_combo.setStyleSheet("background:#0a1520; color:#c8c8c8; border:1px solid #1e3a5a;")
        self._pad_filter_combo.currentIndexChanged.connect(self._apply_pad_filter)

        self._search_btn = QPushButton("Search")
        self._search_btn.setStyleSheet(
            "QPushButton { background:#1a3a5a; color:#FFB347; border:1px solid #2a5a8a;"
            " border-radius:3px; padding:3px 12px; font-weight:bold; }"
            "QPushButton:hover { background:#2a5a8a; }"
            "QPushButton:disabled { background:#111; color:#555; border-color:#333; }"
        )
        self._search_btn.clicked.connect(self._start_search)

        row.addWidget(self._commodity_edit, 1)
        row.addWidget(range_label)
        row.addWidget(self._range_spin)
        row.addWidget(pad_label)
        row.addWidget(self._pad_filter_combo)
        row.addWidget(self._search_btn)
        search_layout.addLayout(row)

        near_row = QHBoxLayout()
        near_row.setSpacing(8)
        near_row.addWidget(near_label)
        near_row.addWidget(self._near_edit, 1)
        near_row.addWidget(self._exclude_enemy_pp_check)
        near_row.addWidget(self._faction_only_check)
        search_layout.addLayout(near_row)

        service_row = QHBoxLayout()
        service_row.setSpacing(4)

        self._rare_goods_btn = QPushButton("Rare Goods…")
        self._rare_goods_btn.setStyleSheet(
            "QPushButton { background:#2a1a3a; color:#D9A8FF; border:1px solid #5a3a8a;"
            " border-radius:3px; padding:3px 10px; font-weight:bold; }"
            "QPushButton:hover { background:#3a2a5a; }"
        )
        self._rare_goods_btn.setToolTip(
            "Real rare goods only have one true source station each — this cross-references "
            "the known list against actual EDDN reports for that exact station, not a plain "
            "name search (which can surface noisy/incorrect duplicate listings)."
        )
        self._rare_goods_btn.clicked.connect(self._open_rare_goods_dialog)
        service_row.addWidget(self._rare_goods_btn)

        self._service_dialogs: dict = {}
        for tags, label, (bg, fg) in _CONCOURSE_SERVICES:
            btn = QPushButton(f"{label}…")
            btn.setStyleSheet(
                f"QPushButton {{ background:{bg}; color:{fg}; border:1px solid {fg};"
                " border-radius:3px; padding:3px 10px; font-weight:bold; }"
                f"QPushButton:hover {{ background:{fg}; color:{bg}; }}"
            )
            btn.setToolTip(f"Known stations (from your own past dockings) offering {label}, closest first.")
            btn.clicked.connect(lambda _checked=False, t=tags, l=label: self._open_service_dialog(t, l))
            service_row.addWidget(btn)

        service_row.addStretch(1)
        search_layout.addLayout(service_row)

        note = QLabel(
            "Sourced from EDDN's live galaxy-wide commodity feed — other commanders' "
            "recent market visits, not just your own. Prices can go stale between visits; "
            "check \"Updated\" before flying somewhere."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#7a7a7a; font-size:11px; background:transparent; border:none;")
        search_layout.addWidget(note)

        root.addWidget(search_frame)

        # ── Trade opportunities (current market) ────────────────────────
        trade_hdr_row = QHBoxLayout()
        self._trade_hdr = QLabel("TRADE OPPORTUNITIES — CURRENT MARKET")
        self._trade_hdr.setStyleSheet(_HDR_STYLE)
        self._trade_hdr.setVisible(False)
        trade_hdr_row.addWidget(self._trade_hdr)
        trade_hdr_row.addStretch(1)
        self._trade_refresh_btn = QPushButton("Refresh")
        self._trade_refresh_btn.setStyleSheet(
            "QPushButton { background:#1a3a5a; color:#FFB347; border:1px solid #2a5a8a;"
            " border-radius:3px; padding:2px 10px; font-weight:bold; }"
            "QPushButton:hover { background:#2a5a8a; }"
            "QPushButton:disabled { background:#111; color:#555; border-color:#333; }"
        )
        self._trade_refresh_btn.setToolTip(
            "Re-check current best sell prices without leaving/reopening the market screen."
        )
        self._trade_refresh_btn.setVisible(False)
        self._trade_refresh_btn.clicked.connect(self._on_refresh_trade_clicked)
        trade_hdr_row.addWidget(self._trade_refresh_btn)
        root.addLayout(trade_hdr_row)

        self._trade_status_label = QLabel("")
        self._trade_status_label.setStyleSheet("color:#888888; font-size:12px; background:transparent;")
        self._trade_status_label.setVisible(False)
        root.addWidget(self._trade_status_label)

        self._trade_table = QTableWidget()
        self._trade_table.setColumnCount(9)
        self._trade_table.setHorizontalHeaderLabels(
            ["Commodity", "Buy Here", "Stock", "Best Sell", "Destination Station",
             "Destination System", "Pad", "Dist (ly)", "Profit %"]
        )
        self._trade_table.setToolTip("Click a Destination Station or System cell to copy its name to the clipboard.")
        self._trade_table.cellClicked.connect(self._on_trade_cell_clicked)
        self._trade_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._trade_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._trade_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._trade_table.verticalHeader().setVisible(False)
        self._trade_table.verticalHeader().setDefaultSectionSize(18)
        self._trade_table.setAlternatingRowColors(True)
        self._trade_table.setStyleSheet(
            "QTableWidget { background:#080f18; alternate-background-color:#0a1520;"
            " gridline-color:#1e3a5a; border:1px solid #1e3a5a; font-size:12px; }"
            "QTableWidget::item { padding:1px 4px; }"
            "QHeaderView::section { background:#0d1a2a; color:#888888; border:none;"
            " padding:2px; font-size:12px; font-weight:bold; letter-spacing:1px; }"
            "QTableWidget::item:selected { background:#1a3a5a; color:#FFB347; }"
        )
        th = self._trade_table.horizontalHeader()
        th.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        th.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        th.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        th.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        th.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        th.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        th.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        th.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        th.setSectionResizeMode(8, QHeaderView.ResizeMode.ResizeToContents)
        self._trade_table.setVisible(False)
        # Fixed vertical policy + cap so a large manual search result below
        # (also stretch=1) can never starve this table for space when both
        # are visible at once — it scrolls internally instead of shrinking.
        self._trade_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self._trade_table.setMaximumHeight(260)
        root.addWidget(self._trade_table)

        # Floats over the table (kept empty, not hidden, while loading, so
        # the spinner has a stable target geometry to center itself on) —
        # not placed in the layout itself, see BusySpinner.
        self._trade_loading_spinner = BusySpinner(self)

        # ── Status + results ────────────────────────────────────────────
        self._status_label = QLabel("Enter a commodity and press Search.")
        self._status_label.setStyleSheet("color:#888888; font-size:12px; background:transparent;")
        root.addWidget(self._status_label)

        self._table = QTableWidget()
        self._table.setColumnCount(7)
        self._table.setHorizontalHeaderLabels(
            ["Station", "Pad", "System", "Sell Price", "Dist (ly)", "Demand", "Updated"]
        )
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(18)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet(
            "QTableWidget { background:#080f18; alternate-background-color:#0a1520;"
            " gridline-color:#1e3a5a; border:1px solid #1e3a5a; font-size:12px; }"
            "QTableWidget::item { padding:1px 4px; }"
            "QHeaderView::section { background:#0d1a2a; color:#888888; border:none;"
            " padding:2px; font-size:12px; font-weight:bold; letter-spacing:1px; }"
            "QTableWidget::item:selected { background:#1a3a5a; color:#FFB347; }"
        )
        h = self._table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setToolTip("Click a Station or System cell to copy its name to the clipboard.")
        self._table.cellClicked.connect(self._on_results_cell_clicked)
        root.addWidget(self._table, 1)

        self._search_loading_spinner = BusySpinner(self)

    # ── Public API ────────────────────────────────────────────────────────

    def _on_results_cell_clicked(self, row: int, column: int) -> None:
        if column not in (0, 2):  # Station, System
            return
        item = self._table.item(row, column)
        if item is None or not item.text():
            return
        QApplication.clipboard().setText(item.text())
        label = "Station" if column == 0 else "System"
        self._status_label.setText(f"Copied {label.lower()} name: {item.text()}")

        station_item = self._table.item(row, 0)
        system_item  = self._table.item(row, 2)
        station_name = station_item.text() if station_item else ""
        system_name  = system_item.text() if system_item else ""
        if station_name and system_name:
            self.destination_selected.emit(
                system_name, station_name, self._commodity_edit.text().strip(), self._mode()
            )

    def refresh_commodity_names(self) -> None:
        """
        Repopulates the commodity search box's autocomplete list from
        commodity_names — built up from the player's own Market.json visits
        (which has real display names), so suggestions only ever show
        commodities we can actually resolve back to a display name. Cheap
        (a few hundred strings at most); safe to call often.
        """
        try:
            names = self._repo.get_all_commodity_display_names()
        except Exception:
            log.exception("Failed to load commodity display names")
            return
        model = self._commodity_completer.model()
        if isinstance(model, QStringListModel):
            model.setStringList(names)
        else:
            self._commodity_completer.setModel(QStringListModel(names, self._commodity_completer))

    def refresh(self, state, radius_ly: int) -> None:
        """Cheap, safe to call on every general refresh — location/radius only.
        Does NOT touch Trade Opportunities; call refresh_trade_opportunities()
        explicitly when a new Market event actually arrives."""
        self._last_state = state
        self._last_radius_ly = radius_ly
        self._my_power = getattr(state, "pp_power", None) or None
        self._system = (getattr(state, "system", None) or "").strip()
        self._ref_x = float(getattr(state, "system_x", 0.0) or 0.0)
        self._ref_y = float(getattr(state, "system_y", 0.0) or 0.0)
        self._ref_z = float(getattr(state, "system_z", 0.0) or 0.0)
        self._location_label.setText(f"Location: {self._system or '—'}")
        self._search_btn.setEnabled(bool(self._system))
        if radius_ly and self._range_spin.value() == 100 and radius_ly != 100:
            self._range_spin.setValue(int(radius_ly))

        self._refresh_cargo_destinations(state)

    def _refresh_cargo_destinations(self, state) -> None:
        cargo = getattr(state, "cargo_inventory", None) or []

        # Sum quantity per commodity — the same item can appear as multiple
        # entries (e.g. a regular stack plus a mission-tagged stack).
        qty_by_commodity: dict = {}
        display_by_commodity: dict = {}
        for c in cargo:
            if not isinstance(c, dict):
                continue
            raw_name = c.get("Name") or ""
            key = normalize_commodity_name(raw_name)
            if not key:
                continue
            qty_by_commodity[key] = qty_by_commodity.get(key, 0) + int(c.get("Count") or 0)
            display_by_commodity.setdefault(key, c.get("Name_Localised") or raw_name.title())

        rows = []
        for key, qty in qty_by_commodity.items():
            dest = self._cargo_destinations.get(key)
            if not dest:
                continue  # in cargo, but we never computed a known destination for it
            rows.append((display_by_commodity[key], qty, dest))

        if not rows:
            self._cargo_hdr.setVisible(False)
            self._cargo_table.setVisible(False)
            self._cargo_table.setRowCount(0)
            return

        self._cargo_hdr.setVisible(True)
        self._cargo_table.setVisible(True)
        self._cargo_table.setRowCount(len(rows))
        for row, (name, qty, dest) in enumerate(rows):
            name_item = QTableWidgetItem(name)
            qty_item = QTableWidgetItem(str(qty))
            dest_item = QTableWidgetItem(f"{dest['station_name']} ({dest['system_name']})")
            pad_item = QTableWidgetItem(dest.get("pad_size") or pad_size_hint(dest.get("station_type")))
            dist_item = QTableWidgetItem(f"{dest.get('distance_ly', 0.0):.1f}")
            price_item = QTableWidgetItem(f"{dest.get('sell_price', 0):,}")
            if pad_item.text() == "?":
                pad_item.setForeground(QColor("#888888"))
            for it in (qty_item, pad_item, dist_item, price_item):
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            self._cargo_table.setItem(row, 0, name_item)
            self._cargo_table.setItem(row, 1, qty_item)
            self._cargo_table.setItem(row, 2, dest_item)
            self._cargo_table.setItem(row, 3, pad_item)
            self._cargo_table.setItem(row, 4, dist_item)
            self._cargo_table.setItem(row, 5, price_item)

    def refresh_trade_opportunities(self, state, radius_ly: int, force: bool = False) -> None:
        """
        Call only when a new Market event has actually arrived (i.e. the
        commodity screen was just opened) — not on every general refresh.
        Runs the per-commodity price search on a background thread so a
        large station's market (dozens of commodities, one DB query each)
        never freezes the UI. force=True (manual Refresh button) bypasses
        the "already computed for this market visit" dedupe, since the
        underlying market_prices data keeps changing from live EDDN
        traffic while you're still docked.
        """
        items = getattr(state, "current_market_items", None) or []
        market_id = getattr(state, "current_market_id", None)
        station = getattr(state, "current_market_station", None) or ""

        if not items or not isinstance(market_id, int):
            self._trade_hdr.setVisible(False)
            self._trade_status_label.setVisible(False)
            self._trade_table.setVisible(False)
            self._trade_loading_spinner.stop()
            self._trade_refresh_btn.setVisible(False)
            self._trade_table.setRowCount(0)
            self._last_market_id_computed = None
            return

        if market_id == self._last_market_id_computed and not force:
            return  # already computed for this exact market visit

        if self._trade_thread and self._trade_thread.isRunning():
            return

        ref_x = float(getattr(state, "system_x", 0.0) or 0.0)
        ref_y = float(getattr(state, "system_y", 0.0) or 0.0)
        ref_z = float(getattr(state, "system_z", 0.0) or 0.0)

        self._trade_hdr.setVisible(True)
        self._trade_status_label.setVisible(True)
        self._trade_status_label.setText(f"Checking {station or 'current station'}'s commodities…")
        # Left visible but emptied (not hidden) — a hidden widget's layout
        # space collapses, which would leave the spinner nothing stable to
        # center itself on.
        self._trade_table.setVisible(True)
        self._trade_table.setRowCount(0)
        self._trade_refresh_btn.setVisible(True)
        self._trade_refresh_btn.setEnabled(False)
        self._trade_loading_spinner.start_over(self)

        self._last_market_id_computed = market_id
        self._trade_worker = _TradeOpportunityWorker(
            self._repo.db.db_path, items, market_id, station, ref_x, ref_y, ref_z, radius_ly,
        )
        self._trade_thread = QThread()
        self._trade_worker.moveToThread(self._trade_thread)
        self._trade_thread.started.connect(self._trade_worker.run)
        self._trade_worker.finished.connect(self._on_trade_opportunities_result)
        self._trade_worker.finished.connect(self._trade_thread.quit)
        self._trade_thread.start()

    def _on_refresh_trade_clicked(self) -> None:
        if self._last_state is not None:
            self.refresh_trade_opportunities(self._last_state, self._last_radius_ly, force=True)

    def _on_trade_opportunities_result(self, opportunities: list, station: str):
        self._trade_refresh_btn.setEnabled(True)
        self._last_trade_opportunities_raw = opportunities
        self._last_trade_station = station
        self._render_trade_opportunities()

    def _render_trade_opportunities(self) -> None:
        opportunities = self._last_trade_opportunities_raw or []
        station = self._last_trade_station

        # Merge (don't replace) — a destination remembered from an earlier
        # station visit must survive later visits to other stations, since
        # whatever's still in cargo from that earlier stop still needs it.
        # Enemy-PowerPlay systems are excluded before this merge too, so an
        # excluded destination is never remembered/recommended later either.
        # Re-applied (not just once) so toggling the checkbox off restores
        # a previously-excluded destination instead of it staying dropped.
        opportunities, enemy_excluded = self._filter_enemy_pp(opportunities)
        for o in opportunities:
            key = normalize_commodity_name(o.get("name") or "")
            if key:
                self._cargo_destinations[key] = o

        excluded_note = f" ({enemy_excluded} enemy-PowerPlay destination{'s' if enemy_excluded != 1 else ''} excluded)" if enemy_excluded else ""
        self._trade_status_label.setText(
            f"{station or 'Current station'}: {len(opportunities)} profitable "
            f"destination{'s' if len(opportunities) != 1 else ''} found.{excluded_note}"
        )
        self._trade_loading_spinner.stop()
        self._trade_table.setVisible(True)

        self._trade_table.setSortingEnabled(False)
        self._trade_table.setRowCount(len(opportunities))
        for row, o in enumerate(opportunities):
            name_item = QTableWidgetItem(o["name"])
            buy_item = _NumericTableWidgetItem(f"{o['buy_price']:,}", float(o["buy_price"]))
            stock_item = _NumericTableWidgetItem(f"{o.get('stock', 0):,}", float(o.get("stock", 0)))
            sell_item = _NumericTableWidgetItem(f"{o['sell_price']:,}", float(o["sell_price"]))
            dest_station_item = QTableWidgetItem(o.get("station_name") or "—")
            dest_system_item = QTableWidgetItem(o.get("system_name") or "—")
            pad_item = QTableWidgetItem(o.get("pad_size") or pad_size_hint(o.get("station_type")))
            dist_item = _NumericTableWidgetItem(f"{o['distance_ly']:.1f}", float(o["distance_ly"]))
            profit_item = _NumericTableWidgetItem(f"+{o['profit_pct']:.1f}%", float(o["profit_pct"]))
            profit_item.setForeground(QColor("#6BCB77"))
            if pad_item.text() == "?":
                pad_item.setForeground(QColor("#888888"))
                pad_item.setToolTip("Landing pad size unknown for this station type")
            for it in (buy_item, stock_item, sell_item, pad_item, dist_item, profit_item):
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            self._trade_table.setItem(row, 0, name_item)
            self._trade_table.setItem(row, 1, buy_item)
            self._trade_table.setItem(row, 2, stock_item)
            self._trade_table.setItem(row, 3, sell_item)
            self._trade_table.setItem(row, 4, dest_station_item)
            self._trade_table.setItem(row, 5, dest_system_item)
            self._trade_table.setItem(row, 6, pad_item)
            self._trade_table.setItem(row, 7, dist_item)
            self._trade_table.setItem(row, 8, profit_item)
        self._trade_table.setSortingEnabled(True)
        # Auto-sort best-profit-first by default — still click-sortable by
        # any column afterward like the search results table.
        self._trade_table.sortItems(8, Qt.SortOrder.DescendingOrder)

    def _on_trade_cell_clicked(self, row: int, column: int) -> None:
        if column not in (4, 5):  # Destination Station, Destination System
            return
        item = self._trade_table.item(row, column)
        if item and item.text():
            QApplication.clipboard().setText(item.text())

    def search_for(self, commodity_display_name: str, mode: str | None = None) -> None:
        """External entry point (e.g. from the Mining or Squadron tab) to
        search a specific commodity. mode="buy"/"sell" switches the search
        direction first; omitted leaves whatever was last selected."""
        if mode in ("buy", "sell"):
            idx = self._mode_combo.findData(mode)
            if idx >= 0:
                self._mode_combo.setCurrentIndex(idx)
        self._commodity_edit.setText(commodity_display_name)
        self._start_search()

    # ── Search ────────────────────────────────────────────────────────────

    def _on_mode_changed(self):
        if self._mode() == "buy":
            self._search_hdr.setText("MARKET — CHEAPEST BUY PRICE SEARCH")
            self._table.setHorizontalHeaderLabels(
                ["Station", "Pad", "System", "Buy Price", "Dist (ly)", "Stock", "Updated"]
            )
        else:
            self._search_hdr.setText("MARKET — BEST SELL PRICE SEARCH")
            self._table.setHorizontalHeaderLabels(
                ["Station", "Pad", "System", "Sell Price", "Dist (ly)", "Demand", "Updated"]
            )

    def _open_rare_goods_dialog(self) -> None:
        if self._rare_dialog is None:
            self._rare_dialog = _RareGoodsDialog(self)
        self._rare_dialog.refresh_results()
        self._rare_dialog.show()
        self._rare_dialog.raise_()
        self._rare_dialog.activateWindow()

    def _open_service_dialog(self, tags: list, label: str) -> None:
        key = ",".join(tags)
        dlg = self._service_dialogs.get(key)
        if dlg is None:
            dlg = _StationServiceDialog(self, tags, label)
            self._service_dialogs[key] = dlg
        dlg.refresh_results()
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _mode(self) -> str:
        return self._mode_combo.currentData() or "sell"

    def _start_search(self):
        raw = self._commodity_edit.text().strip()
        if not raw:
            self._status_label.setText("Enter a commodity name first.")
            return
        if not self._system:
            self._status_label.setText("No system location data yet — jump to a system first.")
            return

        near_name = self._near_edit.text().strip()
        if not near_name:
            self._run_market_search(raw, self._ref_x, self._ref_y, self._ref_z, self._system)
            return

        # Our own system_coords cache only has systems someone happened to
        # report via EDDN while we were listening — a perfectly real system
        # nobody's passed through recently comes up empty there even though
        # it exists. Try that first (instant, local), then fall back to a
        # background EDSM lookup rather than rejecting it outright.
        coords = self._repo.get_system_coords_for_names([near_name])
        found = coords.get(near_name)
        if found:
            self._run_market_search(raw, found[0], found[1], found[2], near_name)
            return

        self._search_btn.setEnabled(False)
        self._status_label.setText(f"Looking up \"{near_name}\" via EDSM…")
        self._table.setRowCount(0)
        self._search_loading_spinner.start_over(self)
        self._coords_worker = _NearSystemCoordsWorker(self._repo.db.db_path, near_name)
        self._coords_thread = QThread()
        self._coords_worker.moveToThread(self._coords_thread)
        self._coords_thread.started.connect(self._coords_worker.run)
        self._coords_worker.finished.connect(lambda c, n: self._on_near_coords_resolved(c, n, raw))
        self._coords_worker.finished.connect(self._coords_thread.quit)
        self._coords_thread.start()

    def _on_near_coords_resolved(self, coords, system_name: str, raw: str) -> None:
        if not coords:
            self._search_btn.setEnabled(True)
            self._search_loading_spinner.stop()
            self._status_label.setText(
                f"Unknown system \"{system_name}\" — not found locally or via EDSM. Check "
                "spelling/capitalization, or leave \"Near\" blank to search near your current location."
            )
            return
        self._run_market_search(raw, coords[0], coords[1], coords[2], system_name)

    def _run_market_search(self, raw: str, ref_x: float, ref_y: float, ref_z: float, near_label: str) -> None:
        commodity = normalize_commodity_name(raw)
        radius = self._range_spin.value()
        buy_mode = self._mode() == "buy"

        self._last_near_label = near_label
        self._search_btn.setEnabled(False)
        self._status_label.setText(f"Searching for {raw} near {near_label}…")
        self._table.setRowCount(0)
        self._search_loading_spinner.start_over(self)

        self._search_worker = _MarketSearchWorker(
            self._repo.db.db_path, commodity, raw, ref_x, ref_y, ref_z, radius, buy_mode,
        )
        self._search_thread = QThread()
        self._search_worker.moveToThread(self._search_thread)
        self._search_thread.started.connect(self._search_worker.run)
        self._search_worker.finished.connect(self._on_search_finished)
        self._search_worker.finished.connect(self._search_thread.quit)
        self._search_thread.start()

    def _on_search_finished(self, results: list, raw: str, radius: int, buy_mode: bool) -> None:
        self._search_btn.setEnabled(True)
        self._search_loading_spinner.stop()
        self._last_results = results
        self._last_search_desc = (raw, radius, buy_mode)
        self._render_results()

    def _apply_pad_filter(self) -> None:
        if self._last_results is not None:
            self._render_results()

    def _on_exclude_enemy_pp_toggled(self) -> None:
        if self._last_results is not None:
            self._render_results()
        self._render_trade_opportunities()

    def _on_faction_only_toggled(self) -> None:
        if self._last_results is not None:
            self._render_results()

    def _filter_faction_only(self, results: list) -> list:
        """Same idea as Trade Route Loop Planner's equivalent checkbox —
        drops results at stations not controlled by the squadron's aligned
        faction. Resolved on demand rather than cached in refresh() since
        it's only needed when this checkbox is actually on."""
        if not self._faction_only_check.isChecked():
            return results
        squadron_faction_name = None
        try:
            overview = self._repo.get_player_faction_overview()
            squadron_faction_name = overview["faction_name"] if overview else None
        except Exception:
            log.exception("Failed to load squadron faction name for market filter")
        if not squadron_faction_name:
            return results
        target = squadron_faction_name.strip().lower()
        return [r for r in results if (r.get("station_faction") or "").strip().lower() == target]

    def _filter_enemy_pp(self, results: list) -> tuple[list, int]:
        """Drops entries in systems currently controlled by a Power other
        than the player's own pledged one (from EDSM's daily PowerPlay
        dump) — shared by the manual search and Trade Opportunities so one
        checkbox governs both. A system with no known PowerPlay presence is
        left in, not treated as enemy. Returns (kept, excluded_count)."""
        if not self._exclude_enemy_pp_check.isChecked() or not self._my_power or not self._edsm_powerplay:
            return results, 0
        kept = []
        excluded = 0
        for r in results:
            controller = self._edsm_powerplay.get_controller_by_name(r.get("system_name"))
            controlling_power = (controller or {}).get("power") or ""
            if controlling_power and controlling_power != self._my_power:
                excluded += 1
            else:
                kept.append(r)
        return kept, excluded

    def _cargo_qty_of(self, commodity_key: str) -> int:
        """Current cargo hold quantity for a normalized commodity name —
        used for the bulk-sale-price warning (selling past ~25% of a
        station's demand tapers the price down for the excess)."""
        cargo = getattr(self._last_state, "cargo_inventory", None) or []
        total = 0
        for c in cargo:
            if not isinstance(c, dict):
                continue
            if normalize_commodity_name(c.get("Name") or "") == commodity_key:
                total += int(c.get("Count") or 0)
        return total

    def _render_results(self) -> None:
        results = self._last_results or []
        raw, radius, buy_mode = self._last_search_desc

        min_pad = self._pad_filter_combo.currentData()
        if min_pad:
            rank = {"S": 1, "M": 2, "L": 3}
            min_rank = rank[min_pad]
            results = [
                r for r in results
                if (r.get("pad_size") or pad_size_hint(r.get("station_type"))) not in rank
                or rank[r.get("pad_size") or pad_size_hint(r.get("station_type"))] >= min_rank
            ]

        results, enemy_excluded = self._filter_enemy_pp(results)
        results = self._filter_faction_only(results)

        verb = "buying" if buy_mode else "selling"
        near_label = self._last_near_label or self._system
        excluded_note = f" ({enemy_excluded} enemy-PowerPlay system{'s' if enemy_excluded != 1 else ''} excluded)" if enemy_excluded else ""
        self._status_label.setText(
            f"Found {len(results)} station{'s' if len(results) != 1 else ''} "
            f"{verb} {raw} within {radius} ly of {near_label}.{excluded_note}"
        )
        cargo_qty = self._cargo_qty_of(normalize_commodity_name(raw)) if not buy_mode else 0

        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(results))
        for row, r in enumerate(results):
            station_item = QTableWidgetItem(r.get("station_name") or "—")
            pad_item = QTableWidgetItem(r.get("pad_size") or pad_size_hint(r.get("station_type")))
            system_item = QTableWidgetItem(r.get("system_name") or "—")
            price = r.get("buy_price") if buy_mode else r.get("sell_price")
            price_value = float(price or 0)
            price_item = _NumericTableWidgetItem(f"{price or 0:,}", price_value)
            dist_value = float(r.get("distance_ly", 0.0) or 0.0)
            dist_item = _NumericTableWidgetItem(f"{dist_value:.1f}", dist_value)
            count_value = float((r.get("stock") if buy_mode else r.get("demand")) or 0)
            count_item = _NumericTableWidgetItem(str(int(count_value)), count_value)
            updated_text, updated_age = _format_relative_time(r.get("last_updated") or "")
            updated_item = _NumericTableWidgetItem(updated_text, updated_age)
            if pad_item.text() == "?":
                pad_item.setForeground(QColor("#888888"))
                pad_item.setToolTip("Landing pad size unknown for this station type")

            # Selling more than ~25% of a station's demand tapers the price
            # down per unit past that point (real game mechanic).
            if not buy_mode and cargo_qty > 0 and count_value > 0 and cargo_qty > 0.25 * count_value:
                warn = (
                    f"Your {cargo_qty} in cargo is {cargo_qty / count_value * 100:.0f}% of the "
                    f"{int(count_value)} demand here — expect a lower price than shown for the excess."
                )
                count_item.setForeground(QColor("#FF8C00"))
                count_item.setToolTip(warn)
                price_item.setForeground(QColor("#FF8C00"))
                price_item.setToolTip(warn)

            for it in (pad_item, price_item, dist_item, count_item, updated_item):
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            self._table.setItem(row, 0, station_item)
            self._table.setItem(row, 1, pad_item)
            self._table.setItem(row, 2, system_item)
            self._table.setItem(row, 3, price_item)
            self._table.setItem(row, 4, dist_item)
            self._table.setItem(row, 5, count_item)
            self._table.setItem(row, 6, updated_item)
        self._table.setSortingEnabled(True)


class _RareGoodsDialog(QDialog):
    """
    Non-modal detail window (stays open, movable, independent of tab
    switching) listing every real rare good the reference table knows
    about that EDDN has actually reported data for at its one true
    canonical station — see Repository.get_known_rare_goods.
    """

    def __init__(self, panel: "MarketPanel"):
        super().__init__(None)
        self.setStyleSheet("QDialog { background:#080f18; color:#c8c8c8; }")
        self._panel = panel
        self._all_rows: list = []
        self.setWindowTitle("Rare Goods")
        self.resize(900, 500)

        layout = QVBoxLayout(self)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Search:"))
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Rare good name…")
        self._search_edit.setStyleSheet("background:#0a1520; color:#c8c8c8; border:1px solid #1e3a5a;")
        self._search_edit.textChanged.connect(self._apply_filter)
        search_row.addWidget(self._search_edit, 1)
        layout.addLayout(search_row)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color:#888888; font-size:11px; background:transparent; border:none;")
        layout.addWidget(self._status_label)

        self._table = QTableWidget()
        self._table.setColumnCount(7)
        self._table.setHorizontalHeaderLabels(
            ["Rare Good", "Station", "Pad", "System", "Dist (ly)", "Available", "Updated"]
        )
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet(
            "QTableWidget { background:#080f18; alternate-background-color:#0a1520;"
            " gridline-color:#1e3a5a; border:1px solid #1e3a5a; }"
            "QHeaderView::section { background:#0d1a2a; color:#888888; border:none;"
            " padding:3px; font-size:12px; font-weight:bold; letter-spacing:1px; }"
            "QTableWidget::item:selected { background:#1a3a5a; color:#FFB347; }"
        )
        h = self._table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setToolTip("Click a Station or System cell to copy its name to the clipboard.")
        self._table.cellClicked.connect(self._on_cell_clicked)
        layout.addWidget(self._table, 1)

        note = QLabel(
            "Only rare goods EDDN has actually reported data for at their real canonical "
            "station are listed here — no data yet means no row, not a guess."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#7a7a7a; font-size:11px; background:transparent; border:none;")
        layout.addWidget(note)

    def refresh_results(self) -> None:
        rare_table = self._panel._rare_table
        if rare_table is None:
            self._all_rows = []
        else:
            self._all_rows = self._panel._repo.get_known_rare_goods(
                rare_table.all(), self._panel._ref_x, self._panel._ref_y, self._panel._ref_z,
            )
        self._apply_filter()

    def _apply_filter(self) -> None:
        query = self._search_edit.text().strip().lower()
        rows = [
            r for r in self._all_rows
            if not query or query in (r.get("rare_name") or "").lower()
        ]
        rows.sort(key=lambda r: (r.get("distance_ly") is None, r.get("distance_ly") or 0.0))

        self._status_label.setText(f"{len(rows)} of {len(self._all_rows)} known rare goods.")

        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(rows))
        for row, r in enumerate(rows):
            name_item = QTableWidgetItem(r.get("rare_name") or "—")
            station_item = QTableWidgetItem(r.get("station_name") or "—")
            pad_item = QTableWidgetItem(r.get("pad_size") or pad_size_hint(r.get("station_type")))
            system_item = QTableWidgetItem(r.get("system_name") or "—")
            dist_value = r.get("distance_ly")
            dist_text = f"{dist_value:.1f}" if isinstance(dist_value, (int, float)) else "—"
            dist_item = _NumericTableWidgetItem(dist_text, dist_value if isinstance(dist_value, (int, float)) else float("inf"))
            stock_value = float(r.get("stock") or 0)
            stock_item = _NumericTableWidgetItem(str(int(stock_value)), stock_value)
            updated_text, updated_age = _format_relative_time(r.get("last_updated") or "")
            updated_item = _NumericTableWidgetItem(updated_text, updated_age)
            if pad_item.text() == "?":
                pad_item.setForeground(QColor("#888888"))
                pad_item.setToolTip("Landing pad size unknown for this station type")
            for it in (pad_item, dist_item, stock_item, updated_item):
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            self._table.setItem(row, 0, name_item)
            self._table.setItem(row, 1, station_item)
            self._table.setItem(row, 2, pad_item)
            self._table.setItem(row, 3, system_item)
            self._table.setItem(row, 4, dist_item)
            self._table.setItem(row, 5, stock_item)
            self._table.setItem(row, 6, updated_item)
        self._table.setSortingEnabled(True)

    def _on_cell_clicked(self, row: int, column: int) -> None:
        if column not in (1, 3):  # Station, System
            return
        item = self._table.item(row, column)
        if item and item.text():
            QApplication.clipboard().setText(item.text())


class _StationServiceDialog(QDialog):
    """
    Non-modal detail window listing every known station (from our own past
    dockings) offering a given set of StationServices tags, closest first —
    same pattern as _RareGoodsDialog, generalized to any Concourse/ship
    service rather than a specific commodity list.
    """

    def __init__(self, panel: "MarketPanel", tags: list, label: str):
        super().__init__(None)
        self.setStyleSheet("QDialog { background:#080f18; color:#c8c8c8; }")
        self._panel = panel
        self._tags = tags
        self.setWindowTitle(f"Market — {label}")
        self.resize(700, 450)

        layout = QVBoxLayout(self)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color:#888888; font-size:11px; background:transparent; border:none;")
        layout.addWidget(self._status_label)

        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(["Station", "Pad", "System", "Dist (ly)", "Last Visited"])
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet(
            "QTableWidget { background:#080f18; alternate-background-color:#0a1520;"
            " gridline-color:#1e3a5a; border:1px solid #1e3a5a; }"
            "QHeaderView::section { background:#0d1a2a; color:#888888; border:none;"
            " padding:3px; font-size:12px; font-weight:bold; letter-spacing:1px; }"
            "QTableWidget::item:selected { background:#1a3a5a; color:#FFB347; }"
        )
        h = self._table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setToolTip("Click a Station or System cell to copy its name to the clipboard.")
        self._table.cellClicked.connect(self._on_cell_clicked)
        layout.addWidget(self._table, 1)

        note = QLabel(
            "Bounded to stations you've personally docked at — Frontier's journal doesn't "
            "expose station services for anywhere you haven't visited. Services can change "
            "over time (BGS/security/faction shifts) — check \"Last Visited\" before flying somewhere."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#7a7a7a; font-size:11px; background:transparent; border:none;")
        layout.addWidget(note)

    def refresh_results(self) -> None:
        rows = self._panel._repo.find_stations_with_service(
            self._panel._ref_x, self._panel._ref_y, self._panel._ref_z, self._tags,
        )
        self._status_label.setText(f"{len(rows)} known station{'s' if len(rows) != 1 else ''}.")

        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(rows))
        for row, r in enumerate(rows):
            station_item = QTableWidgetItem(r.get("station_name") or "—")
            pad_item = QTableWidgetItem(r.get("pad_size") or pad_size_hint(r.get("station_type")))
            system_item = QTableWidgetItem(r.get("system_name") or "—")
            dist_value = r.get("distance_ly")
            dist_text = f"{dist_value:.1f}" if isinstance(dist_value, (int, float)) else "—"
            dist_item = _NumericTableWidgetItem(dist_text, dist_value if isinstance(dist_value, (int, float)) else float("inf"))
            visited_text, visited_age = _format_relative_time(r.get("last_visited") or "")
            visited_item = _NumericTableWidgetItem(visited_text, visited_age)
            if pad_item.text() == "?":
                pad_item.setForeground(QColor("#888888"))
                pad_item.setToolTip("Landing pad size unknown for this station type")
            for it in (pad_item, dist_item, visited_item):
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            self._table.setItem(row, 0, station_item)
            self._table.setItem(row, 1, pad_item)
            self._table.setItem(row, 2, system_item)
            self._table.setItem(row, 3, dist_item)
            self._table.setItem(row, 4, visited_item)
        self._table.setSortingEnabled(True)

    def _on_cell_clicked(self, row: int, column: int) -> None:
        if column not in (0, 2):  # Station, System
            return
        item = self._table.item(row, column)
        if item and item.text():
            QApplication.clipboard().setText(item.text())
