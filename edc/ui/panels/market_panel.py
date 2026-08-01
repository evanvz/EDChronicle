"""Market panel — best sell price search across the galaxy-wide EDDN commodity feed."""
from __future__ import annotations

import logging
import re
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QSpinBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QFrame,
)

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


class MarketPanel(QWidget):
    """
    Owns all widgets and refresh logic for the Market tab.
    Receives state via refresh(state, radius_ly). Unlike most panels this
    one is constructed with a Repository directly — the search itself is a
    local SQLite query (fast, no network), so no background worker/network
    client is needed here.
    """

    def __init__(self, repo, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._system: str = ""
        self._ref_x: float = 0.0
        self._ref_y: float = 0.0
        self._ref_z: float = 0.0

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 8)
        root.setSpacing(6)

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

        # ── Status + results ────────────────────────────────────────────
        self._status_label = QLabel("Enter a commodity and press Search.")
        self._status_label.setStyleSheet("color:#888888; font-size:10px; background:transparent;")
        root.addWidget(self._status_label)

        self._table = QTableWidget()
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels(
            ["Station", "System", "Sell Price", "Dist (ly)", "Demand", "Updated"]
        )
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet(
            "QTableWidget { background:#080f18; alternate-background-color:#0a1520;"
            " color:#c8c8c8; gridline-color:#1e3a5a; border:1px solid #1e3a5a; }"
            "QHeaderView::section { background:#0d1a2a; color:#888888; border:none;"
            " padding:3px; font-size:10px; font-weight:bold; letter-spacing:1px; }"
            "QTableWidget::item:selected { background:#1a3a5a; color:#FFB347; }"
        )
        h = self._table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self._table, 1)

    # ── Public API ────────────────────────────────────────────────────────

    def refresh(self, state, radius_ly: int) -> None:
        self._system = (getattr(state, "system", None) or "").strip()
        self._ref_x = float(getattr(state, "system_x", 0.0) or 0.0)
        self._ref_y = float(getattr(state, "system_y", 0.0) or 0.0)
        self._ref_z = float(getattr(state, "system_z", 0.0) or 0.0)
        self._location_label.setText(f"Location: {self._system or '—'}")
        self._search_btn.setEnabled(bool(self._system))
        if radius_ly and self._range_spin.value() == 100 and radius_ly != 100:
            self._range_spin.setValue(int(radius_ly))

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
            system_item = QTableWidgetItem(r.get("system_name") or "—")
            price_item = QTableWidgetItem(f"{r.get('sell_price', 0):,}")
            dist_item = QTableWidgetItem(f"{r.get('distance_ly', 0.0):.1f}")
            demand_item = QTableWidgetItem(str(r.get("demand") or 0))
            updated_item = QTableWidgetItem(str(r.get("last_updated") or "—"))
            for it in (price_item, dist_item, demand_item):
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            self._table.setItem(row, 0, station_item)
            self._table.setItem(row, 1, system_item)
            self._table.setItem(row, 2, price_item)
            self._table.setItem(row, 3, dist_item)
            self._table.setItem(row, 4, demand_item)
            self._table.setItem(row, 5, updated_item)
