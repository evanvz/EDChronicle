"""Engineering Blueprint Wishlist panel — pick blueprints to build, track missing materials."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QSpinBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QFrame,
)

from edc.core.engineering_blueprints import EngineeringBlueprintTable
from edc.core.engineering_wishlist import EngineeringWishlist

log = logging.getLogger(__name__)

_CATEGORY_STATE_ATTR = {
    "raw": "materials_raw",
    "manufactured": "materials_manufactured",
    "encoded": "materials_encoded",
}


class EngineeringPanel(QWidget):
    """
    Owns all widgets and refresh logic for the Engineering (Blueprint
    Wishlist) tab. Receives state via refresh(state). Knows nothing
    about main_window or repo.
    """

    _CARD_STYLE = "QFrame { background:#0d1a2a; border:1px solid #1e3a5a; border-radius:5px; }"
    _HDR_STYLE = "color:#555555; font-size:10px; font-weight:bold; letter-spacing:1px; background:transparent; border:none;"
    _LABEL_STYLE = "background:transparent; border:none; color:#c8c8c8;"

    def __init__(self, blueprint_table: EngineeringBlueprintTable, wishlist_store: EngineeringWishlist, parent=None):
        super().__init__(parent)
        self._blueprints = blueprint_table
        self._store = wishlist_store
        self._wishlist: List[Dict[str, Any]] = self._store.load()
        self._state = None

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 8)
        root.setSpacing(6)

        # ── Add-to-wishlist card ──────────────────────────────────────────
        add_frame = QFrame()
        add_frame.setStyleSheet(self._CARD_STYLE)
        add_layout = QVBoxLayout(add_frame)
        add_layout.setContentsMargins(8, 6, 8, 8)
        add_layout.setSpacing(6)

        hdr = QLabel("ENGINEERING — BLUEPRINT WISHLIST")
        hdr.setStyleSheet(self._HDR_STYLE)
        add_layout.addWidget(hdr)

        row = QHBoxLayout()
        row.setSpacing(8)

        self._bp_combo = QComboBox()
        self._bp_combo.setStyleSheet("background:#0a1520; color:#c8c8c8; border:1px solid #1e3a5a;")
        self._bp_fdnames: List[str] = self._blueprints.blueprint_names()
        for fdname in self._bp_fdnames:
            bp = self._blueprints.get(fdname) or {}
            label = f"{bp.get('display_name', fdname)} — {bp.get('short_name', '')}"
            self._bp_combo.addItem(label, fdname)
        self._bp_combo.currentIndexChanged.connect(self._on_blueprint_changed)

        grade_label = QLabel("Grade:")
        grade_label.setStyleSheet(self._LABEL_STYLE)

        self._grade_spin = QSpinBox()
        self._grade_spin.setRange(1, 5)
        self._grade_spin.setStyleSheet("background:#0a1520; color:#c8c8c8; border:1px solid #1e3a5a;")

        add_btn = QPushButton("Add to Wishlist")
        add_btn.setStyleSheet(
            "QPushButton { background:#1a3a5a; color:#FFB347; border:1px solid #2a5a8a;"
            " border-radius:3px; padding:3px 12px; font-weight:bold; }"
            "QPushButton:hover { background:#2a5a8a; }"
        )
        add_btn.clicked.connect(self._add_to_wishlist)

        row.addWidget(self._bp_combo, 1)
        row.addWidget(grade_label)
        row.addWidget(self._grade_spin)
        row.addWidget(add_btn)
        add_layout.addLayout(row)

        root.addWidget(add_frame)
        self._on_blueprint_changed()

        # ── Wishlist table ────────────────────────────────────────────────
        wl_hdr_row = QHBoxLayout()
        wl_hdr = QLabel("TRACKED BUILDS")
        wl_hdr.setStyleSheet(self._HDR_STYLE)
        wl_hdr_row.addWidget(wl_hdr)
        wl_hdr_row.addStretch()
        remove_btn = QPushButton("Remove Selected")
        remove_btn.setStyleSheet(
            "QPushButton { background:#2a1010; color:#FF8080; border:1px solid #5a2a2a;"
            " border-radius:3px; padding:2px 10px; }"
            "QPushButton:hover { background:#3a1818; }"
        )
        remove_btn.clicked.connect(self._remove_selected)
        wl_hdr_row.addWidget(remove_btn)
        root.addLayout(wl_hdr_row)

        self._wl_table = QTableWidget()
        self._wl_table.setColumnCount(3)
        self._wl_table.setHorizontalHeaderLabels(["Blueprint", "Grade", "Status"])
        self._wl_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._wl_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._wl_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._wl_table.verticalHeader().setVisible(False)
        self._wl_table.setAlternatingRowColors(True)
        self._wl_table.setStyleSheet(
            "QTableWidget { background:#080f18; alternate-background-color:#0a1520;"
            " color:#c8c8c8; gridline-color:#1e3a5a; border:1px solid #1e3a5a; }"
            "QHeaderView::section { background:#0d1a2a; color:#888888; border:none;"
            " padding:3px; font-size:10px; font-weight:bold; letter-spacing:1px; }"
            "QTableWidget::item:selected { background:#1a3a5a; color:#FFB347; }"
        )
        h = self._wl_table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._wl_table.itemSelectionChanged.connect(self._refresh_detail_table)
        root.addWidget(self._wl_table)

        # ── Materials detail table (for selected wishlist row) ────────────
        detail_hdr = QLabel("MATERIALS REQUIRED")
        detail_hdr.setStyleSheet(self._HDR_STYLE)
        root.addWidget(detail_hdr)

        self._detail_table = QTableWidget()
        self._detail_table.setColumnCount(4)
        self._detail_table.setHorizontalHeaderLabels(["Material", "Type", "Held", "Required"])
        self._detail_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._detail_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._detail_table.verticalHeader().setVisible(False)
        self._detail_table.setAlternatingRowColors(True)
        self._detail_table.setStyleSheet(
            "QTableWidget { background:#080f18; alternate-background-color:#0a1520;"
            " color:#c8c8c8; gridline-color:#1e3a5a; border:1px solid #1e3a5a; }"
            "QHeaderView::section { background:#0d1a2a; color:#888888; border:none;"
            " padding:3px; font-size:10px; font-weight:bold; letter-spacing:1px; }"
        )
        dh = self._detail_table.horizontalHeader()
        dh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        dh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        dh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        dh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self._detail_table, 1)

    # ── Helpers ──────────────────────────────────────────────────────────

    def _on_blueprint_changed(self):
        fdname = self._bp_combo.currentData()
        if fdname:
            max_g = self._blueprints.max_grade(fdname) or 5
            self._grade_spin.setMaximum(max_g)

    def _held_count(self, symbol: str) -> int:
        if self._state is None:
            return 0
        cat = self._blueprints.material_type(symbol).strip().lower()
        attr = _CATEGORY_STATE_ATTR.get(cat)
        if not attr:
            return 0
        src = getattr(self._state, attr, {}) or {}
        return int(src.get(symbol.lower(), 0))

    def _missing_count(self, fdname: str, grade: int) -> int:
        """Number of distinct materials where held < required."""
        reqs = self._blueprints.requirements(fdname, grade)
        return sum(1 for sym, qty in reqs.items() if self._held_count(sym) < qty)

    def missing_materials_for_wishlist(self) -> Dict[str, int]:
        """
        Aggregated {material_symbol: shortfall} across the whole wishlist —
        used by the alerting hook in main_window to check farming locations.
        """
        shortfall: Dict[str, int] = {}
        for entry in self._wishlist:
            reqs = self._blueprints.requirements(entry["fdname"], entry["grade"])
            for sym, qty in reqs.items():
                need = qty - self._held_count(sym)
                if need > 0:
                    shortfall[sym] = max(shortfall.get(sym, 0), need)
        return shortfall

    def _add_to_wishlist(self):
        fdname = self._bp_combo.currentData()
        if not fdname:
            return
        grade = self._grade_spin.value()
        if any(e["fdname"] == fdname and e["grade"] == grade for e in self._wishlist):
            return
        self._wishlist.append({"fdname": fdname, "grade": grade})
        self._store.save(self._wishlist)
        self._refresh_wishlist_table()

    def _remove_selected(self):
        row = self._wl_table.currentRow()
        if row < 0 or row >= len(self._wishlist):
            return
        del self._wishlist[row]
        self._store.save(self._wishlist)
        self._refresh_wishlist_table()

    def _refresh_wishlist_table(self):
        self._wl_table.setRowCount(len(self._wishlist))
        for r, entry in enumerate(self._wishlist):
            fdname = entry["fdname"]
            grade = entry["grade"]
            bp = self._blueprints.get(fdname) or {}
            name_item = QTableWidgetItem(f"{bp.get('display_name', fdname)} — {bp.get('short_name', '')}")
            grade_item = QTableWidgetItem(str(grade))
            grade_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            missing = self._missing_count(fdname, grade)
            if missing == 0:
                status_item = QTableWidgetItem("Ready")
                status_item.setForeground(QColor("#6BCB77"))
            else:
                status_item = QTableWidgetItem(f"{missing} missing")
                status_item.setForeground(QColor("#FF8C00"))

            self._wl_table.setItem(r, 0, name_item)
            self._wl_table.setItem(r, 1, grade_item)
            self._wl_table.setItem(r, 2, status_item)
        self._refresh_detail_table()

    def _refresh_detail_table(self):
        row = self._wl_table.currentRow()
        if row < 0 or row >= len(self._wishlist):
            self._detail_table.setRowCount(0)
            return
        entry = self._wishlist[row]
        reqs = self._blueprints.requirements(entry["fdname"], entry["grade"])
        rows = sorted(reqs.items(), key=lambda kv: self._blueprints.material_name(kv[0]))

        self._detail_table.setRowCount(len(rows))
        for r, (sym, qty) in enumerate(rows):
            held = self._held_count(sym)
            name_item = QTableWidgetItem(self._blueprints.material_name(sym))
            type_item = QTableWidgetItem(self._blueprints.material_type(sym))
            held_item = QTableWidgetItem(str(held))
            req_item = QTableWidgetItem(str(qty))
            for it in (held_item, req_item):
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            color = QColor("#6BCB77") if held >= qty else QColor("#FF6B6B")
            name_item.setForeground(color)
            held_item.setForeground(color)

            self._detail_table.setItem(r, 0, name_item)
            self._detail_table.setItem(r, 1, type_item)
            self._detail_table.setItem(r, 2, held_item)
            self._detail_table.setItem(r, 3, req_item)

    # ── Public API ────────────────────────────────────────────────────────

    def refresh(self, state) -> None:
        self._state = state
        self._refresh_wishlist_table()
