# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
"""PowerPlay Watch List: reinforcement vs undermining this cycle for every
watched system (PowerPlay task systems, supporting systems of Acquisition
tasks, squadron-faction systems your power holds -- see bgs_tasks.pp_watch),
a tab in the PowerPlay window. Data comes from the Player Faction panel,
which already holds the repo, BGS tick, pledge and live state."""
from __future__ import annotations

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from edc.core.bgs_tasks import _hours_ago, distance_text, pp_watch, watch_rows
from edc.ui.style import HDR_STYLE, TABLE_STYLE, bulk_table_fill

log = logging.getLogger(__name__)

_COLUMNS = ["System", "Why watched", "State", "Reinforced", "Decay", "Attack", "Since tick", "Data", "Distance"]
_RED, _AMBER, _GREEN, _DIM = "#FF6B6B", "#FFB347", "#6BCB77", "#777777"
_STATUS_COLOR = {"attack": _RED, "unknown": _AMBER, "decay": _AMBER, "holding": _GREEN, None: _DIM}


class _NumItem(QTableWidgetItem):
    """Sorts by the number behind the text (None sorts first)."""

    def __init__(self, text: str, value):
        super().__init__(text)
        self._value = value if value is not None else float("-inf")

    def __lt__(self, other):
        return self._value < getattr(other, "_value", float("-inf"))


