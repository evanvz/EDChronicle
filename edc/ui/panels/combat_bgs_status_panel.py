"""Combat tab's System Status sub-panel -- radius search over
system_bgs_status/system_res_sites (War/CivilWar conflicts, multi-state
factions, RES tier presence), same self-contained radius-search shape as
market_panel.py (own repo reference, own QThread search worker with its
own DB connection per the project's cross-thread SQLite rule)."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt, QObject, QThread, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox,
    QTableWidget, QTableWidgetItem, QHeaderView,
)

from edc.ui import formatting as fmt

log = logging.getLogger(__name__)

_LABEL_STYLE = "color:#c8c8c8; background:transparent; border:none;"
_ACCENT_BG = QColor(26, 58, 90)   # squadron-relevant row highlight
_ACCENT_FG = QColor(255, 179, 71)


class _SearchWorker(QObject):
    finished = pyqtSignal(list, list)  # (bgs_status_results, res_results)

    def __init__(self, db_path, x, y, z, radius_ly):
        super().__init__()
        self._db_path = db_path
        self._x, self._y, self._z, self._radius_ly = x, y, z, radius_ly

    def run(self):
        from persistence.database import Database
        from persistence.repository import Repository

        db = Database(self._db_path)
        repo = Repository(db)
        try:
            bgs_results = repo.search_bgs_status_near(self._x, self._y, self._z, float(self._radius_ly))
            res_results = repo.search_res_sites_near(self._x, self._y, self._z, float(self._radius_ly))
        except Exception:
            log.exception("BGS/RES status search failed")
            bgs_results, res_results = [], []
        finally:
            db.close()
        self.finished.emit(bgs_results, res_results)


def _merge_results(bgs_results: List[dict], res_results: List[dict]) -> List[Dict[str, Any]]:
    """One row per system_name, combining conflict/faction-state data with
    RES tier data -- most systems will only have one of the two."""
    merged: Dict[str, Dict[str, Any]] = {}
    for r in bgs_results:
        merged[r["system_name"]] = {
            "system_name": r["system_name"], "distance_ly": r["distance_ly"],
            "conflicts": r["conflicts"], "faction_states": r["faction_states"],
            "tiers": [], "data_timestamp": r["data_timestamp"],
        }
    for r in res_results:
        row = merged.setdefault(r["system_name"], {
            "system_name": r["system_name"], "distance_ly": r["distance_ly"],
            "conflicts": [], "faction_states": [], "tiers": [], "data_timestamp": r["data_timestamp"],
        })
        row["tiers"] = r["tiers"]
        if r["data_timestamp"] > row.get("data_timestamp", ""):
            row["data_timestamp"] = r["data_timestamp"]
    return sorted(merged.values(), key=lambda r: r["distance_ly"])


def _won_days_text(won_days) -> str:
    return str(won_days) if isinstance(won_days, int) else "?"


def _conflicts_text(conflicts: List[dict]) -> str:
    if not conflicts:
        return ""
    parts = []
    for c in conflicts:
        label = "War" if c.get("war_type") == "war" else "Civil War"
        parts.append(
            f"{label}: {c.get('faction1')} ({_won_days_text(c.get('won_days1'))}) "
            f"vs {c.get('faction2')} ({_won_days_text(c.get('won_days2'))})"
        )
    return " | ".join(parts)


def _faction_states_text(faction_states: List[dict]) -> str:
    if not faction_states:
        return ""
    parts = []
    for f in faction_states:
        state_bits = []
        for s in (f.get("active_states") or []):
            if isinstance(s, dict) and s.get("State"):
                state_bits.append(s["State"])
        for bucket, label in (("pending_states", "pending"), ("recovering_states", "recovering")):
            for s in (f.get(bucket) or []):
                if isinstance(s, dict) and s.get("State"):
                    state_bits.append(f"{s['State']} ({label})")
        if state_bits:
            parts.append(f"{f.get('name')}: {', '.join(state_bits)}")
    return " | ".join(parts)


class CombatBgsStatusPanel(QWidget):
    """Owns all widgets and refresh logic for the Combat > System Status
    sub-tab. Receives state via refresh(state); knows nothing about
    main_window or CombatPanel."""

    def __init__(self, repo, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._system: str = ""
        self._ref_x: float = 0.0
        self._ref_y: float = 0.0
        self._ref_z: float = 0.0
        self._squadron_faction: Optional[str] = None
        self._pp_power: str = ""
        self._search_thread: Optional[QThread] = None
        self._search_worker: Optional[_SearchWorker] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 8)
        root.setSpacing(6)

        self._location_label = QLabel("Location: —")
        self._location_label.setStyleSheet(_LABEL_STYLE)
        root.addWidget(self._location_label)

        row = QHBoxLayout()
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

        row.addWidget(range_label)
        row.addWidget(self._range_spin)
        row.addWidget(self._search_btn)
        row.addStretch(1)
        root.addLayout(row)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet(_LABEL_STYLE)
        root.addWidget(self._status_label)

        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(["System", "Distance", "War / Civil War", "Faction States", "RES Tiers"])
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.setSortingEnabled(False)
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self._table, 1)

    def refresh(self, state) -> None:
        self._system = (getattr(state, "system", None) or "").strip()
        self._ref_x = float(getattr(state, "system_x", 0.0) or 0.0)
        self._ref_y = float(getattr(state, "system_y", 0.0) or 0.0)
        self._ref_z = float(getattr(state, "system_z", 0.0) or 0.0)
        self._pp_power = (getattr(state, "pp_power", None) or "").strip()
        self._location_label.setText(f"Location: {self._system or '—'}")
        self._search_btn.setEnabled(bool(self._system))

    def _start_search(self) -> None:
        if not self._system:
            self._status_label.setText("No system location data yet — jump to a system first.")
            return
        if self._search_thread and self._search_thread.isRunning():
            return

        try:
            overview = self._repo.get_player_faction_overview()
            self._squadron_faction = overview["faction_name"] if overview else None
        except Exception:
            log.exception("Failed to load squadron faction for highlight matching")
            self._squadron_faction = None

        self._search_btn.setEnabled(False)
        self._status_label.setText(f"Searching within {self._range_spin.value()} ly of {self._system}…")
        self._table.setRowCount(0)

        self._search_worker = _SearchWorker(
            self._repo.db.db_path, self._ref_x, self._ref_y, self._ref_z, self._range_spin.value(),
        )
        self._search_thread = QThread()
        self._search_worker.moveToThread(self._search_thread)
        self._search_thread.started.connect(self._search_worker.run)
        self._search_worker.finished.connect(self._on_search_finished)
        self._search_worker.finished.connect(self._search_thread.quit)
        self._search_thread.start()

    def _on_search_finished(self, bgs_results: list, res_results: list) -> None:
        self._search_btn.setEnabled(True)
        rows = _merge_results(bgs_results, res_results)
        self._status_label.setText(
            f"Found {len(rows)} system{'s' if len(rows) != 1 else ''} with active War/CivilWar, "
            f"multi-state factions, or RES presence within {self._range_spin.value()} ly of {self._system}."
        )

        self._table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            relevant_names = {n for n in (self._squadron_faction, self._pp_power) if n}
            is_squadron_relevant = bool(
                relevant_names and (
                    any(f.get("name") in relevant_names for f in row["faction_states"])
                    or any(c.get("faction1") in relevant_names or c.get("faction2") in relevant_names for c in row["conflicts"])
                )
            )
            age_txt, _ = fmt.relative_time(row.get("data_timestamp") or "")

            items = [
                QTableWidgetItem(row["system_name"]),
                QTableWidgetItem(f"{row['distance_ly']:.1f} ly"),
                QTableWidgetItem(_conflicts_text(row["conflicts"])),
                QTableWidgetItem(_faction_states_text(row["faction_states"])),
                QTableWidgetItem(", ".join(row["tiers"])),
            ]
            for c, item in enumerate(items):
                if is_squadron_relevant:
                    item.setBackground(_ACCENT_BG)
                    item.setForeground(_ACCENT_FG)
                self._table.setItem(r, c, item)
            self._table.item(r, 0).setToolTip(f"Last confirmed {age_txt}")
