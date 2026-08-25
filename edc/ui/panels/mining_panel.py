"""Mining panel — session stats plus a ring/hotspot target finder (search by distance)."""
from __future__ import annotations

import logging
from typing import List, Optional

from PyQt6.QtCore import Qt, QObject, QThread, QStringListModel, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QSpinBox, QComboBox, QCompleter, QTableWidget, QTableWidgetItem,
    QHeaderView, QFrame, QApplication,
)

from edc.core.spansh_client import SpanshClient, MiningRingResult
from edc.core.station_pads import pad_size_hint
from edc.ui.busy_spinner import BusySpinner
from edc.ui.panels.market_panel import normalize_commodity_name, _NumericTableWidgetItem
from edc.ui.style import CARD_STYLE as _CARD_STYLE, HDR_STYLE as _HDR_STYLE, LABEL_STYLE as _LABEL_STYLE

log = logging.getLogger(__name__)


class _RingSearchWorker(QObject):
    finished = pyqtSignal(list, str)  # (results, error)

    def __init__(self, material, ref_x, ref_y, ref_z, range_ly):
        super().__init__()
        self._material = material
        self._ref_x = ref_x
        self._ref_y = ref_y
        self._ref_z = ref_z
        self._range_ly = range_ly

    def run(self):
        client = SpanshClient()
        results, error = client.search_mining_rings(
            material=self._material,
            ref_x=self._ref_x, ref_y=self._ref_y, ref_z=self._ref_z,
            range_ly=self._range_ly,
        )
        self.finished.emit(results, error)


class _CargoMarketSearchWorker(QObject):
    """
    Opens its own SQLite connection — search_market_prices() against the
    galaxy-wide market_prices table (13M+ rows) takes several seconds even
    with the bounding-box pre-filter (confirmed: 2-6s per commodity on a
    real database). Looping that once per distinct cargo commodity used to
    run directly on the UI thread, freezing the whole app for the sum of
    all of them — confirmed live: a mixed cargo hold froze the app for
    30-60 seconds. Same fix shape as _RingSearchWorker/_TradeOpportunityWorker.
    """
    finished = pyqtSignal(list, int)  # (rows, commodity_count)

    def __init__(self, db_path, qty_by_commodity, display_by_commodity, ref_x, ref_y, ref_z, radius_ly, exclude_market_id):
        super().__init__()
        self._db_path = db_path
        self._qty_by_commodity = qty_by_commodity
        self._display_by_commodity = display_by_commodity
        self._ref_x, self._ref_y, self._ref_z = ref_x, ref_y, ref_z
        self._radius_ly = radius_ly
        self._exclude_market_id = exclude_market_id

    def run(self):
        from persistence.database import Database
        from persistence.repository import Repository

        db = Database(self._db_path)
        repo = Repository(db)
        rows = []
        try:
            for key, qty in self._qty_by_commodity.items():
                try:
                    results = repo.search_market_prices(
                        key, self._ref_x, self._ref_y, self._ref_z, float(self._radius_ly),
                        exclude_market_id=self._exclude_market_id,
                    )
                except Exception:
                    log.exception("Cargo market search failed for %s", key)
                    continue
                for r in results[:8]:
                    rows.append((self._display_by_commodity[key], qty, r))
        finally:
            db.close()
        self.finished.emit(rows, len(self._qty_by_commodity))


