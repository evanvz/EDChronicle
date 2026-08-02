"""Player Faction panel — tracks your squadron-aligned minor faction across
every system it has a presence in, with a recommended action per system.

Only ever shows data if the game has reported SquadronFaction:true for some
faction at some point — most commanders aren't in a squadron aligned to a
minor faction, and that's a legitimate, permanent empty state, not a bug.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt, QObject, QThread, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame,
)

from edc.core.edsm_faction_lookup import fetch_system_factions, ERROR_BLOCKED, ERROR_NOT_FOUND

log = logging.getLogger(__name__)

_CARD_STYLE = "QFrame { background:#0d1a2a; border:1px solid #1e3a5a; border-radius:5px; }"
_HDR_STYLE = "color:#555555; font-size:10px; font-weight:bold; letter-spacing:1px; background:transparent; border:none;"


class _NumericTableWidgetItem(QTableWidgetItem):
    """Sorts by an actual numeric value instead of the displayed string
    (plain QTableWidgetItem sorting would put "42.0%" before "9.0%")."""

    def __init__(self, text: str, sort_value: float):
        super().__init__(text)
        self._sort_value = sort_value

    def __lt__(self, other):
        if isinstance(other, _NumericTableWidgetItem):
            return self._sort_value < other._sort_value
        return super().__lt__(other)


def _parse_states(raw) -> List[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [
        str(s.get("State"))
        for s in data
        if isinstance(s, dict) and s.get("State")
    ]


def derive_bgs_action(sys_rec: Dict[str, Any]) -> Tuple[str, str]:
    """Returns (action_text, color_hex) advising what this system needs, if anything."""
    active = {s.lower() for s in _parse_states(sys_rec.get("active_states"))}
    pending = {s.lower() for s in _parse_states(sys_rec.get("pending_states"))}
    recovering = {s.lower() for s in _parse_states(sys_rec.get("recovering_states"))}
    faction_state = (sys_rec.get("faction_state") or "").strip().lower()
    if faction_state:
        active.add(faction_state)
    is_controlling = bool(sys_rec.get("is_controlling"))

    if "war" in active or "civilwar" in active:
        return ("⚔ War/Civil War active — combat kills for this faction help win it.", "#FF6B6B")
    if "election" in active:
        return ("🗳 Election in progress — trade/mission activity favors your faction's chances.", "#FFD93D")
    if "civilunrest" in active:
        return ("⚠ Civil Unrest — security/combat missions help stabilize.", "#FF8C00")
    if "lockdown" in active:
        return ("🔒 Lockdown — reduced mission availability; ride it out.", "#888888")
    if "outbreak" in active:
        return ("🦠 Outbreak — deliver medicines to help resolve.", "#FF6B6B")
    if "famine" in active:
        return ("🍞 Famine — deliver food supplies.", "#FF8C00")
    if "drought" in active:
        return ("💧 Drought — deliver water.", "#FF8C00")
    if "blight" in active:
        return ("🌾 Blight — deliver agricultural supplies.", "#FF8C00")
    if "boom" in active:
        return ("📈 Boom — thriving economy; keep trading here to sustain it.", "#6BCB77")
    if "bust" in active:
        return ("📉 Bust — economic decline; less profitable to trade here for now.", "#888888")

    if "expansion" in pending:
        return ("🚀 Expansion pending — keep up trade/missions/bounties here to complete it.", "#6BCB77")
    if "retreat" in pending:
        return ("⬇ Retreat pending — losing ground; needs support activity to avoid losing this system.", "#FF6B6B")
    if "war" in pending or "civilwar" in pending:
        return ("⚠ Conflict pending — a rival faction is challenging control here.", "#FFB347")

    if recovering:
        return ("Recovering from a recent crisis — stay supportive to fully stabilize.", "#4D96FF")

    if is_controlling:
        return ("Stable control — no immediate action needed.", "#4D96FF")
    return ("Present, not controlling — monitor influence trend.", "#888888")


class _EdsmFactionLookupWorker(QObject):
    finished = pyqtSignal(object, object, str)  # (result dict or None, error code or None, queried system name)

    def __init__(self, system_name: str):
        super().__init__()
        self._system_name = system_name

    def run(self):
        result, error = fetch_system_factions(self._system_name)
        self.finished.emit(result, error, self._system_name)


class PlayerFactionPanel(QWidget):
    """
    Owns all widgets and refresh logic for the Player Faction tab.
    Receives the repository directly (like MarketPanel) since this is a
    cross-system query, not something derivable from live GameState alone.
    """

    def __init__(self, repo, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._faction_name: Optional[str] = None
        self._last_state = None
        self._lookup_thread: Optional[QThread] = None
        self._lookup_worker: Optional[_EdsmFactionLookupWorker] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 8)
        root.setSpacing(6)

        frame = QFrame()
        frame.setStyleSheet(_CARD_STYLE)
        frame_l = QVBoxLayout(frame)
        frame_l.setContentsMargins(8, 6, 8, 8)
        frame_l.setSpacing(4)

        hdr = QLabel("PLAYER FACTION — SQUADRON-ALIGNED MINOR FACTION")
        hdr.setStyleSheet(_HDR_STYLE)
        frame_l.addWidget(hdr)

        self._summary_label = QLabel("")
        self._summary_label.setWordWrap(True)
        self._summary_label.setStyleSheet("background:transparent; border:none; color:#c8c8c8;")
        frame_l.addWidget(self._summary_label)

        root.addWidget(frame)

        # ── Manually add a system (e.g. from Inara's faction page) ────────
        add_row = QHBoxLayout()
        add_row.setSpacing(6)
        self._add_system_edit = QLineEdit()
        self._add_system_edit.setPlaceholderText("System name (looked up live via EDSM)")
        self._add_system_edit.setStyleSheet("background:#0a1520; color:#c8c8c8; border:1px solid #1e3a5a;")
        self._add_system_edit.returnPressed.connect(self._on_add_system_clicked)
        self._add_system_btn = QPushButton("Add System")
        self._add_system_btn.setStyleSheet(
            "QPushButton { background:#1a3a5a; color:#FFB347; border:1px solid #2a5a8a;"
            " border-radius:3px; padding:3px 12px; font-weight:bold; }"
            "QPushButton:hover { background:#2a5a8a; }"
            "QPushButton:disabled { background:#111; color:#555; border-color:#333; }"
        )
        self._add_system_btn.clicked.connect(self._on_add_system_clicked)
        add_row.addWidget(self._add_system_edit, 1)
        add_row.addWidget(self._add_system_btn)
        root.addLayout(add_row)

        self._add_system_status = QLabel("")
        self._add_system_status.setWordWrap(True)
        self._add_system_status.setStyleSheet("background:transparent; border:none; color:#888888; font-size:10px;")
        root.addWidget(self._add_system_status)

        self._table = QTableWidget()
        self._table.setColumnCount(8)
        self._table.setHorizontalHeaderLabels(
            ["System", "Influence", "Controlling", "Active", "Pending", "Reputation", "Action", ""]
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
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSortingEnabled(True)
        self._table.cellClicked.connect(self._on_table_cell_clicked)
        root.addWidget(self._table, 1)

        # ── Active missions for this faction (what to complete) ───────────
        missions_hdr = QLabel("ACTIVE MISSIONS — HELP THIS FACTION")
        missions_hdr.setStyleSheet(_HDR_STYLE)
        root.addWidget(missions_hdr)

        self._missions_status_label = QLabel("")
        self._missions_status_label.setWordWrap(True)
        self._missions_status_label.setStyleSheet("background:transparent; border:none; color:#888888; font-size:10px;")
        root.addWidget(self._missions_status_label)

        self._missions_table = QTableWidget()
        self._missions_table.setColumnCount(4)
        self._missions_table.setHorizontalHeaderLabels(
            ["Mission", "Influence", "Destination", "Expiry"]
        )
        self._missions_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._missions_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._missions_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._missions_table.verticalHeader().setVisible(False)
        self._missions_table.setAlternatingRowColors(True)
        self._missions_table.setStyleSheet(
            "QTableWidget { background:#080f18; alternate-background-color:#0a1520;"
            " color:#c8c8c8; gridline-color:#1e3a5a; border:1px solid #1e3a5a; }"
            "QHeaderView::section { background:#0d1a2a; color:#888888; border:none;"
            " padding:3px; font-size:10px; font-weight:bold; letter-spacing:1px; }"
            "QTableWidget::item:selected { background:#1a3a5a; color:#FFB347; }"
        )
        mh = self._missions_table.horizontalHeader()
        mh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        mh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        mh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        mh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self._missions_table, 1)

    def refresh(self, state=None) -> None:
        self._last_state = state
        try:
            overview = self._repo.get_player_faction_overview()
        except Exception:
            log.exception("Failed to load player faction overview")
            overview = None

        if not overview:
            self._faction_name = None
            self._summary_label.setText(
                "You're not currently aligned with a squadron-supported minor faction — "
                "this tab activates automatically once your squadron adopts one."
            )
            self._table.setRowCount(0)
            self._missions_status_label.setText("")
            self._missions_table.setRowCount(0)
            return

        self._faction_name = overview["faction_name"]
        systems = overview.get("systems") or []
        controlling_count = sum(1 for s in systems if s.get("is_controlling"))
        self._summary_label.setText(
            f"Faction: {overview['faction_name']} — present in {len(systems)} system"
            f"{'s' if len(systems) != 1 else ''}, controlling {controlling_count}."
        )

        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(systems))
        for row, s in enumerate(systems):
            name_item = QTableWidgetItem(s.get("system_name") or f"Unknown ({s.get('system_address')})")
            infl = s.get("influence")
            infl_value = float(infl) if isinstance(infl, (int, float)) else -1.0
            infl_item = _NumericTableWidgetItem(
                f"{infl_value * 100:.1f}%" if isinstance(infl, (int, float)) else "?", infl_value,
            )
            ctrl_item = QTableWidgetItem("★ Yes" if s.get("is_controlling") else "No")

            active_names = [s.get("faction_state")] if s.get("faction_state") and s.get("faction_state") != "None" else []
            active_names += [st for st in _parse_states(s.get("active_states")) if st not in active_names]
            active_item = QTableWidgetItem(", ".join(active_names) if active_names else "—")

            pending_names = _parse_states(s.get("pending_states"))
            pending_item = QTableWidgetItem(", ".join(pending_names) if pending_names else "—")

            rep = s.get("my_reputation")
            rep_value = float(rep) if isinstance(rep, (int, float)) else -999.0
            rep_item = _NumericTableWidgetItem(f"{rep_value:.1f}" if isinstance(rep, (int, float)) else "—", rep_value)

            action_text, color = derive_bgs_action(s)
            action_item = QTableWidgetItem(action_text)
            action_item.setForeground(QColor(color))

            for it in (infl_item, ctrl_item, active_item, pending_item, rep_item):
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if s.get("is_controlling"):
                ctrl_item.setForeground(QColor("#6BCB77"))
            if pending_names:
                pending_item.setForeground(QColor("#FFD93D"))

            self._table.setItem(row, 0, name_item)
            self._table.setItem(row, 1, infl_item)
            self._table.setItem(row, 2, ctrl_item)
            self._table.setItem(row, 3, active_item)
            self._table.setItem(row, 4, pending_item)
            self._table.setItem(row, 5, rep_item)
            self._table.setItem(row, 6, action_item)

            # A setCellWidget() button would not follow its row when the
            # table is sorted (a real QTableWidgetItem does) — a plain
            # clickable-styled item + cellClicked handler instead.
            system_address = s.get("system_address")
            remove_item = QTableWidgetItem("✕ Remove")
            remove_item.setForeground(QColor("#d06060"))
            remove_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            remove_item.setToolTip("Hide this system — use if the squadron no longer has presence here.")
            remove_item.setData(Qt.ItemDataRole.UserRole, system_address)
            self._table.setItem(row, 7, remove_item)

        self._table.setSortingEnabled(True)
        self._refresh_active_missions(self._faction_name, state)

    def _refresh_active_missions(self, faction_name: str, state) -> None:
        active_missions = getattr(state, "active_missions", None) or {} if state else {}
        relevant = [m for m in active_missions.values() if m.get("faction") == faction_name]

        if not relevant:
            self._missions_status_label.setText(
                f"No active missions currently helping {faction_name} — "
                "accept some at a station it controls."
            )
            self._missions_table.setRowCount(0)
            return

        self._missions_status_label.setText(
            f"{len(relevant)} active mission{'s' if len(relevant) != 1 else ''} helping {faction_name}."
        )
        self._missions_table.setRowCount(len(relevant))
        for row, m in enumerate(relevant):
            name_item = QTableWidgetItem(m.get("localised_name") or m.get("name") or "—")
            infl_item = QTableWidgetItem(m.get("influence") or "—")
            dest = m.get("destination_system") or "—"
            if m.get("destination_station"):
                dest = f"{dest} ({m['destination_station']})"
            dest_item = QTableWidgetItem(dest)
            expiry_item = QTableWidgetItem(m.get("expiry") or "—")
            infl_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            expiry_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            self._missions_table.setItem(row, 0, name_item)
            self._missions_table.setItem(row, 1, infl_item)
            self._missions_table.setItem(row, 2, dest_item)
            self._missions_table.setItem(row, 3, expiry_item)

    # ── Manual add / remove ─────────────────────────────────────────────

    def _on_add_system_clicked(self):
        system_name = self._add_system_edit.text().strip()
        if not system_name:
            self._add_system_status.setText("Enter a system name first.")
            return
        if not self._faction_name:
            self._add_system_status.setText(
                "No squadron-aligned faction known yet — this activates once one is detected."
            )
            return
        if self._lookup_thread and self._lookup_thread.isRunning():
            return

        self._add_system_btn.setEnabled(False)
        self._add_system_status.setText(f"Looking up {system_name} on EDSM…")

        self._lookup_worker = _EdsmFactionLookupWorker(system_name)
        self._lookup_thread = QThread()
        self._lookup_worker.moveToThread(self._lookup_thread)
        self._lookup_thread.started.connect(self._lookup_worker.run)
        self._lookup_worker.finished.connect(self._on_lookup_finished)
        self._lookup_worker.finished.connect(self._lookup_thread.quit)
        self._lookup_thread.start()

    def _on_lookup_finished(self, result: Optional[Dict[str, Any]], error: Optional[str], queried_name: str):
        self._add_system_btn.setEnabled(True)

        if not result:
            if error == ERROR_BLOCKED:
                self._add_system_status.setText(
                    f"EDSM lookup for {queried_name!r} failed (network error or blocked) — try again shortly."
                )
            elif error == ERROR_NOT_FOUND:
                self._add_system_status.setText(
                    f"{queried_name!r} isn't in EDSM's database — check the spelling, "
                    "or it may be a system nobody has reported there yet."
                )
            else:
                self._add_system_status.setText(f"Lookup for {queried_name!r} failed.")
            return

        factions = result.get("factions") or []
        match = next((f for f in factions if f.get("Name") == self._faction_name), None)
        if not match:
            self._add_system_status.setText(
                f"{result['system_name']} found, but {self._faction_name} isn't present there."
            )
            return

        try:
            self._repo.save_system_name_if_missing(result["system_address"], result["system_name"])
            is_controlling = bool(match.pop("is_controlling", False))
            self._repo.save_faction_snapshot(
                result["system_address"], match, date.today().isoformat(), is_controlling,
            )
            # A deliberate manual add should override an earlier "Remove" —
            # otherwise re-adding a previously-dismissed system would save
            # successfully but silently stay hidden, which is confusing.
            self._repo.undismiss_faction_system(self._faction_name, result["system_address"])
        except Exception:
            log.exception("Failed to save EDSM-sourced faction snapshot")
            self._add_system_status.setText("Found it, but saving failed — see log.")
            return

        self._add_system_status.setText(f"Added {result['system_name']}.")
        self._add_system_edit.clear()
        self.refresh(self._last_state)

    def _on_table_cell_clicked(self, row: int, column: int):
        if column != 7:
            return
        item = self._table.item(row, 7)
        if item is None:
            return
        system_address = item.data(Qt.ItemDataRole.UserRole)
        self._on_remove_system_clicked(system_address)

    def _on_remove_system_clicked(self, system_address):
        if not self._faction_name or not isinstance(system_address, int):
            return
        try:
            self._repo.dismiss_faction_system(self._faction_name, system_address)
        except Exception:
            log.exception("Failed to dismiss faction system")
            return
        self.refresh(self._last_state)