class PowerPlayWatchPanel(QWidget):
    def __init__(self, panel, parent=None):
        super().__init__(parent)
        self._panel = panel
        self._rows = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 8)
        hdr_row = QHBoxLayout()
        hdr = QLabel("POWERPLAY WATCH LIST — REINFORCEMENT VS UNDERMINING THIS CYCLE")
        hdr.setStyleSheet(HDR_STYLE)
        hdr_row.addWidget(hdr)
        hdr_row.addStretch(1)
        self._only_attacked = QCheckBox("Show only attacked / unclear")
        self._only_attacked.setChecked(True)
        self._only_attacked.toggled.connect(self._fill)
        hdr_row.addWidget(self._only_attacked)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)
        hdr_row.addWidget(refresh_btn)
        layout.addLayout(hdr_row)

        self._status = QLabel("")
        self._status.setStyleSheet("background:transparent; border:none; color:#888888; font-size:11px;")
        layout.addWidget(self._status)

        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet(TABLE_STYLE)
        h = self._table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in range(1, len(_COLUMNS)):
            h.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        h.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)   # keep watch_rows' order until a header is clicked
        self._table.cellClicked.connect(self._copy_system)
        self._table.itemSelectionChanged.connect(self._update_add_button)
        layout.addWidget(self._table, 1)

        foot = QHBoxLayout()
        hint = QLabel("Click a row to copy the system name. Red = real undermining this cycle (grew after the "
                      "reset). Amber = only the weekly decay (counted as undermining, set at the reset) is ahead; "
                      "decay alone can't drop a state.")
        hint.setStyleSheet("color:#9aa4b0; font-size:11px; background:transparent;")
        foot.addWidget(hint, 1)
        self._add_btn = QPushButton("Add as BGS task (Reinforcement)")
        self._add_btn.setEnabled(False)
        self._add_btn.clicked.connect(self._add_task)
        foot.addWidget(self._add_btn)
        layout.addLayout(foot)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()

    def refresh(self) -> None:
        repo = self._panel._repo
        getter = getattr(self._panel, "pledged_power_getter", None)
        pledged = getter() if getter else ""
        since = getattr(self._panel, "_latest_known_tick", None) or "1970-01-01T00:00:00Z"
        try:
            watch = pp_watch(repo, pledged, getattr(self._panel, "edsm_powerplay", None))
            self._rows = watch_rows(repo, since, watch)
        except Exception:
            log.exception("Failed to build PowerPlay watch list")
            self._rows = []
        losing = sum(1 for r in self._rows if r["status"] == "attack")
        behind = sum(1 for r in self._rows if r["status"] == "decay")
        unknown = sum(1 for r in self._rows if r["status"] == "unknown")
        no_data = sum(1 for r in self._rows if r["undermining"] is None)
        self._status.setText(
            f"{len(self._rows)} systems watched · {losing} under attack · {behind} behind on weekly decay · "
            f"{unknown} undermined, decay or attack unclear · "
            f"{no_data} with no reading since the Thursday reset"
            + ("" if pledged else " · not pledged: only PowerPlay task systems are watched"))
        self._fill()

    def _distances(self) -> dict:
        state = getattr(self._panel, "_last_state", None)
        here_name = (getattr(state, "system", None) or "").strip()
        here = None
        if getattr(state, "system_x", None) is not None:
            here = (state.system_x, state.system_y, state.system_z)
        coords = self._panel._repo.get_system_coords_for_names([r["name"] for r in self._rows])
        return {r["name"]: distance_text(here, coords.get(r["name"]),
                                         same_system=here_name.lower() == r["name"].lower())
                for r in self._rows}

    def _fill(self) -> None:
        rows = [r for r in self._rows
                if r["status"] in ("attack", "unknown") or not self._only_attacked.isChecked()]
        dist = self._distances() if rows else {}
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(rows))
        with bulk_table_fill(self._table):
            for i, r in enumerate(rows):
                color = _STATUS_COLOR[r["status"]]
                data = r["observed_at"] and f"{_hours_ago(r['observed_at'])} ({r['source']})"
                cells = [
                    QTableWidgetItem(r["name"]),
                    QTableWidgetItem(r["why"]),
                    QTableWidgetItem(r["state"] or "—"),
                    _NumItem("—" if r["reinforcement"] is None else f"{r['reinforcement']:,}", r["reinforcement"]),
                    _NumItem("—" if r["decay"] is None else
                             (f"{r['decay']:,}?" if r["status"] == "unknown" else f"{r['decay']:,}"), r["decay"]),
                    _NumItem("?" if r["status"] == "unknown" else
                             ("—" if not r["attack"] else f"+{r['attack']:,}"), r["attack"]),
                    _NumItem("?" if r["gained"] is None and r["status"] else
                             ("—" if not r["gained"] else f"+{r['gained']:,}"), r["gained"]),
                    QTableWidgetItem(data or "no data yet"),
                    QTableWidgetItem(dist.get(r["name"], "")),
                ]
                for c, item in enumerate(cells):
                    if c in (3, 4, 5, 6):
                        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    if c in (0, 5) or (c == 4 and r["status"] in ("decay", "unknown")):
                        item.setForeground(QColor(color))
                    item.setData(Qt.ItemDataRole.UserRole, r)
                    self._table.setItem(i, c, item)
        self._table.setSortingEnabled(True)
        if not rows:
            self._status.setText(self._status.text() + " — nothing under attack right now")
        self._update_add_button()

    def _selected(self):
        items = self._table.selectedItems()
        return items[0].data(Qt.ItemDataRole.UserRole) if items else None

    def _update_add_button(self) -> None:
        r = self._selected()
        self._add_btn.setEnabled(bool(r) and r["why"] != "PowerPlay task")

    def _copy_system(self, row: int, _col: int) -> None:
        item = self._table.item(row, 0)
        if item:
            QApplication.clipboard().setText(item.text())
            self._status.setText(f"Copied: {item.text()}")

    def _add_task(self) -> None:
        r = self._selected()
        if not r:
            return
        try:
            self._panel._repo.add_bgs_task(r["name"], "powerplay", pp_mode="Reinforcement")
        except Exception:
            log.exception("Failed to add BGS task for %s", r["name"])
            return
        self._status.setText(f"Added {r['name']} to BGS Tasks (PowerPlay, Reinforcement)")
        self._panel.notify_bgs_activity()
        self.refresh()
        bgs_changed = getattr(self._panel, "bgs_tasks_changed", None)
        if bgs_changed is not None:
            bgs_changed.emit()