class MiningPanel(QWidget):
    """
    Owns all widgets and refresh logic for the Mining tab.
    Receives state via refresh(state). Knows nothing about
    main_window or repo — "where to sell" is delegated via
    sell_search_requested, letting main_window switch tabs and
    query the Market panel itself.
    """

    sell_search_requested = pyqtSignal(str)  # commodity display name

    def __init__(self, repo, parent=None):
        super().__init__(parent)

        self._repo = repo
        self._system: str = ""
        self._ref_x: float = 0.0
        self._ref_y: float = 0.0
        self._ref_z: float = 0.0
        self._cargo_inventory: list = []
        self._current_market_id: Optional[int] = None
        self._market_radius_ly: int = 100
        self._thread: Optional[QThread] = None
        self._worker: Optional[_RingSearchWorker] = None
        self._last_ring_results: List[MiningRingResult] = []
        self._cargo_rows_raw: list = []
        self._cargo_commodity_count: int = 0
        self._cargo_thread: Optional[QThread] = None
        self._cargo_worker: Optional[_CargoMarketSearchWorker] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 8)
        root.setSpacing(6)

        # ── Session stats card ────────────────────────────────────────────
        stats_frame = QFrame()
        stats_frame.setStyleSheet(_CARD_STYLE)
        stats_layout = QVBoxLayout(stats_frame)
        stats_layout.setContentsMargins(8, 6, 8, 8)
        stats_layout.setSpacing(4)

        stats_hdr = QLabel("MINING — SESSION")
        stats_hdr.setStyleSheet(_HDR_STYLE)
        stats_layout.addWidget(stats_hdr)

        self._session_label = QLabel("No mining activity yet this session.")
        self._session_label.setWordWrap(True)
        self._session_label.setStyleSheet(_LABEL_STYLE)
        stats_layout.addWidget(self._session_label)

        self._last_prospect_label = QLabel("")
        self._last_prospect_label.setWordWrap(True)
        self._last_prospect_label.setStyleSheet("color:#FFB347; background:transparent; border:none;")
        self._last_prospect_label.setVisible(False)
        stats_layout.addWidget(self._last_prospect_label)

        self._sell_hdr = QLabel("Where to sell:")
        self._sell_hdr.setStyleSheet("color:#7a7a7a; font-size:12px; background:transparent; border:none;")
        self._sell_hdr.setVisible(False)
        stats_layout.addWidget(self._sell_hdr)

        self._sell_row = QHBoxLayout()
        self._sell_row.setSpacing(4)
        stats_layout.addLayout(self._sell_row)

        root.addWidget(stats_frame)

        # ── Sell cargo — market search ──────────────────────────────────
        cargo_frame = QFrame()
        cargo_frame.setStyleSheet(_CARD_STYLE)
        cargo_layout = QVBoxLayout(cargo_frame)
        cargo_layout.setContentsMargins(8, 6, 8, 8)
        cargo_layout.setSpacing(6)

        cargo_hdr_row = QHBoxLayout()
        cargo_hdr = QLabel("SELL CARGO — MARKET SEARCH")
        cargo_hdr.setStyleSheet(_HDR_STYLE)
        cargo_hdr_row.addWidget(cargo_hdr)
        cargo_hdr_row.addStretch(1)
        cargo_pad_label = QLabel("Min pad:")
        cargo_pad_label.setStyleSheet(_LABEL_STYLE)
        cargo_hdr_row.addWidget(cargo_pad_label)
        self._cargo_pad_filter_combo = QComboBox()
        self._cargo_pad_filter_combo.addItem("Any", None)
        self._cargo_pad_filter_combo.addItem("Medium+", "M")
        self._cargo_pad_filter_combo.addItem("Large only", "L")
        self._cargo_pad_filter_combo.setStyleSheet("background:#0a1520; color:#c8c8c8; border:1px solid #1e3a5a;")
        self._cargo_pad_filter_combo.currentIndexChanged.connect(self._render_cargo_markets)
        cargo_hdr_row.addWidget(self._cargo_pad_filter_combo)
        self._cargo_search_btn = QPushButton("Search Markets for Cargo")
        self._cargo_search_btn.setStyleSheet(
            "QPushButton { background:#1a3a5a; color:#FFB347; border:1px solid #2a5a8a;"
            " border-radius:3px; padding:3px 12px; font-weight:bold; }"
            "QPushButton:hover { background:#2a5a8a; }"
            "QPushButton:disabled { background:#111; color:#555; border-color:#333; }"
        )
        self._cargo_search_btn.clicked.connect(self._search_cargo_markets)
        cargo_hdr_row.addWidget(self._cargo_search_btn)
        cargo_layout.addLayout(cargo_hdr_row)

        self._cargo_status_label = QLabel("Mine something, then search for where to sell your whole hold.")
        self._cargo_status_label.setWordWrap(True)
        self._cargo_status_label.setStyleSheet("color:#888888; font-size:12px; background:transparent;")
        cargo_layout.addWidget(self._cargo_status_label)

        self._cargo_market_table = QTableWidget()
        self._cargo_market_table.setColumnCount(6)
        self._cargo_market_table.setHorizontalHeaderLabels(
            ["Commodity", "Qty", "Station", "System", "Pad", "Sell Price"]
        )
        self._cargo_market_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._cargo_market_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._cargo_market_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._cargo_market_table.verticalHeader().setVisible(False)
        self._cargo_market_table.verticalHeader().setDefaultSectionSize(18)
        self._cargo_market_table.setAlternatingRowColors(True)
        self._cargo_market_table.setStyleSheet(
            "QTableWidget { background:#080f18; alternate-background-color:#0a1520;"
            " gridline-color:#1e3a5a; border:1px solid #1e3a5a; font-size:12px; }"
            "QTableWidget::item { padding:1px 4px; }"
            "QHeaderView::section { background:#0d1a2a; color:#888888; border:none;"
            " padding:2px; font-size:12px; font-weight:bold; letter-spacing:1px; }"
            "QTableWidget::item:selected { background:#1a3a5a; color:#FFB347; }"
        )
        cmh = self._cargo_market_table.horizontalHeader()
        cmh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        cmh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        cmh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        cmh.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        cmh.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        cmh.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self._cargo_market_table.setMaximumHeight(180)
        self._cargo_market_table.setToolTip("Click the Station or System cell to copy its name to the clipboard.")
        self._cargo_market_table.cellClicked.connect(self._on_cargo_cell_clicked)
        cargo_layout.addWidget(self._cargo_market_table)

        root.addWidget(cargo_frame)
        self._cargo_loading_spinner = BusySpinner(self)

        # ── Ring finder card ──────────────────────────────────────────────
        finder_frame = QFrame()
        finder_frame.setStyleSheet(_CARD_STYLE)
        finder_layout = QVBoxLayout(finder_frame)
        finder_layout.setContentsMargins(8, 6, 8, 8)
        finder_layout.setSpacing(6)

        finder_hdr = QLabel("MINING TARGET FINDER — RING HOTSPOT SEARCH")
        finder_hdr.setStyleSheet(_HDR_STYLE)
        finder_layout.addWidget(finder_hdr)

        self._location_label = QLabel("Location: —")
        self._location_label.setStyleSheet(_LABEL_STYLE)
        finder_layout.addWidget(self._location_label)

        row = QHBoxLayout()
        row.setSpacing(8)

        self._material_edit = QLineEdit()
        self._material_edit.setPlaceholderText("Material (e.g. Platinum, Painite, Alexandrite, Void Opals...)")
        self._material_edit.setStyleSheet("background:#0a1520; color:#c8c8c8; border:1px solid #1e3a5a;")

        self._material_completer = QCompleter([])
        self._material_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._material_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._material_completer.popup().setStyleSheet(
            "QAbstractItemView { background:#0a1520; color:#c8c8c8; border:1px solid #1e3a5a;"
            " selection-background-color:#1a3a5a; selection-color:#FFB347; }"
        )
        self._material_edit.setCompleter(self._material_completer)
        self.refresh_commodity_names()

        range_label = QLabel("Range:")
        range_label.setStyleSheet(_LABEL_STYLE)
        self._range_spin = QSpinBox()
        self._range_spin.setRange(10, 500)
        self._range_spin.setSingleStep(10)
        self._range_spin.setValue(100)
        self._range_spin.setSuffix(" ly")
        self._range_spin.setStyleSheet("background:#0a1520; color:#c8c8c8; border:1px solid #1e3a5a;")

        reserve_label = QLabel("Reserve:")
        reserve_label.setStyleSheet(_LABEL_STYLE)
        self._reserve_filter_combo = QComboBox()
        self._reserve_filter_combo.addItem("All (Pristine+Major)", None)
        self._reserve_filter_combo.addItem("Pristine only", "Pristine")
        self._reserve_filter_combo.setStyleSheet("background:#0a1520; color:#c8c8c8; border:1px solid #1e3a5a;")
        self._reserve_filter_combo.currentIndexChanged.connect(self._render_ring_results)

        self._search_btn = QPushButton("Search")
        self._search_btn.setStyleSheet(
            "QPushButton { background:#1a3a5a; color:#FFB347; border:1px solid #2a5a8a;"
            " border-radius:3px; padding:3px 12px; font-weight:bold; }"
            "QPushButton:hover { background:#2a5a8a; }"
            "QPushButton:disabled { background:#111; color:#555; border-color:#333; }"
        )
        self._search_btn.clicked.connect(self._start_search)

        row.addWidget(self._material_edit, 1)
        row.addWidget(range_label)
        row.addWidget(self._range_spin)
        row.addWidget(reserve_label)
        row.addWidget(self._reserve_filter_combo)
        row.addWidget(self._search_btn)
        finder_layout.addLayout(row)

        note = QLabel(
            "Searches the nearest ~500 high-reserve ring bodies within range for a hotspot "
            "match — very rare materials near the edge of a large range may not surface."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#7a7a7a; font-size:11px; background:transparent; border:none;")
        finder_layout.addWidget(note)

        root.addWidget(finder_frame)

        # ── Status + results ──────────────────────────────────────────────
        self._status_label = QLabel("Enter a material and press Search.")
        self._status_label.setStyleSheet("color:#888888; font-size:12px; background:transparent;")
        root.addWidget(self._status_label)

        self._table = QTableWidget()
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels(
            ["System", "Body", "Ring Type", "Reserve", "Dist (ly)", "Hotspots"]
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
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setToolTip("Click the System or Body cell to copy its name to the clipboard.")
        self._table.cellClicked.connect(self._on_ring_cell_clicked)
        root.addWidget(self._table, 1)
        self._ring_loading_spinner = BusySpinner(self)

    # ── Public API ────────────────────────────────────────────────────────

    def refresh_commodity_names(self) -> None:
        """Same autocomplete source as the Market tab — ring hotspot
        materials are also ordinary sellable commodities, so no separate
        data source is needed. See MarketPanel.refresh_commodity_names."""
        try:
            names = self._repo.get_all_commodity_display_names()
        except Exception:
            log.exception("Failed to load commodity display names")
            return
        model = self._material_completer.model()
        if isinstance(model, QStringListModel):
            model.setStringList(names)
        else:
            self._material_completer.setModel(QStringListModel(names, self._material_completer))

    def refresh(self, state, market_radius_ly: int = 100) -> None:
        self._system = (getattr(state, "system", None) or "").strip()
        self._ref_x = float(getattr(state, "system_x", 0.0) or 0.0)
        self._ref_y = float(getattr(state, "system_y", 0.0) or 0.0)
        self._ref_z = float(getattr(state, "system_z", 0.0) or 0.0)
        self._location_label.setText(f"Location: {self._system or '—'}")
        self._search_btn.setEnabled(bool(self._system))

        self._cargo_inventory = getattr(state, "cargo_inventory", None) or []
        self._current_market_id = getattr(state, "current_market_id", None)
        self._market_radius_ly = int(market_radius_ly or 100)
        self._cargo_search_btn.setEnabled(bool(self._system) and bool(self._cargo_inventory))

        refined = getattr(state, "mining_refined_totals", {}) or {}
        prospected = getattr(state, "mining_prospected_count", 0)
        cracked = getattr(state, "mining_cracked_count", 0)

        if refined or prospected or cracked:
            parts = [f"Prospected: {prospected}", f"Motherlodes cracked: {cracked}"]
            if refined:
                refined_txt = ", ".join(
                    f"{name.title()}: {count}"
                    for name, count in sorted(refined.items(), key=lambda kv: -kv[1])
                )
                parts.append(f"Refined — {refined_txt}")
            self._session_label.setText(" | ".join(parts))
            self._rebuild_sell_buttons(refined)
        else:
            self._rebuild_sell_buttons({})
            self._session_label.setText("No mining activity yet this session.")

        content = getattr(state, "mining_last_prospect_content", None)
        materials = getattr(state, "mining_last_prospect_materials", None) or []
        motherlode = getattr(state, "mining_last_motherlode_material", None)
        if content or materials:
            mat_txt = ", ".join(
                f"{m.get('Name', '?')} {m.get('Proportion', 0):.1f}%"
                for m in materials if isinstance(m, dict)
            )
            bits = [f"Last prospect: {content or '—'}"]
            if mat_txt:
                bits.append(mat_txt)
            if motherlode:
                bits.append(f"Motherlode: {motherlode}")
            self._last_prospect_label.setText(" — ".join(bits))
            self._last_prospect_label.setVisible(True)
        else:
            self._last_prospect_label.setVisible(False)

    def _rebuild_sell_buttons(self, refined: dict) -> None:
        while self._sell_row.count():
            item = self._sell_row.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if not refined:
            self._sell_hdr.setVisible(False)
            return

        self._sell_hdr.setVisible(True)
        for name in sorted(refined.keys(), key=lambda n: -refined[n])[:6]:
            btn = QPushButton(name.title())
            btn.setStyleSheet(
                "QPushButton { background:#1a2a1a; color:#6BCB77; border:1px solid #2a5a2a;"
                " border-radius:3px; padding:2px 8px; font-size:12px; }"
                "QPushButton:hover { background:#2a3a2a; }"
            )
            btn.clicked.connect(lambda checked=False, n=name: self.sell_search_requested.emit(n))
            self._sell_row.addWidget(btn)
        self._sell_row.addStretch(1)

    def _search_cargo_markets(self):
        if not self._system:
            self._cargo_status_label.setText("No system location data yet — jump to a system first.")
            return
        if not self._cargo_inventory:
            self._cargo_status_label.setText("Cargo hold is empty — nothing to search for.")
            self._cargo_market_table.setRowCount(0)
            return
        if self._cargo_thread and self._cargo_thread.isRunning():
            return

        # Sum quantity per distinct commodity — the same item can appear as
        # multiple entries (e.g. a regular stack plus a mission-tagged stack).
        qty_by_commodity: dict = {}
        display_by_commodity: dict = {}
        for c in self._cargo_inventory:
            if not isinstance(c, dict):
                continue
            raw_name = c.get("Name") or ""
            key = normalize_commodity_name(raw_name)
            if not key:
                continue
            qty_by_commodity[key] = qty_by_commodity.get(key, 0) + int(c.get("Count") or 0)
            display_by_commodity.setdefault(key, c.get("Name_Localised") or raw_name.title())

        # One search_market_prices() call per distinct commodity, each
        # several seconds against the galaxy-wide market_prices table —
        # backgrounded so it can't freeze the app (confirmed live it did,
        # for 30-60s with a mixed cargo hold, before this fix).
        self._cargo_search_btn.setEnabled(False)
        self._cargo_status_label.setText(f"Searching markets for {len(qty_by_commodity)} commodities…")
        self._cargo_market_table.setRowCount(0)
        self._cargo_loading_spinner.start_over(self._cargo_market_table)
        self._cargo_worker = _CargoMarketSearchWorker(
            self._repo.db.db_path, qty_by_commodity, display_by_commodity,
            self._ref_x, self._ref_y, self._ref_z, self._market_radius_ly, self._current_market_id,
        )
        self._cargo_thread = QThread()
        self._cargo_worker.moveToThread(self._cargo_thread)
        self._cargo_thread.started.connect(self._cargo_worker.run)
        self._cargo_worker.finished.connect(self._on_cargo_search_finished)
        self._cargo_worker.finished.connect(self._cargo_thread.quit)
        self._cargo_thread.start()

    def _on_cargo_search_finished(self, rows: list, commodity_count: int) -> None:
        self._cargo_search_btn.setEnabled(bool(self._system) and bool(self._cargo_inventory))
        self._cargo_loading_spinner.stop()
        self._cargo_rows_raw = rows
        self._cargo_commodity_count = commodity_count
        self._render_cargo_markets()

    def _render_cargo_markets(self) -> None:
        rows = self._cargo_rows_raw
        if not rows:
            self._cargo_status_label.setText(
                "No known market data for anything in your cargo within "
                f"{self._market_radius_ly} ly yet."
            )
            self._cargo_market_table.setRowCount(0)
            return

        min_pad = self._cargo_pad_filter_combo.currentData()
        rank = {"S": 1, "M": 2, "L": 3}
        shown_per_commodity: dict = {}
        shown_rows = []
        for name, qty, r in rows:
            pad = r.get("pad_size") or pad_size_hint(r.get("station_type"))
            if min_pad and pad in rank and rank[pad] < rank[min_pad]:
                continue
            if shown_per_commodity.get(name, 0) >= 3:
                continue
            shown_per_commodity[name] = shown_per_commodity.get(name, 0) + 1
            shown_rows.append((name, qty, r, pad))

        self._cargo_status_label.setText(
            f"{self._cargo_commodity_count} commodit{'y' if self._cargo_commodity_count == 1 else 'ies'} "
            f"in cargo — showing up to 3 destinations each, within {self._market_radius_ly} ly."
        )

        self._cargo_market_table.setSortingEnabled(False)
        self._cargo_market_table.setRowCount(len(shown_rows))
        for row, (name, qty, r, pad) in enumerate(shown_rows):
            name_item = QTableWidgetItem(name)
            qty_item = _NumericTableWidgetItem(str(qty), float(qty))
            station_item = QTableWidgetItem(r.get("station_name") or "—")
            system_item = QTableWidgetItem(r.get("system_name") or "—")
            pad_item = QTableWidgetItem(pad)
            price_value = float(r.get("sell_price") or 0)
            price_item = _NumericTableWidgetItem(f"{r.get('sell_price', 0):,}", price_value)
            if pad_item.text() == "?":
                pad_item.setForeground(QColor("#888888"))
                pad_item.setToolTip("Landing pad size unknown for this station type")

            # Selling more than ~25% of a station's demand tapers the price
            # down per unit past that point (real game mechanic — a low-
            # demand station makes this easy to hit with a full cargo hold
            # of one commodity, which mining trips often are).
            demand = r.get("demand")
            if isinstance(demand, int) and demand > 0 and qty > 0.25 * demand:
                warn = f"Selling {qty} here is {qty / demand * 100:.0f}% of the {demand} demand — expect a lower price than shown for the excess."
                qty_item.setForeground(QColor("#FF8C00"))
                qty_item.setToolTip(warn)
                price_item.setForeground(QColor("#FF8C00"))
                price_item.setToolTip(warn)

            for it in (qty_item, pad_item, price_item):
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            self._cargo_market_table.setItem(row, 0, name_item)
            self._cargo_market_table.setItem(row, 1, qty_item)
            self._cargo_market_table.setItem(row, 2, station_item)
            self._cargo_market_table.setItem(row, 3, system_item)
            self._cargo_market_table.setItem(row, 4, pad_item)
            self._cargo_market_table.setItem(row, 5, price_item)
        self._cargo_market_table.setSortingEnabled(True)
        self._cargo_market_table.sortItems(5, Qt.SortOrder.DescendingOrder)

    def _on_cargo_cell_clicked(self, row: int, column: int) -> None:
        if column not in (2, 3):  # Station, System
            return
        item = self._cargo_market_table.item(row, column)
        if item and item.text():
            QApplication.clipboard().setText(item.text())

    # ── Search ────────────────────────────────────────────────────────────

    def _start_search(self):
        material = self._material_edit.text().strip()
        if not material:
            self._status_label.setText("Enter a material name first.")
            return
        if not self._system:
            self._status_label.setText("No system location data yet — jump to a system first.")
            return
        if self._thread and self._thread.isRunning():
            return

        self._search_btn.setEnabled(False)
        self._status_label.setText(f"Searching for {material} hotspots…")
        self._table.setRowCount(0)
        self._ring_loading_spinner.start_over(self._table)

        self._worker = _RingSearchWorker(
            material=material,
            ref_x=self._ref_x, ref_y=self._ref_y, ref_z=self._ref_z,
            range_ly=self._range_spin.value(),
        )
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_results)
        self._worker.finished.connect(self._thread.quit)
        self._thread.start()

    def _on_results(self, results: List[MiningRingResult], error: str):
        self._search_btn.setEnabled(True)
        self._ring_loading_spinner.stop()
        if error:
            self._status_label.setText(f"Error: {error}")
            return
        self._last_ring_results = results
        self._render_ring_results()

    def _render_ring_results(self) -> None:
        results = self._last_ring_results
        reserve_filter = self._reserve_filter_combo.currentData()
        if reserve_filter:
            results = [r for r in results if r.reserve_level == reserve_filter]

        self._status_label.setText(
            f"Found {len(results)} ring{'s' if len(results) != 1 else ''} "
            f"within {self._range_spin.value()} ly."
        )
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(results))
        for row, r in enumerate(results):
            name_item = QTableWidgetItem(r.system_name)
            body_item = QTableWidgetItem(r.body_name)
            type_item = QTableWidgetItem(r.ring_type)
            reserve_item = QTableWidgetItem(r.reserve_level)
            dist_item = _NumericTableWidgetItem(f"{r.distance:.1f}", r.distance)
            hotspot_item = _NumericTableWidgetItem(str(r.hotspot_count), float(r.hotspot_count))
            for it in (type_item, reserve_item, dist_item, hotspot_item):
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            self._table.setItem(row, 0, name_item)
            self._table.setItem(row, 1, body_item)
            self._table.setItem(row, 2, type_item)
            self._table.setItem(row, 3, reserve_item)
            self._table.setItem(row, 4, dist_item)
            self._table.setItem(row, 5, hotspot_item)
        self._table.setSortingEnabled(True)
        self._table.sortItems(4, Qt.SortOrder.AscendingOrder)

    def _on_ring_cell_clicked(self, row: int, column: int) -> None:
        if column not in (0, 1):  # System, Body
            return
        item = self._table.item(row, column)
        if item and item.text():
            QApplication.clipboard().setText(item.text())
