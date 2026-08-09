"""Trade Route Loop Planner — finds A<->B round trips (buy X at A, sell at
B; buy Y at B, sell at A) within a radius of your current location. See
docs/superpowers/specs/2026-08-09-trade-route-loop-planner-design.md.
"""
from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import Qt, QObject, QThread, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSpinBox, QComboBox, QCheckBox, QTableWidget, QTableWidgetItem, QHeaderView, QFrame,
)

from edc.core.trade_routes import find_trade_loops
from edc.ui.busy_spinner import BusySpinner
from edc.ui.panels.market_panel import _NumericTableWidgetItem

log = logging.getLogger(__name__)

_CARD_STYLE = "QFrame { background:#0d1a2a; border:1px solid #1e3a5a; border-radius:5px; }"
_LABEL_STYLE = "background:transparent; border:none; color:#c8c8c8;"
_PAD_RANK = {"S": 1, "M": 2, "L": 3}


class _TradeRouteWorker(QObject):
    """
    Opens its own SQLite connection per the project's cross-thread rule.
    The station-pairing search is O(N^2) over stations within radius —
    bounded by the radius itself (not the whole galaxy) and by
    find_trade_loops' max_results cap, but still real work, hence its own
    thread rather than the UI thread (same reasoning as every other
    search in Market/Mining).
    """
    finished = pyqtSignal(list, str)  # (loops, error)

    def __init__(self, db_path, x, y, z, radius_ly, cargo_capacity,
                 exclude_enemy_pp, my_power, edsm_powerplay,
                 faction_only, squadron_faction_name, required_pad):
        super().__init__()
        self._db_path = db_path
        self._x, self._y, self._z = x, y, z
        self._radius_ly = radius_ly
        self._cargo_capacity = cargo_capacity
        self._exclude_enemy_pp = exclude_enemy_pp
        self._my_power = my_power
        self._edsm_powerplay = edsm_powerplay
        self._faction_only = faction_only
        self._squadron_faction_name = squadron_faction_name
        self._required_pad = required_pad

    def run(self):
        from persistence.database import Database
        from persistence.repository import Repository

        db = Database(self._db_path)
        try:
            repo = Repository(db)
            stations = repo.get_market_snapshot_in_radius(self._x, self._y, self._z, self._radius_ly)

            if self._exclude_enemy_pp and self._my_power and self._edsm_powerplay:
                stations = {
                    mid: s for mid, s in stations.items()
                    if not self._is_enemy_pp(s["system_name"])
                }

            if self._faction_only and self._squadron_faction_name:
                stations = {
                    mid: s for mid, s in stations.items()
                    if (s.get("controlling_faction") or "").strip().lower()
                    == self._squadron_faction_name.strip().lower()
                }

            if self._required_pad in _PAD_RANK:
                # Only drop a station whose pad is CONFIRMED too small —
                # "?" (unknown) stays in rather than being wrongly excluded.
                min_rank = _PAD_RANK[self._required_pad]
                stations = {
                    mid: s for mid, s in stations.items()
                    if s["pad_size"] not in _PAD_RANK or _PAD_RANK[s["pad_size"]] >= min_rank
                }

            loops = find_trade_loops(stations, self._cargo_capacity)

            display_names = repo.get_commodity_display_name_map()
            for loop in loops:
                for leg in (loop["leg_a_to_b"], loop["leg_b_to_a"]):
                    leg["commodity_display"] = display_names.get(leg["commodity"], leg["commodity"].title())
        except Exception as exc:
            log.exception("Trade route search failed")
            self.finished.emit([], str(exc))
            return
        finally:
            db.close()
        self.finished.emit(loops, "")

    def _is_enemy_pp(self, system_name: str) -> bool:
        controller = self._edsm_powerplay.get_controller_by_name(system_name)
        controlling_power = (controller or {}).get("power") or ""
        return bool(controlling_power) and controlling_power != self._my_power


