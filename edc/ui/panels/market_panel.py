"""Market panel — best sell price search across the galaxy-wide EDDN commodity feed."""
from __future__ import annotations

import logging
import re
from typing import Optional

from PyQt6.QtCore import Qt, QObject, QThread, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QSpinBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QFrame,
)

from edc.core.station_pads import pad_size_hint

log = logging.getLogger(__name__)

_CARD_STYLE = "QFrame { background:#0d1a2a; border:1px solid #1e3a5a; border-radius:5px; }"
_HDR_STYLE = "color:#555555; font-size:10px; font-weight:bold; letter-spacing:1px; background:transparent; border:none;"
_LABEL_STYLE = "background:transparent; border:none; color:#c8c8c8;"


def normalize_commodity_name(name: str) -> str:
    """
    EDDN/journal commodity symbols are lowercase, no spaces/punctuation
    (e.g. "Low Temperature Diamonds" -> "lowtemperaturediamonds"). Applied
    to whatever the user types so free-text search matches stored data.
    """
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _compute_trade_opportunities(repo, items, market_id, ref_x, ref_y, ref_z, radius_ly):
    """
    Runs one search_market_prices query per purchasable commodity in the
    current market. This can mean dozens of sequential DB queries for a
    large station — deliberately kept off the UI thread (see
    _TradeOpportunityWorker) so it never freezes the app.
    """
    opportunities = []
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
        try:
            results = repo.search_market_prices(
                commodity, ref_x, ref_y, ref_z, float(radius_ly),
                exclude_market_id=market_id,
            )
        except Exception:
            log.exception("Trade opportunity search failed for %s", commodity)
            continue
        if not results:
            continue
        best = results[0]
        sell_price = best.get("sell_price") or 0
        if sell_price <= 0:
            continue
        profit_pct = (sell_price - buy_price) / buy_price * 100.0
        if profit_pct <= 0:
            continue
        opportunities.append({
            "name": item.get("name"),
            "buy_price": buy_price,
            "stock": stock,
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


class MarketPanel(QWidget):
    """
    Owns all widgets and refresh logic for the Market tab.
    Receives state via refresh(state, radius_ly). Unlike most panels this
    one is constructed with a Repository directly — the manual search is a
    single local SQLite query (fast, synchronous). Trade Opportunities is
    not — it's one query per commodity in the current market, so that runs
    on a background thread (see refresh_trade_opportunities) rather than
    blocking the UI.
    """

    def __init__(self, repo, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._system: str = ""
        self._ref_x: float = 0.0
        self._ref_y: float = 0.0
        self._ref_z: float = 0.0
        self._trade_thread: Optional[QThread] = None
        self._trade_worker: Optional[_TradeOpportunityWorker] = None
        self._last_market_id_computed: Optional[int] = None

        # Remembers "where to sell X" per commodity across station visits —
        # merged (not replaced) on each new Trade Opportunities computation,
        # so a destination found at an earlier station isn't lost once you
        # undock and the current-market data clears.
        self._cargo_destinations: dict = {}

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
            " color:#c8c8c8; gridline-color:#1e3a1e; border:1px solid #2a5a2a; font-size:10px; }"
            "QTableWidget::item { padding:1px 4px; }"
            "QHeaderView::section { background:#0d1a0d; color:#6BCB77; border:none;"
            " padding:2px; font-size:10px; font-weight:bold; letter-spacing:1px; }"
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

        hdr = QLabel("MARKET — BEST SELL PRICE SEARCH")
        hdr.setStyleSheet(_HDR_STYLE)
        search_layout.addWidget(hdr)

        self._location_label = QLabel("Location: —")
        self._location_label.setStyleSheet(_LABEL_STYLE)
        search_layout.addWidget(self._location_label)

        row = QHBoxLayout()
        row.setSpacing(8)

        self._commodity_edit = QLineEdit()
        self._commodity_edit.setPlaceholderText("Commodity (e.g. Gold, Painite, Low Temperature Diamonds...)")
        self._commodity_edit.setStyleSheet("background:#0a1520; color:#c8c8c8; border:1px solid #1e3a5a;")
        self._commodity_edit.returnPressed.connect(self._start_search)

        range_label = QLabel("Range:")
        range_label.setStyleSheet(_LABEL_STYLE)
        self._range_spin = QSpinBox()
        self._range_spin.setRange(10, 5000)
        self._range_spin.setSingleStep(10)
        self._range_spin.setValue(100)
        self._range_spin.setSuffix(" ly")
        self._range_spin.setStyleSheet("background:#0a1520; color:#c8c8c8; border:1px solid #1e3a5a;")

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
        row.addWidget(self._search_btn)
        search_layout.addLayout(row)

        note = QLabel(
            "Sourced from EDDN's live galaxy-wide commodity feed — other commanders' "
            "recent market visits, not just your own. Prices can go stale between visits; "
            "check \"Updated\" before flying somewhere."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#555555; font-size:9px; background:transparent; border:none;")
        search_layout.addWidget(note)

        root.addWidget(search_frame)

        # ── Trade opportunities (current market) ────────────────────────
        self._trade_hdr = QLabel("TRADE OPPORTUNITIES — CURRENT MARKET")
        self._trade_hdr.setStyleSheet(_HDR_STYLE)
        self._trade_hdr.setVisible(False)
        root.addWidget(self._trade_hdr)

        self._trade_status_label = QLabel("")
        self._trade_status_label.setStyleSheet("color:#888888; font-size:10px; background:transparent;")
        self._trade_status_label.setVisible(False)
        root.addWidget(self._trade_status_label)

        self._trade_table = QTableWidget()
        self._trade_table.setColumnCount(8)
        self._trade_table.setHorizontalHeaderLabels(
            ["Commodity", "Buy Here", "Stock", "Best Sell", "Destination", "Pad", "Dist (ly)", "Profit %"]
        )
        self._trade_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._trade_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._trade_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._trade_table.verticalHeader().setVisible(False)
        self._trade_table.verticalHeader().setDefaultSectionSize(18)
        self._trade_table.setAlternatingRowColors(True)
        self._trade_table.setStyleSheet(
            "QTableWidget { background:#080f18; alternate-background-color:#0a1520;"
            " color:#c8c8c8; gridline-color:#1e3a5a; border:1px solid #1e3a5a; font-size:10px; }"
            "QTableWidget::item { padding:1px 4px; }"
            "QHeaderView::section { background:#0d1a2a; color:#888888; border:none;"
            " padding:2px; font-size:10px; font-weight:bold; letter-spacing:1px; }"
            "QTableWidget::item:selected { background:#1a3a5a; color:#FFB347; }"
        )
        th = self._trade_table.horizontalHeader()
        th.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        th.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        th.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        th.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        th.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        th.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        th.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        th.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        self._trade_table.setVisible(False)
        root.addWidget(self._trade_table, 1)

        # ── Status + results ────────────────────────────────────────────
        self._status_label = QLabel("Enter a commodity and press Search.")
        self._status_label.setStyleSheet("color:#888888; font-size:10px; background:transparent;")
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
            " color:#c8c8c8; gridline-color:#1e3a5a; border:1px solid #1e3a5a; font-size:10px; }"
            "QTableWidget::item { padding:1px 4px; }"
            "QHeaderView::section { background:#0d1a2a; color:#888888; border:none;"
            " padding:2px; font-size:10px; font-weight:bold; letter-spacing:1px; }"
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
        root.addWidget(self._table, 1)

    # ── Public API ────────────────────────────────────────────────────────

    def refresh(self, state, radius_ly: int) -> None:
        """Cheap, safe to call on every general refresh — location/radius only.
        Does NOT touch Trade Opportunities; call refresh_trade_opportunities()
        explicitly when a new Market event actually arrives."""
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

    def refresh_trade_opportunities(self, state, radius_ly: int) -> None:
        """
        Call only when a new Market event has actually arrived (i.e. the
        commodity screen was just opened) — not on every general refresh.
        Runs the per-commodity price search on a background thread so a
        large station's market (dozens of commodities, one DB query each)
        never freezes the UI.
        """
        items = getattr(state, "current_market_items", None) or []
        market_id = getattr(state, "current_market_id", None)
        station = getattr(state, "current_market_station", None) or ""

        if not items or not isinstance(market_id, int):
            self._trade_hdr.setVisible(False)
            self._trade_status_label.setVisible(False)
            self._trade_table.setVisible(False)
            self._trade_table.setRowCount(0)
            self._last_market_id_computed = None
            return

        if market_id == self._last_market_id_computed:
            return  # already computed for this exact market visit

        if self._trade_thread and self._trade_thread.isRunning():
            return

        ref_x = float(getattr(state, "system_x", 0.0) or 0.0)
        ref_y = float(getattr(state, "system_y", 0.0) or 0.0)
        ref_z = float(getattr(state, "system_z", 0.0) or 0.0)

        self._trade_hdr.setVisible(True)
        self._trade_status_label.setVisible(True)
        self._trade_status_label.setText(f"Checking {station or 'current station'}'s commodities…")
        self._trade_table.setVisible(True)

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

    def _on_trade_opportunities_result(self, opportunities: list, station: str):
        # Merge (don't replace) — a destination remembered from an earlier
        # station visit must survive later visits to other stations, since
        # whatever's still in cargo from that earlier stop still needs it.
        for o in opportunities:
            key = normalize_commodity_name(o.get("name") or "")
            if key:
                self._cargo_destinations[key] = o

        self._trade_status_label.setText(
            f"{station or 'Current station'}: {len(opportunities)} profitable "
            f"destination{'s' if len(opportunities) != 1 else ''} found."
        )

        self._trade_table.setRowCount(len(opportunities))
        for row, o in enumerate(opportunities):
            name_item = QTableWidgetItem(o["name"])
            buy_item = QTableWidgetItem(f"{o['buy_price']:,}")
            stock_item = QTableWidgetItem(f"{o.get('stock', 0):,}")
            sell_item = QTableWidgetItem(f"{o['sell_price']:,}")
            dest_item = QTableWidgetItem(f"{o['station_name']} ({o['system_name']})")
            pad_item = QTableWidgetItem(o.get("pad_size") or pad_size_hint(o.get("station_type")))
            dist_item = QTableWidgetItem(f"{o['distance_ly']:.1f}")
            profit_item = QTableWidgetItem(f"+{o['profit_pct']:.1f}%")
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
            self._trade_table.setItem(row, 4, dest_item)
            self._trade_table.setItem(row, 5, pad_item)
            self._trade_table.setItem(row, 6, dist_item)
            self._trade_table.setItem(row, 7, profit_item)

    def search_for(self, commodity_display_name: str) -> None:
        """External entry point (e.g. from the Mining tab) to search a specific commodity."""
        self._commodity_edit.setText(commodity_display_name)
        self._start_search()

    # ── Search ────────────────────────────────────────────────────────────

    def _start_search(self):
        raw = self._commodity_edit.text().strip()
        if not raw:
            self._status_label.setText("Enter a commodity name first.")
            return
        if not self._system:
            self._status_label.setText("No system location data yet — jump to a system first.")
            return

        commodity = normalize_commodity_name(raw)
        radius = self._range_spin.value()

        try:
            results = self._repo.search_market_prices(
                commodity, self._ref_x, self._ref_y, self._ref_z, float(radius)
            )
        except Exception:
            log.exception("Market price search failed")
            self._status_label.setText("Search failed — see log.")
            return

        self._status_label.setText(
            f"Found {len(results)} station{'s' if len(results) != 1 else ''} "
            f"selling {raw} within {radius} ly."
        )
        self._table.setRowCount(len(results))
        for row, r in enumerate(results):
            station_item = QTableWidgetItem(r.get("station_name") or "—")
            pad_item = QTableWidgetItem(r.get("pad_size") or pad_size_hint(r.get("station_type")))
            system_item = QTableWidgetItem(r.get("system_name") or "—")
            price_item = QTableWidgetItem(f"{r.get('sell_price', 0):,}")
            dist_item = QTableWidgetItem(f"{r.get('distance_ly', 0.0):.1f}")
            demand_item = QTableWidgetItem(str(r.get("demand") or 0))
            updated_item = QTableWidgetItem(str(r.get("last_updated") or "—"))
            if pad_item.text() == "?":
                pad_item.setForeground(QColor("#888888"))
                pad_item.setToolTip("Landing pad size unknown for this station type")
            for it in (pad_item, price_item, dist_item, demand_item):
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            self._table.setItem(row, 0, station_item)
            self._table.setItem(row, 1, pad_item)
            self._table.setItem(row, 2, system_item)
            self._table.setItem(row, 3, price_item)
            self._table.setItem(row, 4, dist_item)
            self._table.setItem(row, 5, demand_item)
            self._table.setItem(row, 6, updated_item)
