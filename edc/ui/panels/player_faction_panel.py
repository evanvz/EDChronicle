"""Player Faction panel — tracks your squadron-aligned minor faction across
every system it has a presence in, with a recommended action per system.

Only ever shows data if the game has reported SquadronFaction:true for some
faction at some point — most commanders aren't in a squadron aligned to a
minor faction, and that's a legitimate, permanent empty state, not a bug.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt, QObject, QThread, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame, QFileDialog,
)

from edc.core.edsm_faction_lookup import fetch_system_factions, ERROR_BLOCKED, ERROR_NOT_FOUND
from edc.core.inara_faction_csv import parse_inara_faction_csv

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


class _CsvImportWorker(QObject):
    """
    Resolves each CSV row against EDSM one at a time (reusing the exact
    same single-system lookup already proven working live), rather than an
    unverified bulk endpoint — slower, but every row goes through code
    that's already been tested against the real API. Paced with a small
    delay per request to avoid hammering EDSM across hundreds of systems.
    """
    progress = pyqtSignal(int, int, str)  # current, total, system_name
    # imported, fallback_used, not_found (genuine — not on EDSM at all),
    # cancelled_at (0 if not cancelled), blocked_rows (list of CSV row
    # dicts that failed due to a blocked/network error, not a genuine
    # not-found — worth retrying, unlike a real gap in EDSM's data)
    finished = pyqtSignal(int, int, int, int, list)

    def __init__(self, db_path, rows: List[Dict[str, Any]], faction_name: str):
        super().__init__()
        self._db_path = db_path
        self._rows = rows
        self._faction_name = faction_name
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        from persistence.database import Database
        from persistence.repository import Repository

        db = Database(self._db_path)
        repo = Repository(db)
        imported = 0
        fallback_used = 0
        not_found = 0
        cancelled_at = 0
        blocked_rows: List[Dict[str, Any]] = []
        total = len(self._rows)

        try:
            for i, row in enumerate(self._rows, start=1):
                if self._cancel:
                    cancelled_at = i - 1  # i-1 rows were fully processed before this check
                    break

                system_name = row["system_name"]
                self.progress.emit(i, total, system_name)

                result, error = fetch_system_factions(system_name)
                if result:
                    match = next((f for f in result["factions"] if f.get("Name") == self._faction_name), None)
                    if match:
                        is_controlling = bool(match.pop("is_controlling", False))
                        faction_rec = match
                        snapshot_date = date.today().isoformat()
                        imported += 1
                    else:
                        # EDSM found the system but doesn't list our faction
                        # there (possibly stale on one side) — fall back to
                        # the CSV's own influence/government/allegiance so
                        # the row isn't dropped entirely.
                        faction_rec = {
                            "Name": self._faction_name,
                            "Influence": row.get("influence"),
                            "Government": row.get("government"),
                            "Allegiance": row.get("allegiance"),
                        }
                        is_controlling = False
                        snapshot_date = row.get("updated_date") or date.today().isoformat()
                        fallback_used += 1

                    repo.save_system_name_if_missing(result["system_address"], result["system_name"])
                    repo.save_faction_snapshot(result["system_address"], faction_rec, snapshot_date, is_controlling)
                    repo.undismiss_faction_system(self._faction_name, result["system_address"])
                elif error == ERROR_BLOCKED:
                    # Confirmed via live testing: most "failures" at this
                    # scale are Cloudflare blocking a request, not the
                    # system genuinely missing from EDSM — worth a retry.
                    blocked_rows.append(row)
                else:
                    not_found += 1

                time.sleep(0.3)
        finally:
            db.close()

        self.finished.emit(imported, fallback_used, not_found, cancelled_at, blocked_rows)


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
        self._csv_thread: Optional[QThread] = None
        self._csv_worker: Optional[_CsvImportWorker] = None
        self._last_csv_names: set = set()

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
        csv_note = QLabel(
            "To bulk-import: on Inara, open your minor faction's page and export its full "
            "system presence list as a .csv, then use \"Import Inara CSV…\" below."
        )
        csv_note.setWordWrap(True)
        csv_note.setStyleSheet(
            "color:#FFD93D; font-size:11px; font-weight:bold; background:transparent; border:none;"
        )
        root.addWidget(csv_note)

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

        self._import_csv_btn = QPushButton("Import Inara CSV…")
        self._import_csv_btn.setStyleSheet(
            "QPushButton { background:#1a3a5a; color:#FFB347; border:1px solid #2a5a8a;"
            " border-radius:3px; padding:3px 12px; font-weight:bold; }"
            "QPushButton:hover { background:#2a5a8a; }"
            "QPushButton:disabled { background:#111; color:#555; border-color:#333; }"
        )
        self._import_csv_btn.setToolTip(
            "Bulk-import systems from Inara's faction-presence CSV export "
            "(faction page → export). Resolves each system live via EDSM, "
            "one at a time — can take a while for large factions."
        )
        self._import_csv_btn.clicked.connect(self._on_import_csv_clicked)
        add_row.addWidget(self._import_csv_btn)

        self._cancel_import_btn = QPushButton("Cancel")
        self._cancel_import_btn.setStyleSheet(
            "QPushButton { background:#2a0d0d; color:#d06060; border:1px solid #4a1e1e;"
            " border-radius:3px; padding:3px 12px; font-weight:bold; }"
            "QPushButton:hover { background:#4a1e1e; }"
        )
        self._cancel_import_btn.clicked.connect(self._on_cancel_import_clicked)
        self._cancel_import_btn.setVisible(False)
        add_row.addWidget(self._cancel_import_btn)

        self._retry_failed_btn = QPushButton("Retry Failed")
        self._retry_failed_btn.setStyleSheet(
            "QPushButton { background:#201a0d; color:#d0a060; border:1px solid #4a3a1e;"
            " border-radius:3px; padding:3px 12px; font-weight:bold; }"
            "QPushButton:hover { background:#4a3a1e; }"
            "QPushButton:disabled { background:#111; color:#555; border-color:#333; }"
        )
        self._retry_failed_btn.setToolTip(
            "Re-run the lookup for systems that failed last time due to a blocked/network "
            "error (not systems genuinely missing from EDSM) — each attempt has an "
            "independent chance of getting through."
        )
        self._retry_failed_btn.clicked.connect(self._on_retry_failed_clicked)
        self._retry_failed_btn.setVisible(False)
        add_row.addWidget(self._retry_failed_btn)
        self._last_blocked_rows: List[Dict[str, Any]] = []
        self._last_skip_count: int = 0
        # Rebuilding the systems table (QTableWidgetItem creation + BGS
        # action derivation per row) is cheap at a handful of rows but not
        # at hundreds, and refresh() is called on nearly every single
        # journal event via _refresh_hud(). A plain equality check against
        # the last overview isn't enough on its own: with EDDN traffic
        # constantly touching influence/state across a large faction
        # footprint, the DB query result is genuinely different almost
        # every call, so the "skip if unchanged" path rarely fires. The
        # real fix is to not rebuild an offscreen tab at all, and to cap
        # how often the visible tab rebuilds even while data keeps
        # changing underneath it — confirmed via live profiling this was
        # what stalled the main thread. The mission list below still
        # updates every time regardless, since it's driven by live state
        # rather than this DB query.
        self._last_overview: Optional[Dict[str, Any]] = None
        self._last_rebuild_at: float = 0.0
        self._force_rebuild_next: bool = True
        self._REBUILD_MIN_INTERVAL_S = 15.0
        self._row_by_system_address: Dict[int, int] = {}

        root.addLayout(add_row)

        self._add_system_status = QLabel("")
        self._add_system_status.setWordWrap(True)
        self._add_system_status.setStyleSheet("background:transparent; border:none; color:#888888; font-size:10px;")
        root.addWidget(self._add_system_status)

        # ── Stale-system review (shown after a completed CSV import) ──────
        self._stale_frame = QFrame()
        self._stale_frame.setStyleSheet(
            "QFrame { background:#201a0d; border:1px solid #4a3a1e; border-radius:5px; }"
        )
        stale_l = QVBoxLayout(self._stale_frame)
        stale_l.setContentsMargins(8, 6, 8, 6)
        stale_l.setSpacing(4)

        stale_hdr = QLabel("NOT IN LATEST IMPORT — MAY NO LONGER BE PRESENT")
        stale_hdr.setStyleSheet(
            "color:#d0a060; font-size:10px; font-weight:bold; letter-spacing:1px; background:transparent; border:none;"
        )
        stale_l.addWidget(stale_hdr)

        self._stale_list_label = QLabel("")
        self._stale_list_label.setWordWrap(True)
        self._stale_list_label.setStyleSheet("background:transparent; border:none; color:#c8c8c8; font-size:11px;")
        stale_l.addWidget(self._stale_list_label)

        self._dismiss_stale_btn = QPushButton("Dismiss All Listed")
        self._dismiss_stale_btn.setStyleSheet(
            "QPushButton { background:#2a0d0d; color:#d06060; border:1px solid #4a1e1e;"
            " border-radius:3px; padding:3px 12px; font-weight:bold; }"
            "QPushButton:hover { background:#4a1e1e; }"
        )
        self._dismiss_stale_btn.clicked.connect(self._on_dismiss_stale_clicked)
        stale_l.addWidget(self._dismiss_stale_btn)

        root.addWidget(self._stale_frame)
        self._stale_frame.setVisible(False)
        self._stale_system_addresses: List[int] = []

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
        # ResizeToContents forces Qt to re-measure every row in that column
        # on every single setItem() call (dataChanged -> sizeHintForColumn()
        # scans the whole column) — fine at a handful of rows, but O(rows)
        # per insert makes populating this table O(rows^2) at the ~hundreds
        # of systems this tab tracks (confirmed via live profiling: this is
        # what actually made the bulk rebuild pathologically slow, distinct
        # from how often the rebuild ran). Fixed/Interactive widths avoid
        # the per-insert remeasurement entirely.
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        h.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        h.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        h.setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)
        h.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(7, QHeaderView.ResizeMode.Interactive)
        self._table.setColumnWidth(1, 70)
        self._table.setColumnWidth(2, 90)
        self._table.setColumnWidth(3, 160)
        self._table.setColumnWidth(4, 140)
        self._table.setColumnWidth(5, 80)
        self._table.setColumnWidth(7, 90)
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

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._force_rebuild_next = True
        # refresh() is no longer called on every journal event — it's now
        # driven by system arrival + a coarse timer — so switching to this
        # tab needs to trigger its own refresh to show current data.
        self.refresh(self._last_state)

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

        if not self.isVisible():
            # Tab isn't the one currently on screen — no point paying for
            # hundreds of QTableWidgetItem rebuilds the user can't see.
            # Cache the latest data so the next actual rebuild (on show,
            # or once due) reflects it.
            self._last_overview = overview
            self._refresh_active_missions(self._faction_name, state)
            return

        now = time.monotonic()
        data_changed = overview != self._last_overview
        rebuild_due = (now - self._last_rebuild_at) >= self._REBUILD_MIN_INTERVAL_S
        if not self._force_rebuild_next and not (data_changed and rebuild_due):
            self._refresh_active_missions(self._faction_name, state)
            return
        self._force_rebuild_next = False
        self._last_overview = overview
        self._last_rebuild_at = now

        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(systems))
        self._row_by_system_address = {}
        for row, s in enumerate(systems):
            for col, item in enumerate(self._build_row_items(s)):
                self._table.setItem(row, col, item)
            system_address = s.get("system_address")
            if isinstance(system_address, int):
                self._row_by_system_address[system_address] = row

        self._table.setSortingEnabled(True)
        self._refresh_active_missions(self._faction_name, state)

    def _build_row_items(self, s: dict) -> List[QTableWidgetItem]:
        """Builds the 8 QTableWidgetItems for one systems-table row from a
        faction-status dict. Shared by the full rebuild in refresh() and by
        refresh_single_system()'s targeted single-row update."""
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

        active_lower = {n.lower() for n in active_names}
        is_war = bool(active_lower & {"war", "civilwar"})
        is_election = "election" in active_lower

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

        row_items = [name_item, infl_item, ctrl_item, active_item, pending_item, rep_item, action_item]
        # War/Civil War/Election are the states that most urgently need
        # squadron attention — highlight the whole row, not just a cell,
        # so it's obvious scanning down the System column alone.
        if is_war:
            for it in row_items:
                it.setBackground(QColor(90, 30, 30))
            active_item.setForeground(QColor("#FF6B6B"))
        elif is_election:
            for it in row_items:
                it.setBackground(QColor(80, 65, 10))
            active_item.setForeground(QColor("#FFD93D"))

        # A setCellWidget() button would not follow its row when the table
        # is sorted (a real QTableWidgetItem does) — a plain clickable-styled
        # item + cellClicked handler instead.
        remove_item = QTableWidgetItem("✕ Remove")
        remove_item.setForeground(QColor("#d06060"))
        remove_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        remove_item.setToolTip("Hide this system — use if the squadron no longer has presence here.")
        remove_item.setData(Qt.ItemDataRole.UserRole, s.get("system_address"))

        return row_items + [remove_item]

    def refresh_single_system(self, system_address: int) -> None:
        """
        Called on arrival in a system — checks/updates just that one row
        instead of the full ~hundreds-of-systems bulk refresh. BGS state
        only ticks daily server-side, so there's no need to re-check every
        tracked system just because the player jumped somewhere.
        """
        if not self._faction_name or not isinstance(system_address, int):
            return
        try:
            status = self._repo.get_player_faction_system_status(self._faction_name, system_address)
        except Exception:
            log.exception("Failed to load single-system faction status for %s", system_address)
            return
        if not status:
            return  # not a tracked system — nothing to update

        row = self._row_by_system_address.get(system_address)
        if row is None or row >= self._table.rowCount():
            return  # table not built yet / row map stale — next bulk refresh will pick it up

        for col, item in enumerate(self._build_row_items(status)):
            self._table.setItem(row, col, item)

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
        if (self._lookup_thread and self._lookup_thread.isRunning()) or \
           (self._csv_thread and self._csv_thread.isRunning()):
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

    # ── Bulk CSV import ──────────────────────────────────────────────────

    def _on_import_csv_clicked(self):
        if not self._faction_name:
            self._add_system_status.setText(
                "No squadron-aligned faction known yet — this activates once one is detected."
            )
            return
        if (self._lookup_thread and self._lookup_thread.isRunning()) or \
           (self._csv_thread and self._csv_thread.isRunning()):
            return

        path, _filter = QFileDialog.getOpenFileName(
            self, "Import Inara faction-presence CSV", "", "CSV files (*.csv);;All files (*)",
        )
        if not path:
            return

        try:
            rows = parse_inara_faction_csv(Path(path))
        except Exception:
            log.exception("Failed to parse Inara CSV")
            self._add_system_status.setText("Couldn't read that CSV — see log.")
            return

        if not rows:
            self._add_system_status.setText("No systems found in that CSV.")
            return

        # Kept from the FULL row set (not the filtered one below) — stale-
        # system reconciliation needs to know everything this CSV actually
        # lists, not just what we ended up re-querying.
        self._last_csv_names = {r["system_name"] for r in rows}

        try:
            known = self._repo.get_known_system_names(self._faction_name)
        except Exception:
            log.exception("Failed to load known system names")
            known = set()
        new_rows = [r for r in rows if r["system_name"].strip().lower() not in known]
        skipped = len(rows) - len(new_rows)

        if not new_rows:
            self._add_system_status.setText(
                f"All {len(rows)} systems in that CSV are already known — nothing to import."
            )
            return

        self._last_skip_count = skipped
        self._start_csv_import(new_rows, skipped=skipped)

    def _on_retry_failed_clicked(self):
        if (self._lookup_thread and self._lookup_thread.isRunning()) or \
           (self._csv_thread and self._csv_thread.isRunning()):
            return
        rows = self._last_blocked_rows
        if not rows:
            return
        # Retrying is scoped to just these rows — doesn't change what
        # counts as "in the latest import" for stale-system reconciliation,
        # so _last_csv_names is deliberately left as-is from the original run.
        self._last_skip_count = 0
        self._start_csv_import(rows)

    def _start_csv_import(self, rows: List[Dict[str, Any]], skipped: int = 0):
        self._add_system_btn.setEnabled(False)
        self._import_csv_btn.setEnabled(False)
        self._retry_failed_btn.setVisible(False)
        self._cancel_import_btn.setVisible(True)
        prefix = (
            f"Skipping {skipped} already-known system{'s' if skipped != 1 else ''}. " if skipped else ""
        )
        self._add_system_status.setText(f"{prefix}Importing 0 / {len(rows)}…")
        self._stale_frame.setVisible(False)

        self._csv_worker = _CsvImportWorker(self._repo.db.db_path, rows, self._faction_name)
        self._csv_thread = QThread()
        self._csv_worker.moveToThread(self._csv_thread)
        self._csv_thread.started.connect(self._csv_worker.run)
        self._csv_worker.progress.connect(self._on_csv_import_progress)
        self._csv_worker.finished.connect(self._on_csv_import_finished)
        self._csv_worker.finished.connect(self._csv_thread.quit)
        self._csv_thread.start()

    def _on_cancel_import_clicked(self):
        if self._csv_worker:
            self._csv_worker.cancel()
        self._cancel_import_btn.setEnabled(False)

    def _on_csv_import_progress(self, current: int, total: int, system_name: str):
        self._add_system_status.setText(f"Importing {current} / {total}: {system_name}")

    def _on_csv_import_finished(
        self, imported: int, fallback_used: int, not_found: int, cancelled_at: int,
        blocked_rows: List[Dict[str, Any]],
    ):
        self._add_system_btn.setEnabled(True)
        self._import_csv_btn.setEnabled(True)
        self._cancel_import_btn.setVisible(False)
        self._cancel_import_btn.setEnabled(True)

        self._last_blocked_rows = blocked_rows

        parts = []
        if self._last_skip_count:
            parts.append(f"{self._last_skip_count} already-known systems skipped")
        parts.append(f"{imported} imported with full data")
        if fallback_used:
            parts.append(f"{fallback_used} imported from CSV only (not on EDSM's faction list there)")
        if not_found:
            parts.append(f"{not_found} genuinely not found on EDSM")
        if blocked_rows:
            parts.append(f"{len(blocked_rows)} failed due to a blocked/network error — worth retrying")
        summary = ", ".join(parts) + "."
        if cancelled_at:
            summary = f"Cancelled after {cancelled_at} systems. " + summary
        self._add_system_status.setText(summary)
        self._retry_failed_btn.setText(f"Retry Failed ({len(blocked_rows)})")
        self._retry_failed_btn.setVisible(bool(blocked_rows))
        self.refresh(self._last_state)

        # Reconciliation only makes sense against a complete run — a
        # cancelled import only covered part of the CSV, so comparing
        # against it would wrongly flag not-yet-reached systems as stale.
        if not cancelled_at and self._faction_name:
            try:
                stale = self._repo.get_stale_faction_systems(self._faction_name, self._last_csv_names)
            except Exception:
                log.exception("Failed to compute stale faction systems")
                stale = []
            if stale:
                self._stale_system_addresses = [s["system_address"] for s in stale]
                names = ", ".join(s.get("system_name") or f"Unknown ({s['system_address']})" for s in stale)
                verb = "weren't" if len(stale) != 1 else "wasn't"
                self._stale_list_label.setText(
                    f"{len(stale)} system{'s' if len(stale) != 1 else ''} we're tracking {verb} in "
                    f"this import: {names}"
                )
                self._stale_frame.setVisible(True)
            else:
                self._stale_frame.setVisible(False)

    def _on_dismiss_stale_clicked(self):
        if not self._faction_name:
            return
        try:
            for addr in self._stale_system_addresses:
                self._repo.dismiss_faction_system(self._faction_name, addr)
        except Exception:
            log.exception("Failed to dismiss stale faction systems")
            return
        self._stale_system_addresses = []
        self._stale_frame.setVisible(False)
        self.refresh(self._last_state)

    def _on_remove_system_clicked(self, system_address):
        if not self._faction_name or not isinstance(system_address, int):
            return
        try:
            self._repo.dismiss_faction_system(self._faction_name, system_address)
        except Exception:
            log.exception("Failed to dismiss faction system")
            return
        self.refresh(self._last_state)