class TradeRoutePanel(QWidget):
    """Owns all widgets and refresh logic for the Trade Routes tab.
    Receives state via refresh(state); manual search only (no
    auto-refresh — the heaviest computation of any search in this app)."""

    def __init__(self, repo, edsm_powerplay=None, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._edsm_powerplay = edsm_powerplay
        self._system: str = ""
        self._ref_x = self._ref_y = self._ref_z = 0.0
        self._cargo_capacity: Optional[int] = None
        self._my_power: Optional[str] = None
        self._thread: Optional[QThread] = None
        self._worker: Optional[_TradeRouteWorker] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 8)
        root.setSpacing(6)

        frame = QFrame()
        frame.setStyleSheet(_CARD_STYLE)
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(8, 6, 8, 8)
        fl.setSpacing(6)

        hdr = QLabel("TRADE ROUTE LOOP PLANNER")
        hdr.setStyleSheet("color:#555555; font-size:12px; font-weight:bold; letter-spacing:1px; background:transparent; border:none;")
        fl.addWidget(hdr)

        note = QLabel(
            "Finds round trips near your current location: buy commodity X cheap at Station A, "
            "sell it at Station B, buy a different commodity at B, sell it back at A."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#555555; font-size:11px; background:transparent; border:none;")
        fl.addWidget(note)

        self._location_label = QLabel("Location: —")
        self._location_label.setStyleSheet(_LABEL_STYLE)
        fl.addWidget(self._location_label)

        self._cargo_label = QLabel("Cargo capacity: unknown (fly at least once this session)")
        self._cargo_label.setStyleSheet(_LABEL_STYLE)
        fl.addWidget(self._cargo_label)

        row = QHBoxLayout()
        row.setSpacing(8)
        range_label = QLabel("Range:")
        range_label.setStyleSheet(_LABEL_STYLE)
        self._range_spin = QSpinBox()
        self._range_spin.setRange(10, 500)
        self._range_spin.setSingleStep(10)
        self._range_spin.setValue(50)
        self._range_spin.setSuffix(" ly")
        self._range_spin.setStyleSheet("background:#0a1520; color:#c8c8c8; border:1px solid #1e3a5a;")
        self._range_spin.setToolTip(
            "Kept tighter than Market's search range — pairing every station up is much more "
            "expensive than a single-commodity lookup, so a smaller radius keeps it fast."
        )
        pad_label = QLabel("Min pad:")
        pad_label.setStyleSheet(_LABEL_STYLE)
        self._pad_filter_combo = QComboBox()
        self._pad_filter_combo.addItem("Any", None)
        self._pad_filter_combo.addItem("Medium+", "M")
        self._pad_filter_combo.addItem("Large only", "L")
        self._pad_filter_combo.setStyleSheet("background:#0a1520; color:#c8c8c8; border:1px solid #1e3a5a;")
        self._pad_filter_combo.setToolTip(
            "Manual, like Market's equivalent filter — set to whatever your current ship needs. "
            "Kept manual (not auto-detected from your ship) so a future ship the app doesn't "
            "recognize can't silently misfilter results."
        )
        self._search_btn = QPushButton("Search")
        self._search_btn.setStyleSheet(
            "QPushButton { background:#1a3a5a; color:#FFB347; border:1px solid #2a5a8a;"
            " border-radius:3px; padding:3px 12px; font-weight:bold; }"
            "QPushButton:hover { background:#2a5a8a; }"
            "QPushButton:disabled { background:#111; color:#555; border-color:#333; }"
        )
        self._search_btn.clicked.connect(self._start_search)
        row.addWidget(range_label)
        row.addWidget(self._range_spin)
        row.addWidget(pad_label)
        row.addWidget(self._pad_filter_combo)
        row.addWidget(self._search_btn)
        row.addStretch(1)
        fl.addLayout(row)

        check_row = QHBoxLayout()
        check_row.setSpacing(12)
        self._exclude_enemy_pp_check = QCheckBox("Exclude enemy PowerPlay systems")
        self._exclude_enemy_pp_check.setStyleSheet(_LABEL_STYLE)
        self._exclude_enemy_pp_check.setChecked(True)
        self._exclude_enemy_pp_check.setToolTip(
            "Drops stations in systems currently controlled by a Power other than yours "
            "(same rule as Market's equivalent checkbox)."
        )
        self._faction_only_check = QCheckBox("Only my squadron faction's controlled stations")
        self._faction_only_check.setStyleSheet(_LABEL_STYLE)
        check_row.addWidget(self._exclude_enemy_pp_check)
        check_row.addWidget(self._faction_only_check)
        check_row.addStretch(1)
        fl.addLayout(check_row)

        self._status_label = QLabel("Enter a range and press Search.")
        self._status_label.setStyleSheet("color:#888888; font-size:12px; background:transparent;")
        fl.addWidget(self._status_label)

        self._table = QTableWidget()
        self._table.setColumnCount(10)
        self._table.setHorizontalHeaderLabels(
            ["System A", "Station A", "System B", "Station B", "Dist (ly)",
             "A→B: Buy", "A→B: Profit/u", "B→A: Buy", "B→A: Profit/u", "Total Profit"]
        )
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet(
            "QTableWidget { background:#080f18; alternate-background-color:#0a1520;"
            " color:#c8c8c8; gridline-color:#1e3a5a; border:1px solid #1e3a5a; font-size:12px; }"
            "QTableWidget::item { padding:1px 4px; }"
            "QHeaderView::section { background:#0d1a2a; color:#888888; border:none;"
            " padding:2px; font-size:12px; font-weight:bold; letter-spacing:1px; }"
            "QTableWidget::item:selected { background:#1a3a5a; color:#FFB347; }"
        )
        h = self._table.horizontalHeader()
        for c in (0, 1, 2, 3):
            h.setSectionResizeMode(c, QHeaderView.ResizeMode.Stretch)
        for c in range(4, 10):
            h.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setToolTip("Click a System or Station cell to copy its name to the clipboard.")
        self._table.cellClicked.connect(self._on_cell_clicked)
        fl.addWidget(self._table, 1)

        self._loading_spinner = BusySpinner(self)

        root.addWidget(frame, 1)

    def refresh(self, state) -> None:
        """Cheap, safe to call on every general refresh — just updates the
        location/cargo-capacity display, no search triggered."""
        self._system = (getattr(state, "system", None) or "").strip()
        self._ref_x = float(getattr(state, "system_x", 0.0) or 0.0)
        self._ref_y = float(getattr(state, "system_y", 0.0) or 0.0)
        self._ref_z = float(getattr(state, "system_z", 0.0) or 0.0)
        self._cargo_capacity = getattr(state, "cargo_capacity", None)
        self._my_power = getattr(state, "pp_power", None) or None
        self._location_label.setText(f"Location: {self._system or '—'}")
        if isinstance(self._cargo_capacity, int) and self._cargo_capacity > 0:
            self._cargo_label.setText(f"Cargo capacity: {self._cargo_capacity}t (from current ship)")
        else:
            self._cargo_label.setText("Cargo capacity: unknown (fly at least once this session)")
        self._search_btn.setEnabled(bool(self._system) and bool(self._cargo_capacity))

    def _start_search(self) -> None:
        if not self._system:
            self._status_label.setText("No system location data yet — jump to a system first.")
            return
        if not isinstance(self._cargo_capacity, int) or self._cargo_capacity <= 0:
            self._status_label.setText("Cargo capacity unknown yet — undock or check the outfitting screen once.")
            return
        if self._thread and self._thread.isRunning():
            return

        squadron_faction_name = None
        if self._faction_only_check.isChecked():
            try:
                overview = self._repo.get_player_faction_overview()
                squadron_faction_name = overview["faction_name"] if overview else None
            except Exception:
                log.exception("Failed to load squadron faction name for route filter")
            if not squadron_faction_name:
                self._status_label.setText(
                    "No squadron-aligned faction known yet — can't apply the faction filter."
                )
                return

        radius = self._range_spin.value()
        self._search_btn.setEnabled(False)
        self._status_label.setText(f"Searching for round trips within {radius} ly…")
        self._table.setRowCount(0)
        self._loading_spinner.start_over(self)

        self._worker = _TradeRouteWorker(
            self._repo.db.db_path, self._ref_x, self._ref_y, self._ref_z, radius,
            self._cargo_capacity, self._exclude_enemy_pp_check.isChecked(), self._my_power,
            self._edsm_powerplay, self._faction_only_check.isChecked(), squadron_faction_name,
            self._pad_filter_combo.currentData(),
        )
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_results)
        self._worker.finished.connect(self._thread.quit)
        self._thread.start()

    def _on_results(self, loops: list, error: str) -> None:
        self._search_btn.setEnabled(bool(self._system) and bool(self._cargo_capacity))
        self._loading_spinner.stop()
        if error:
            self._status_label.setText(f"Error: {error}")
            return

        self._status_label.setText(
            f"Found {len(loops)} profitable round trip{'s' if len(loops) != 1 else ''} "
            f"within {self._range_spin.value()} ly."
        )
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(loops))
        for row, loop in enumerate(loops):
            sys_a_item = QTableWidgetItem(loop["system_a"])
            station_a_item = QTableWidgetItem(loop["station_a"])
            sys_b_item = QTableWidgetItem(loop["system_b"])
            station_b_item = QTableWidgetItem(loop["station_b"])
            dist_item = _NumericTableWidgetItem(f"{loop['distance_ly']:.1f}", loop["distance_ly"])
            leg_ab, leg_ba = loop["leg_a_to_b"], loop["leg_b_to_a"]
            ab_commodity_item = QTableWidgetItem(leg_ab["commodity_display"])
            ab_profit_item = _NumericTableWidgetItem(f"{leg_ab['profit_per_unit']:,}", float(leg_ab["profit_per_unit"]))
            ba_commodity_item = QTableWidgetItem(leg_ba["commodity_display"])
            ba_profit_item = _NumericTableWidgetItem(f"{leg_ba['profit_per_unit']:,}", float(leg_ba["profit_per_unit"]))
            total_item = _NumericTableWidgetItem(f"{loop['total_profit']:,}", float(loop["total_profit"]))
            total_item.setForeground(QColor("#6BCB77"))
            for it in (dist_item, ab_profit_item, ba_profit_item, total_item):
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            self._table.setItem(row, 0, sys_a_item)
            self._table.setItem(row, 1, station_a_item)
            self._table.setItem(row, 2, sys_b_item)
            self._table.setItem(row, 3, station_b_item)
            self._table.setItem(row, 4, dist_item)
            self._table.setItem(row, 5, ab_commodity_item)
            self._table.setItem(row, 6, ab_profit_item)
            self._table.setItem(row, 7, ba_commodity_item)
            self._table.setItem(row, 8, ba_profit_item)
            self._table.setItem(row, 9, total_item)
        self._table.setSortingEnabled(True)
        self._table.sortItems(9, Qt.SortOrder.DescendingOrder)

    def _on_cell_clicked(self, row: int, column: int) -> None:
        if column not in (0, 1, 2, 3):
            return
        item = self._table.item(row, column)
        if item and item.text():
            QApplication.clipboard().setText(item.text())
