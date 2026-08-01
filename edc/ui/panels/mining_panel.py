"""Mining panel — session stats plus a ring/hotspot target finder (search by distance)."""
from __future__ import annotations

import logging
from typing import List, Optional

from PyQt6.QtCore import Qt, QObject, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QSpinBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QFrame,
)

from edc.core.spansh_client import SpanshClient, MiningRingResult

log = logging.getLogger(__name__)

_CARD_STYLE = "QFrame { background:#0d1a2a; border:1px solid #1e3a5a; border-radius:5px; }"
_HDR_STYLE = "color:#555555; font-size:10px; font-weight:bold; letter-spacing:1px; background:transparent; border:none;"
_LABEL_STYLE = "background:transparent; border:none; color:#c8c8c8;"


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


class MiningPanel(QWidget):
    """
    Owns all widgets and refresh logic for the Mining tab.
    Receives state via refresh(state). Knows nothing about
    main_window or repo — "where to sell" is delegated via
    sell_search_requested, letting main_window switch tabs and
    query the Market panel itself.
    """

    sell_search_requested = pyqtSignal(str)  # commodity display name

    def __init__(self, parent=None):
        super().__init__(parent)

        self._system: str = ""
        self._ref_x: float = 0.0
        self._ref_y: float = 0.0
        self._ref_z: float = 0.0
        self._thread: Optional[QThread] = None
        self._worker: Optional[_RingSearchWorker] = None

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
        self._sell_hdr.setStyleSheet("color:#555555; font-size:10px; background:transparent; border:none;")
        self._sell_hdr.setVisible(False)
        stats_layout.addWidget(self._sell_hdr)

        self._sell_row = QHBoxLayout()
        self._sell_row.setSpacing(4)
        stats_layout.addLayout(self._sell_row)

        root.addWidget(stats_frame)

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

        range_label = QLabel("Range:")
        range_label.setStyleSheet(_LABEL_STYLE)
        self._range_spin = QSpinBox()
        self._range_spin.setRange(10, 500)
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

        row.addWidget(self._material_edit, 1)
        row.addWidget(range_label)
        row.addWidget(self._range_spin)
        row.addWidget(self._search_btn)
        finder_layout.addLayout(row)

        note = QLabel(
            "Searches the nearest ~500 high-reserve ring bodies within range for a hotspot "
            "match — very rare materials near the edge of a large range may not surface."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#555555; font-size:9px; background:transparent; border:none;")
        finder_layout.addWidget(note)

        root.addWidget(finder_frame)

        # ── Status + results ──────────────────────────────────────────────
        self._status_label = QLabel("Enter a material and press Search.")
        self._status_label.setStyleSheet("color:#888888; font-size:10px; background:transparent;")
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

    def refresh(self, state) -> None:
        self._system = (getattr(state, "system", None) or "").strip()
        self._ref_x = float(getattr(state, "system_x", 0.0) or 0.0)
        self._ref_y = float(getattr(state, "system_y", 0.0) or 0.0)
        self._ref_z = float(getattr(state, "system_z", 0.0) or 0.0)
        self._location_label.setText(f"Location: {self._system or '—'}")
        self._search_btn.setEnabled(bool(self._system))

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
                " border-radius:3px; padding:2px 8px; font-size:10px; }"
                "QPushButton:hover { background:#2a3a2a; }"
            )
            btn.clicked.connect(lambda checked=False, n=name: self.sell_search_requested.emit(n))
            self._sell_row.addWidget(btn)
        self._sell_row.addStretch(1)

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
        if error:
            self._status_label.setText(f"Error: {error}")
            return

        self._status_label.setText(
            f"Found {len(results)} ring{'s' if len(results) != 1 else ''} "
            f"within {self._range_spin.value()} ly."
        )
        self._table.setRowCount(len(results))
        for row, r in enumerate(results):
            name_item = QTableWidgetItem(r.system_name)
            body_item = QTableWidgetItem(r.body_name)
            type_item = QTableWidgetItem(r.ring_type)
            reserve_item = QTableWidgetItem(r.reserve_level)
            dist_item = QTableWidgetItem(f"{r.distance:.1f}")
            hotspot_item = QTableWidgetItem(str(r.hotspot_count))
            for it in (type_item, reserve_item, dist_item, hotspot_item):
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            self._table.setItem(row, 0, name_item)
            self._table.setItem(row, 1, body_item)
            self._table.setItem(row, 2, type_item)
            self._table.setItem(row, 3, reserve_item)
            self._table.setItem(row, 4, dist_item)
            self._table.setItem(row, 5, hotspot_item)
