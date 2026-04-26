"""PowerPlay Target Finder panel — queries Spansh for nearby PP systems."""
from __future__ import annotations

import logging
from typing import List, Optional

from PyQt6.QtCore import Qt, QObject, QThread, pyqtSignal
from PyQt6.QtGui import QClipboard
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QSpinBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QFrame, QApplication,
)

from edc.core.spansh_client import SpanshClient, SpanshSystem
from edc.core.powerplay_activities import PowerPlayActivityTable

log = logging.getLogger(__name__)

_SHORT_POWER = {
    "Aisling Duval":        "Aisling",
    "Arissa Lavigny-Duval": "ALD",
    "Archon Delaine":       "Archon",
    "Denton Patreus":       "Patreus",
    "Edmund Mahon":         "Mahon",
    "Felicia Winters":      "Winters",
    "Jerome Archer":        "Archer",
    "Li Yong-Rui":          "LYR",
    "Nakato Kaine":         "Kaine",
    "Pranav Antal":         "Antal",
    "Yuri Grom":            "Grom",
    "Zemina Torval":        "Torval",
}

_MISSION_OPTIONS = [
    ("Reinforcement systems", "reinforcement"),
    ("Undermining targets",   "undermining"),
    ("Acquisition systems",   "acquisition"),
    ("All PP systems",        "all"),
]

_FACILITY_OPTIONS = [
    ("Any facility",  "any"),
    ("Has Megaship",  "megaship"),
    ("Has Settlement","settlement"),
]


# ── Worker ────────────────────────────────────────────────────────────────────

class _SearchWorker(QObject):
    finished = pyqtSignal(list, str)   # (results, error)

    def __init__(self, power, mission, ref_x, ref_y, ref_z,
                 range_ly, facility):
        super().__init__()
        self._power   = power
        self._mission = mission
        self._ref_x     = ref_x
        self._ref_y     = ref_y
        self._ref_z     = ref_z
        self._range_ly  = range_ly
        self._facility  = facility

    def run(self):
        client = SpanshClient()
        results, error = client.search_pp_systems(
            power=self._power,
            mission=self._mission,
            ref_x=self._ref_x,
            ref_y=self._ref_y,
            ref_z=self._ref_z,
            range_ly=self._range_ly,
            facility=self._facility,
        )
        self.finished.emit(results, error)


# ── Panel ─────────────────────────────────────────────────────────────────────

