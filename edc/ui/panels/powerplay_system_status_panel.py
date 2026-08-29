"""PowerPlay System Status tab — shows Frontier's own official PowerPlay
data (control status + this cycle's Control Points tug-of-war) for two
sets of systems:

1. Every system your pledged power currently holds or contests, galaxy-
   wide, sorted by distance from your current location.
2. Systems you've personally visited that currently have any PowerPlay-
   active status (control/contested/blocked/takingControl) in Frontier's
   feed.

Frontier's feed doesn't name the Exploited/Fortified/Stronghold tier
directly (see fdev_powerplay.py's module docstring), so the tier label
here comes from EDSM's cache instead -- already integrated, already
name-keyed, sourced from real commanders' journals via EDSM's daily
dump.

Refresh is an explicit button, not automatic on every state tick --
this recomputes a coordinate lookup and up to ~1200 rows of scanning,
cheap in absolute terms but there's no reason to pay it on every
journal event, same reasoning as the Target Finder's own Search button.
"""
from __future__ import annotations

import logging
import math
from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame,
)

from edc.ui.style import CARD_STYLE, HDR_STYLE, LABEL_STYLE
from edc.ui.panels.powerplay_finder_panel import _STATE_COLORS

log = logging.getLogger(__name__)

_BAR_WIDTH = 10


def _progress_bar_text(qty: Optional[int], threshold: Optional[int]) -> str:
    """"{filled}{empty} NN%" using block characters, or "—" if there's
    nothing to show progress toward (blank threshold in Frontier's own
    feed -- seen on contested rows with no active vote either way)."""
    if not isinstance(qty, int) or not isinstance(threshold, int) or threshold <= 0:
        return "—"
    frac = max(0.0, min(1.0, qty / threshold))
    filled = round(frac * _BAR_WIDTH)
    bar = "█" * filled + "░" * (_BAR_WIDTH - filled)
    return f"{bar} {frac * 100:.0f}%"


def _tier_label(edsm_powerplay, system_name: str) -> str:
    if edsm_powerplay is None:
        return "—"
    rec = edsm_powerplay.get_controller_by_name(system_name)
    if not rec:
        return "—"
    return rec.get("power_state") or "—"