class PowerplayFinderPanel(QWidget):
    """
    Standalone widget.  Call refresh(state) whenever state changes.
    Does not interact with main_window or other panels directly.
    """

    _CARD_STYLE  = "QFrame { background:#0d1a2a; border:1px solid #1e3a5a; border-radius:5px; }"
    _HDR_STYLE   = "color:#555555; font-size:10px; font-weight:bold; letter-spacing:1px; background:transparent; border:none;"
    _LABEL_STYLE = "background:transparent; border:none; color:#c8c8c8;"

    def __init__(self, parent=None):
        super().__init__(parent)

        self._power:        str   = ""
        self._system:       str   = ""
        self._ref_x:        float = 0.0
        self._ref_y:        float = 0.0
        self._ref_z:        float = 0.0
        self._thread:       Optional[QThread] = None
        self._worker:       Optional[_SearchWorker] = None
        self._pp_activities: Optional[PowerPlayActivityTable] = None

        _ETHOS_COLORS = {
            "Combat":  "#FF6B6B",
            "Finance": "#FFD93D",
            "Social":  "#6BCB77",
            "Covert":  "#C77DFF",
        }
        self._ethos_colors = _ETHOS_COLORS

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 8)
        root.setSpacing(6)

        # ── Controls card ────────────────────────────────────────────────
        ctrl_frame = QFrame()
        ctrl_frame.setStyleSheet(self._CARD_STYLE)
        ctrl_layout = QVBoxLayout(ctrl_frame)
        ctrl_layout.setContentsMargins(8, 6, 8, 8)
        ctrl_layout.setSpacing(6)

        hdr = QLabel("POWERPLAY TARGET FINDER")
        hdr.setStyleSheet(self._HDR_STYLE)
        ctrl_layout.addWidget(hdr)

        # Row 1: power + system
        info_row = QHBoxLayout()
        info_row.setSpacing(12)
        self._power_label = QLabel("Power: —")
        self._power_label.setStyleSheet(self._LABEL_STYLE)
        self._system_label = QLabel("Location: —")
        self._system_label.setStyleSheet(self._LABEL_STYLE)
        info_row.addWidget(self._power_label)
        info_row.addWidget(self._system_label)
        info_row.addStretch()
        ctrl_layout.addLayout(info_row)

        # Row 2: mission + facility + range + button
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)

        self._mission_combo = QComboBox()
        self._mission_combo.setStyleSheet("background:#0a1520; color:#c8c8c8; border:1px solid #1e3a5a;")
        for label, _ in _MISSION_OPTIONS:
            self._mission_combo.addItem(label)

        self._facility_combo = QComboBox()
        self._facility_combo.setStyleSheet("background:#0a1520; color:#c8c8c8; border:1px solid #1e3a5a;")
        for label, _ in _FACILITY_OPTIONS:
            self._facility_combo.addItem(label)

        range_label = QLabel("Range:")
        range_label.setStyleSheet(self._LABEL_STYLE)

        self._range_spin = QSpinBox()
        self._range_spin.setRange(25, 500)
        self._range_spin.setSingleStep(25)
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

        filter_row.addWidget(self._mission_combo, 2)
        filter_row.addWidget(self._facility_combo, 2)
        filter_row.addWidget(range_label)
        filter_row.addWidget(self._range_spin, 1)
        filter_row.addWidget(self._search_btn)
        ctrl_layout.addLayout(filter_row)

        # Row 3: ethos bonus hint
        self._ethos_label = QLabel("")
        self._ethos_label.setTextFormat(Qt.TextFormat.RichText)
        self._ethos_label.setStyleSheet("background:transparent; border:none;")
        self._ethos_label.setVisible(False)
        ctrl_layout.addWidget(self._ethos_label)

        self._mission_combo.currentIndexChanged.connect(self._update_ethos_label)

        root.addWidget(ctrl_frame)

        # ── Status label ─────────────────────────────────────────────────
        self._status_label = QLabel("Select filters and press Search.")
        self._status_label.setStyleSheet("color:#888888; font-size:10px; background:transparent;")
        root.addWidget(self._status_label)

        # ── Results table ─────────────────────────────────────────────────
        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(["System", "Dist (ly)", "PP State", "Powers Present", "Facilities"])
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
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self._table.cellDoubleClicked.connect(self._copy_system_name)
        root.addWidget(self._table, 1)

        copy_hint = QLabel("Double-click a row to copy system name to clipboard.")
        copy_hint.setStyleSheet("color:#555555; font-size:9px; background:transparent;")
        root.addWidget(copy_hint)

    # ── Public API ────────────────────────────────────────────────────────

    def refresh(self, state, pp_activities: Optional[PowerPlayActivityTable] = None) -> None:
        self._power  = (getattr(state, "pp_power",  None) or "").strip()
        self._system = (getattr(state, "system",    None) or "").strip()
        self._ref_x  = float(getattr(state, "system_x", 0.0) or 0.0)
        self._ref_y  = float(getattr(state, "system_y", 0.0) or 0.0)
        self._ref_z  = float(getattr(state, "system_z", 0.0) or 0.0)
        if pp_activities is not None:
            self._pp_activities = pp_activities

        self._power_label.setText(f"Power: {self._power or '—'}")
        self._system_label.setText(f"Location: {self._system or '—'}")
        self._search_btn.setEnabled(bool(self._power))
        self._update_ethos_label()

    # ── Ethos hint ───────────────────────────────────────────────────────

    def _update_ethos_label(self):
        mission = self._mission_key()
        if not self._power or not self._pp_activities or mission == "all":
            self._ethos_label.setVisible(False)
            return

        ethos = self._pp_activities.get_power_ethos(self._power, mission)
        if not ethos:
            self._ethos_label.setVisible(False)
            return

        acts = self._pp_activities.get_actions(mission)
        bonus_names = [
            a.action for a in acts
            if self._power in a.bonus_powers and a.merits == "yes" and not a.contested_only
        ]

        color = self._ethos_colors.get(ethos, "#FFB347")
        preview = " · ".join(bonus_names[:4])
        if len(bonus_names) > 4:
            preview += f" +{len(bonus_names) - 4} more"

        self._ethos_label.setText(
            f'<span style="color:#888888;font-size:10px;">Your bonus: </span>'
            f'<span style="color:{color};font-size:10px;font-weight:bold;">{ethos}</span>'
            f'<span style="color:#666666;font-size:10px;"> — {preview}</span>'
        )
        self._ethos_label.setVisible(True)

    # ── Search ────────────────────────────────────────────────────────────

    def _mission_key(self) -> str:
        idx = self._mission_combo.currentIndex()
        return _MISSION_OPTIONS[idx][1] if 0 <= idx < len(_MISSION_OPTIONS) else "reinforcement"

    def _facility_key(self) -> str:
        idx = self._facility_combo.currentIndex()
        return _FACILITY_OPTIONS[idx][1] if 0 <= idx < len(_FACILITY_OPTIONS) else "any"

    def _start_search(self):
        if not self._power:
            self._status_label.setText("No pledged power detected — fly somewhere first.")
            return
        if not self._system or (self._ref_x == 0.0 and self._ref_y == 0.0 and self._ref_z == 0.0):
            self._status_label.setText("No system location data yet — jump to a system first.")
            return
        if self._thread and self._thread.isRunning():
            return

        self._search_btn.setEnabled(False)
        self._status_label.setText("Searching Spansh…")
        self._table.setRowCount(0)

        self._worker = _SearchWorker(
            power=self._power,
            mission=self._mission_key(),
            ref_x=self._ref_x,
            ref_y=self._ref_y,
            ref_z=self._ref_z,
            range_ly=self._range_spin.value(),
            facility=self._facility_key(),
        )
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_results)
        self._worker.finished.connect(self._thread.quit)
        self._thread.start()

    def _on_results(self, results: List[SpanshSystem], error: str):
        from PyQt6.QtGui import QColor
        self._search_btn.setEnabled(True)
        if error:
            self._status_label.setText(f"Error: {error}")
            return

        self._status_label.setText(
            f"Found {len(results)} system{'s' if len(results) != 1 else ''} "
            f"within {self._range_spin.value()} ly."
        )
        self._table.setRowCount(len(results))
        for row, sys in enumerate(results):
            name_item  = QTableWidgetItem(sys.name)
            dist_item  = QTableWidgetItem(f"{sys.distance:.1f}")
            state_item = QTableWidgetItem(sys.pp_state or sys.controlling_power or "—")
            fac_item   = QTableWidgetItem(sys.facility_summary())

            dist_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            # Colour the state cell
            state_lower = (sys.pp_state or "").lower()
            if "fortified" in state_lower or "stronghold" in state_lower:
                state_item.setForeground(QColor("#4D96FF"))
            elif "contested" in state_lower or "undermining" in state_lower:
                state_item.setForeground(QColor("#FF6B6B"))
            elif "exploited" in state_lower:
                state_item.setForeground(QColor("#FFD93D"))

            # Powers present column — each power individually coloured
            all_p = sys.all_powers()
            if all_p:
                parts = []
                for p in all_p[:3]:
                    abbr  = _SHORT_POWER.get(p, p.split()[-1])
                    color = "#4D96FF" if p == self._power else "#FF8C00"
                    parts.append(f'<span style="color:{color};">{abbr}</span>')
                if len(all_p) > 3:
                    parts.append(f'<span style="color:#888888;">+{len(all_p) - 3}</span>')
                html = ' <span style="color:#444444;">/</span> '.join(parts)
            else:
                html = '<span style="color:#555555;">—</span>'

            power_label = QLabel()
            power_label.setTextFormat(Qt.TextFormat.RichText)
            power_label.setText(html)
            power_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            power_label.setStyleSheet("background:transparent; padding:2px;")

            self._table.setItem(row, 0, name_item)
            self._table.setItem(row, 1, dist_item)
            self._table.setItem(row, 2, state_item)
            self._table.setCellWidget(row, 3, power_label)
            self._table.setItem(row, 4, fac_item)

    def _copy_system_name(self, row: int, _col: int):
        item = self._table.item(row, 0)
        if item:
            QApplication.clipboard().setText(item.text())
            self._status_label.setText(f"Copied: {item.text()}")