class PowerplaySystemStatusPanel(QWidget):
    def __init__(self, parent=None, repo=None, edsm_powerplay=None, fdev_powerplay=None):
        super().__init__(parent)
        self._repo = repo
        self._edsm_powerplay = edsm_powerplay
        self._fdev_powerplay = fdev_powerplay

        self._power: str = ""
        self._ref_x: float = 0.0
        self._ref_y: float = 0.0
        self._ref_z: float = 0.0

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 8)
        root.setSpacing(8)

        hdr_row = QHBoxLayout()
        self._power_label = QLabel("Power: —")
        self._power_label.setStyleSheet(LABEL_STYLE)
        hdr_row.addWidget(self._power_label)
        hdr_row.addStretch(1)
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setEnabled(False)
        self._refresh_btn.clicked.connect(self._do_refresh)
        hdr_row.addWidget(self._refresh_btn)
        root.addLayout(hdr_row)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet(LABEL_STYLE)
        self._status_label.setWordWrap(True)
        root.addWidget(self._status_label)

        self._power_frame, self._power_table = self._build_section("YOUR POWER'S SYSTEMS")
        root.addWidget(self._power_frame, 1)

        self._visited_frame, self._visited_table = self._build_section("VISITED — PP-ACTIVE SYSTEMS")
        root.addWidget(self._visited_frame, 1)

    def _build_section(self, title: str):
        frame = QFrame()
        frame.setStyleSheet(CARD_STYLE)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        hdr = QLabel(title)
        hdr.setStyleSheet(HDR_STYLE)
        layout.addWidget(hdr)

        table = QTableWidget(0, 5)
        table.setHorizontalHeaderLabels(["System", "Distance (ly)", "Tier", "Prediction", "Control Points"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(table)

        return frame, table

    def refresh(self, state, pp_activities=None) -> None:
        self._power = (getattr(state, "pp_power", None) or "").strip()
        self._ref_x = float(getattr(state, "system_x", 0.0) or 0.0)
        self._ref_y = float(getattr(state, "system_y", 0.0) or 0.0)
        self._ref_z = float(getattr(state, "system_z", 0.0) or 0.0)

        self._power_label.setText(f"Power: {self._power or '—'}")
        self._refresh_btn.setEnabled(bool(self._power))

    def _do_refresh(self):
        if not self._power:
            self._status_label.setText("No pledged power detected — fly somewhere first.")
            return
        if self._fdev_powerplay is None or not self._fdev_powerplay.has_data():
            self._status_label.setText("Frontier's official PowerPlay data isn't downloaded yet — try again shortly.")
            return

        age = " (today's data)" if not self._fdev_powerplay.is_stale() else " (cache outdated)"
        self._status_label.setText(f"Frontier official data active{age}.")

        self._fill_power_section()
        self._fill_visited_section()

    def _fill_power_section(self):
        rows = self._fdev_powerplay.get_systems_for_power(self._power)
        names = [row["system"] for row in rows]
        coords = self._repo.get_system_coords_for_names(names) if self._repo else {}

        entries = []
        for row in rows:
            xyz = coords.get(row["system"])
            if xyz is not None:
                dx, dy, dz = xyz[0] - self._ref_x, xyz[1] - self._ref_y, xyz[2] - self._ref_z
                dist = math.sqrt(dx * dx + dy * dy + dz * dz)
            else:
                dist = None
            entries.append((dist, row))

        # Unknown-distance systems (no EDDN-harvested coords yet) sort last,
        # not first -- (float("inf"), ...) beats None under Python's own
        # comparison rules for this exact purpose.
        entries.sort(key=lambda pair: pair[0] if pair[0] is not None else float("inf"))
        self._populate_table(self._power_table, entries)

    def _fill_visited_section(self):
        if not self._repo:
            return
        visited = self._repo.get_all_visited_system_names()
        entries = []
        for name in visited:
            row = self._fdev_powerplay.get_by_name(name)
            if row is None:
                continue
            state = (row.get("state") or "").strip().lower()
            if state not in ("control", "contested", "blocked", "takingcontrol"):
                continue
            entries.append((None, row))
        self._populate_table(self._visited_table, entries)

    def _populate_table(self, table: QTableWidget, entries: list):
        table.setRowCount(len(entries))
        for i, (dist, row) in enumerate(entries):
            name = row["system"]
            dist_txt = f"{dist:.1f}" if isinstance(dist, (int, float)) else "—"
            tier = _tier_label(self._edsm_powerplay, name)

            name_item = QTableWidgetItem(name)
            dist_item = QTableWidgetItem(dist_txt)
            dist_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            tier_item = QTableWidgetItem(tier)
            color = _STATE_COLORS.get(tier.lower())
            if color:
                tier_item.setForeground(QColor(color))

            prediction = row.get("prediction") or "—"
            pred_item = QTableWidgetItem(prediction)
            pred_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            # Whichever direction has an active threshold this cycle is
            # the one worth showing -- a system with no undermining
            # pressure has thr_against blank in Frontier's own feed.
            if row.get("thr_for") is not None:
                cp_text = _progress_bar_text(row.get("qty_for"), row.get("thr_for"))
            else:
                cp_text = _progress_bar_text(row.get("qty_against"), row.get("thr_against"))
            cp_item = QTableWidgetItem(cp_text)

            table.setItem(i, 0, name_item)
            table.setItem(i, 1, dist_item)
            table.setItem(i, 2, tier_item)
            table.setItem(i, 3, pred_item)
            table.setItem(i, 4, cp_item)
