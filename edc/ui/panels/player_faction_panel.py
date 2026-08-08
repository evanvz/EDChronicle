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
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PyQt6.QtCore import Qt, QObject, QThread, QStringListModel, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame, QFileDialog, QDialog,
    QApplication, QCompleter, QSizePolicy,
)

from edc.core.edsm_faction_lookup import (
    fetch_system_factions, fetch_system_coords, fetch_system_stations, ERROR_BLOCKED, ERROR_NOT_FOUND,
)
from edc.core.inara_faction_csv import parse_inara_faction_csv

log = logging.getLogger(__name__)


def _in_weekly_maintenance_window() -> bool:
    """Frontier's weekly Elite Dangerous server maintenance — Thursdays,
    roughly 09:00-11:00 in the user's local time (typically 1-2h, occasionally
    longer on issues). Used to skip the automatic daily full-refresh only —
    manual refresh/recheck clicks are never blocked."""
    now = datetime.now()
    return now.weekday() == 3 and 9 <= now.hour < 11

_CARD_STYLE = "QFrame { background:#0d1a2a; border:1px solid #1e3a5a; border-radius:5px; }"
_HDR_STYLE = "color:#555555; font-size:12px; font-weight:bold; letter-spacing:1px; background:transparent; border:none;"
# Distinct green accent, set apart from the standard blue _CARD_STYLE cards above/below it.
_CARD_STYLE_ACCENT = "QFrame { background:#0d1a12; border:1px solid #2a5a3a; border-radius:5px; }"
_HDR_STYLE_ACCENT = "color:#6BCB77; font-size:12px; font-weight:bold; letter-spacing:1px; background:transparent; border:none;"


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
    if "pirateattack" in active:
        return ("🏴‍☠️ Pirate Attack — expect frequent interdictions; bounty hunting here pays extra and helps resolve it.", "#FF6B6B")
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


def _format_forecast(prediction: Optional[Dict[str, Any]]) -> Tuple[str, str]:
    """Returns (text, color_hex) for the Forecast column, from a
    Repository.get_faction_predictions() entry. Priority: conflict risk
    (a rival converging on your influence) > expansion/retreat risk (both
    are "impending event" signals from the real BGS thresholds) > plain
    trend > "not enough history yet"."""
    if not prediction:
        return ("—", "#555555")

    conflict = prediction.get("conflict_risk")
    if conflict:
        diff_pct = conflict.get("diff", 0.0) * 100
        return (
            f"⚔ Conflict risk vs {conflict.get('faction_name', '?')} (Δ{diff_pct:.1f}%)",
            "#FFB347",
        )

    days_exp = prediction.get("days_in_expansion_range")
    if days_exp is not None:
        return (f"🚀 Expansion likely (≥75% for {days_exp}d)", "#6BCB77")

    days_ret = prediction.get("days_in_retreat_range")
    if days_ret is not None:
        return (f"⬇ Retreat risk ({days_ret}/~5d in window)", "#FF6B6B")

    trend = prediction.get("trend")
    if trend == "up":
        return ("↑ Rising", "#6BCB77")
    if trend == "down":
        return ("↓ Falling", "#FF8C00")
    if trend == "flat":
        return ("→ Stable", "#4D96FF")
    return ("Not enough history yet", "#555555")


# (bucket key, tile label, tile bg color) — order is display order. A system
# can land in several buckets at once (e.g. War + Stale Data); "No Action"
# only gets a system that matched none of the others.
_BUCKET_DEFS: List[Tuple[str, str, str]] = [
    ("war", "War / Civil War", "#5F2323"),
    ("election", "Election", "#5a4a10"),
    ("civilunrest", "Civil Unrest", "#5a3a10"),
    ("pirateattack", "Pirate Attack", "#5a3210"),
    ("boom", "Boom", "#1e4a1e"),
    ("bust", "Bust", "#3a3a3a"),
    ("outbreak", "Outbreak", "#5F2323"),
    ("famine", "Famine", "#5a3a10"),
    ("drought", "Drought", "#5a3a10"),
    ("blight", "Blight", "#5a3a10"),
    ("lockdown", "Lockdown", "#3a3a3a"),
    ("expansion_pending", "Expansion Pending", "#1e4a1e"),
    ("retreat_pending", "Retreat Pending", "#5F2323"),
    ("conflict_pending", "Conflict Pending", "#5a4a10"),
    ("expansion_likely", "Expansion Likely", "#1e4a1e"),
    ("retreat_risk", "Retreat Risk", "#5F2323"),
    ("conflict_risk", "Conflict Risk", "#5a4a10"),
    ("stale", "Stale Data (>7d)", "#3a3a3a"),
    ("no_data", "No Data / Lookup Failed", "#3a3a3a"),
    ("no_action", "No Action", "#1a3a5a"),
]


class _EdsmFactionLookupWorker(QObject):
    finished = pyqtSignal(object, object, str)  # (result dict or None, error code or None, queried system name)

    def __init__(self, system_name: str):
        super().__init__()
        self._system_name = system_name

    def run(self):
        result, error = fetch_system_factions(self._system_name)
        self.finished.emit(result, error, self._system_name)


class _EdsmStationLookupWorker(QObject):
    """
    EDSM's static station catalog knows about every station in a system
    regardless of recent Docked traffic — our own station_info table only
    knows about ones someone has actually docked at recently. Cross-refs
    each result's market_id against our local station_info for a pad size
    when we happen to have one (EDSM doesn't provide pad size at all).
    """
    finished = pyqtSignal(object, object, str)  # (stations list or None, error code or None, queried system name)

    def __init__(self, db_path, system_name: str):
        super().__init__()
        self._db_path = db_path
        self._system_name = system_name

    def run(self):
        stations, error = fetch_system_stations(self._system_name)
        if stations:
            from persistence.database import Database
            from persistence.repository import Repository

            db = Database(self._db_path)
            try:
                repo = Repository(db)
                market_ids = [s["market_id"] for s in stations if isinstance(s.get("market_id"), int)]
                pads_by_market_id = repo.get_pad_sizes_for_markets(market_ids)
                for s in stations:
                    s["pad_size"] = pads_by_market_id.get(s.get("market_id"), "?")
            finally:
                db.close()
        self.finished.emit(stations, error, self._system_name)


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


class _FactionRefreshWorker(QObject):
    """
    Re-queries EDSM for every currently tracked system, saving EVERY
    faction present there — not filtered down to the squadron-aligned one,
    unlike the CSV import worker above. This is what makes rival-faction
    influence available at all (needed for conflict-risk prediction) for
    systems only ever known via EDDN/CSV, never personally visited, and
    keeps every tracked system's data from going stale. Paced the same as
    CSV import to avoid Cloudflare blocking at this scale.
    """
    progress = pyqtSignal(int, int, str)  # current, total, system_name
    finished = pyqtSignal(int, int)  # systems_refreshed, systems_failed

    def __init__(self, db_path, system_names: List[str]):
        super().__init__()
        self._db_path = db_path
        self._system_names = system_names
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        from persistence.database import Database
        from persistence.repository import Repository

        db = Database(self._db_path)
        repo = Repository(db)
        refreshed = 0
        failed = 0
        total = len(self._system_names)

        try:
            # Distance sorting needs system_coords, which the faction
            # endpoint never provides — only fetch it (extra request) for
            # systems that don't already have it, e.g. from EDDN.
            has_coords = set(repo.get_system_coords_for_names(self._system_names).keys())

            for i, system_name in enumerate(self._system_names, start=1):
                if self._cancel:
                    break
                self.progress.emit(i, total, system_name)

                result, error = fetch_system_factions(system_name)
                if not result:
                    failed += 1
                    time.sleep(0.3)
                    continue

                snapshot_date = date.today().isoformat()
                for faction in result["factions"]:
                    is_controlling = bool(faction.pop("is_controlling", False))
                    repo.save_faction_snapshot(
                        result["system_address"], faction, snapshot_date, is_controlling
                    )

                if system_name not in has_coords:
                    coords = fetch_system_coords(system_name)
                    if coords:
                        now_iso = datetime.now(timezone.utc).isoformat()
                        repo.save_system_coords_batch([(system_name, *coords, now_iso)])

                refreshed += 1
                time.sleep(0.3)
        finally:
            db.close()

        self.finished.emit(refreshed, failed)


class PlayerFactionPanel(QWidget):
    """
    Owns all widgets and refresh logic for the Player Faction tab.
    Receives the repository directly (like MarketPanel) since this is a
    cross-system query, not something derivable from live GameState alone.
    """

    def __init__(self, repo, refresh_tracker=None, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._refresh_tracker = refresh_tracker
        self._faction_name: Optional[str] = None
        self._last_state = None
        self._lookup_thread: Optional[QThread] = None
        self._lookup_worker: Optional[_EdsmFactionLookupWorker] = None
        self._csv_thread: Optional[QThread] = None
        self._csv_worker: Optional[_CsvImportWorker] = None
        self._last_csv_names: set = set()
        self._refresh_all_thread: Optional[QThread] = None
        self._refresh_all_worker: Optional["_FactionRefreshWorker"] = None
        self._auto_refresh_checked: bool = False
        # Populated once per bulk rebuild (not on every single-system
        # arrival update — predictions only meaningfully change once a day,
        # matching the BGS tick, so recomputing them more often buys nothing
        # and would reintroduce the per-event overhead already fixed once
        # this session). Keyed by system_address.
        self._last_predictions: Dict[int, dict] = {}
        self._last_stations_system: Optional[str] = None
        self._station_thread: Optional[QThread] = None
        self._station_worker: Optional[_EdsmStationLookupWorker] = None
        self._station_lookup_system: Optional[str] = None

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

        self._bgs_contribution_label = QLabel("")
        self._bgs_contribution_label.setWordWrap(True)
        self._bgs_contribution_label.setStyleSheet("background:transparent; border:none; color:#9BE68C;")
        self._bgs_contribution_label.setVisible(False)
        frame_l.addWidget(self._bgs_contribution_label)

        root.addWidget(frame)

        # ── Faction-controlled stations/settlements — nearest first, for
        # finding somewhere to hand in missions or redeem bounties that
        # actually credits this faction. Green-accented card, set apart
        # from the standard blue cards around it. ─────────────────────
        stations_frame = QFrame()
        stations_frame.setStyleSheet(_CARD_STYLE_ACCENT)
        stations_l = QVBoxLayout(stations_frame)
        stations_l.setContentsMargins(8, 6, 8, 8)
        stations_l.setSpacing(4)

        stations_hdr = QLabel("FACTION-CONTROLLED STATIONS & SETTLEMENTS — CURRENT SYSTEM")
        stations_hdr.setStyleSheet(_HDR_STYLE_ACCENT)
        stations_l.addWidget(stations_hdr)

        self._stations_status_label = QLabel("")
        self._stations_status_label.setWordWrap(True)
        self._stations_status_label.setStyleSheet("background:transparent; border:none; color:#888888; font-size:12px;")
        stations_l.addWidget(self._stations_status_label)

        self._stations_table = QTableWidget()
        self._stations_table.setColumnCount(3)
        self._stations_table.setHorizontalHeaderLabels(["Station", "Type", "Pad"])
        self._stations_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._stations_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._stations_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._stations_table.verticalHeader().setVisible(False)
        self._stations_table.verticalHeader().setDefaultSectionSize(18)
        self._stations_table.setAlternatingRowColors(True)
        self._stations_table.setStyleSheet(
            "QTableWidget { background:#080f18; alternate-background-color:#0a1520;"
            " color:#c8c8c8; gridline-color:#1e3a5a; border:1px solid #1e3a5a; }"
            "QHeaderView::section { background:#0d1a2a; color:#888888; border:none;"
            " padding:3px; font-size:12px; font-weight:bold; letter-spacing:1px; }"
            "QTableWidget::item:selected { background:#1a3a5a; color:#FFB347; }"
        )
        sth = self._stations_table.horizontalHeader()
        sth.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        sth.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        sth.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._stations_table.verticalHeader().setDefaultSectionSize(20)
        self._stations_table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self._stations_table.setMaximumHeight(160)
        self._stations_table.setToolTip("Click the Station cell to copy its name to the clipboard.")
        self._stations_table.cellClicked.connect(self._on_stations_cell_clicked)
        stations_l.addWidget(self._stations_table)

        root.addWidget(stations_frame)

        # ── Full EDSM refresh (all known systems, all factions present —
        # not just squadron's, so rival-faction data becomes available for
        # conflict-risk prediction) — runs automatically about once a day,
        # or on demand via this button. ─────────────────────────────────
        refresh_row = QHBoxLayout()
        refresh_row.setSpacing(6)
        self._refresh_status_label = QLabel("")
        self._refresh_status_label.setStyleSheet(
            "background:transparent; border:none; color:#888888; font-size:11px;"
        )
        refresh_row.addWidget(self._refresh_status_label, 1)
        self._refresh_all_btn = QPushButton("Refresh All from EDSM")
        self._refresh_all_btn.setStyleSheet(
            "QPushButton { background:#1a3a5a; color:#FFB347; border:1px solid #2a5a8a;"
            " border-radius:3px; padding:3px 12px; font-weight:bold; }"
            "QPushButton:hover { background:#2a5a8a; }"
            "QPushButton:disabled { background:#111; color:#555; border-color:#333; }"
        )
        self._refresh_all_btn.setToolTip(
            "Re-queries EDSM for every currently tracked system, saving every faction "
            "present there (not just this one) — refreshes stale data and captures "
            "rival-faction influence for conflict-risk detection. Runs automatically "
            "about once a day; this forces it now."
        )
        self._refresh_all_btn.clicked.connect(self._on_refresh_all_clicked)
        refresh_row.addWidget(self._refresh_all_btn)
        self._cancel_refresh_btn = QPushButton("Cancel")
        self._cancel_refresh_btn.setStyleSheet(
            "QPushButton { background:#2a0d0d; color:#d06060; border:1px solid #4a1e1e;"
            " border-radius:3px; padding:3px 12px; font-weight:bold; }"
            "QPushButton:hover { background:#4a1e1e; }"
        )
        self._cancel_refresh_btn.clicked.connect(self._on_cancel_refresh_clicked)
        self._cancel_refresh_btn.setVisible(False)
        refresh_row.addWidget(self._cancel_refresh_btn)
        root.addLayout(refresh_row)

        self._data_freshness_label = QLabel("")
        self._data_freshness_label.setStyleSheet(
            "background:transparent; border:none; color:#888888; font-size:11px;"
        )
        root.addWidget(self._data_freshness_label)

        # ── Manually add a system (e.g. from Inara's faction page) ────────
        csv_note = QLabel(
            "To bulk-import: on Inara, open your minor faction's page and export its full "
            "system presence list as a .csv, then use \"Import Inara CSV…\" below."
        )
        csv_note.setWordWrap(True)
        csv_note.setStyleSheet(
            "color:#FFD93D; font-size:12px; font-weight:bold; background:transparent; border:none;"
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
            "QPushButton { background:#2a0a0a; color:#d06060; border:1px solid #4a1e1e;"
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

        root.addLayout(add_row)

        self._add_system_status = QLabel("")
        self._add_system_status.setWordWrap(True)
        self._add_system_status.setStyleSheet("background:transparent; border:none; color:#888888; font-size:12px;")
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
            "color:#d0a060; font-size:12px; font-weight:bold; letter-spacing:1px; background:transparent; border:none;"
        )
        stale_l.addWidget(stale_hdr)

        self._stale_list_label = QLabel("")
        self._stale_list_label.setWordWrap(True)
        self._stale_list_label.setStyleSheet("background:transparent; border:none; color:#c8c8c8; font-size:12px;")
        stale_l.addWidget(self._stale_list_label)

        self._dismiss_stale_btn = QPushButton("Dismiss All Listed")
        self._dismiss_stale_btn.setStyleSheet(
            "QPushButton { background:#2a0a0a; color:#d06060; border:1px solid #4a1e1e;"
            " border-radius:3px; padding:3px 12px; font-weight:bold; }"
            "QPushButton:hover { background:#4a1e1e; }"
        )
        self._dismiss_stale_btn.clicked.connect(self._on_dismiss_stale_clicked)
        stale_l.addWidget(self._dismiss_stale_btn)

        root.addWidget(self._stale_frame)
        self._stale_frame.setVisible(False)
        self._stale_system_addresses: List[int] = []

        # ── Bucket dashboard (replaces the old flat ~700-row table) ────────
        buckets_hdr = QLabel("SYSTEMS BY STATUS — CLICK A TILE FOR DETAILS")
        buckets_hdr.setStyleSheet(_HDR_STYLE)
        root.addWidget(buckets_hdr)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Search:"))
        self._system_search_edit = QLineEdit()
        self._system_search_edit.setPlaceholderText("System name…")
        self._system_search_completer = QCompleter([])
        self._system_search_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._system_search_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._system_search_completer.popup().setStyleSheet(
            "QAbstractItemView { background:#0a1520; color:#c8c8c8; border:1px solid #1e3a5a;"
            " selection-background-color:#1a3a5a; selection-color:#FFB347; }"
        )
        self._system_search_edit.setCompleter(self._system_search_completer)
        self._system_search_edit.returnPressed.connect(self._on_system_search)
        search_row.addWidget(self._system_search_edit, 1)
        root.addLayout(search_row)

        self._buckets_widget = QWidget()
        self._buckets_layout = QGridLayout(self._buckets_widget)
        self._buckets_layout.setSpacing(6)
        root.addWidget(self._buckets_widget, 1)
        self._bucket_dialogs: Dict[str, "_FactionBucketDialog"] = {}
        self._last_buckets: Dict[str, List[dict]] = {}

        # ── Active missions for this faction (what to complete) ───────────
        missions_hdr = QLabel("ACTIVE MISSIONS — HELP THIS FACTION")
        missions_hdr.setStyleSheet(_HDR_STYLE)
        root.addWidget(missions_hdr)

        self._missions_status_label = QLabel("")
        self._missions_status_label.setWordWrap(True)
        self._missions_status_label.setStyleSheet("background:transparent; border:none; color:#888888; font-size:12px;")
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
            " padding:3px; font-size:12px; font-weight:bold; letter-spacing:1px; }"
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

    def update_reference_state(self, state) -> None:
        """Cheap position-only update — keeps distance calcs fresh every
        event without triggering the expensive full bucket rebuild."""
        self._last_state = state

        system_name = getattr(state, "system", None) if state else None
        if system_name != self._last_stations_system:
            self._last_stations_system = system_name
            if self._faction_name:
                self._refresh_faction_stations(self._faction_name, state)
                self._start_station_lookup(system_name)

        bounty_cr = getattr(state, "squadron_bgs_bounty_cr", 0) or 0
        trade_cr = getattr(state, "squadron_bgs_trade_cr", 0) or 0
        if not self._faction_name or (not bounty_cr and not trade_cr):
            self._bgs_contribution_label.setVisible(False)
            return
        self._bgs_contribution_label.setText(
            f"Your BGS contribution to {self._faction_name} this session — "
            f"bounties redeemed: {bounty_cr:,} cr, trade: {trade_cr:,} cr "
            "(only counted at stations it controls)."
        )
        self._bgs_contribution_label.setVisible(True)

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
            self._rebuild_buckets([])
            self._missions_status_label.setText("")
            self._missions_table.setRowCount(0)
            self._stations_status_label.setText("")
            self._stations_table.setRowCount(0)
            return

        self._faction_name = overview["faction_name"]
        systems = overview.get("systems") or []
        controlling_count = sum(1 for s in systems if s.get("is_controlling"))
        self._summary_label.setText(
            f"Faction: {overview['faction_name']} — present in {len(systems)} system"
            f"{'s' if len(systems) != 1 else ''}, controlling {controlling_count}."
        )
        self._maybe_auto_refresh_all()

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

        try:
            self._last_predictions = {
                p["system_address"]: p
                for p in self._repo.get_faction_predictions(self._faction_name)
                if isinstance(p.get("system_address"), int)
            }
        except Exception:
            log.exception("Failed to compute faction predictions")
            self._last_predictions = {}

        self._rebuild_buckets(systems)
        self._refresh_active_missions(self._faction_name, state)
        self._refresh_faction_stations(self._faction_name, state)

    def _compute_buckets(self, systems: List[dict]) -> Dict[str, List[dict]]:
        """Sorts tracked systems into status buckets — a system can land in
        several at once (e.g. War + Stale Data). "No Action" only gets a
        system that matched none of the "needs attention" buckets; "Stale
        Data" is checked independently of that, on its own axis."""
        buckets: Dict[str, List[dict]] = {key: [] for key, _, _ in _BUCKET_DEFS}
        today = date.today()

        for s in systems:
            active_names = [s.get("faction_state")] if s.get("faction_state") and s.get("faction_state") != "None" else []
            active_names += [st for st in _parse_states(s.get("active_states")) if st not in active_names]
            active_lower = {n.lower() for n in active_names}
            pending_lower = {n.lower() for n in _parse_states(s.get("pending_states"))}
            system_address = s.get("system_address")
            prediction = self._last_predictions.get(system_address) if isinstance(system_address, int) else None

            has_action = False
            for key in ("war", "election", "civilunrest", "pirateattack", "boom", "bust",
                        "outbreak", "famine", "drought", "blight", "lockdown"):
                matched = bool(active_lower & {"war", "civilwar"}) if key == "war" else key in active_lower
                if matched:
                    buckets[key].append(s)
                    has_action = True

            if "expansion" in pending_lower:
                buckets["expansion_pending"].append(s)
                has_action = True
            if "retreat" in pending_lower:
                buckets["retreat_pending"].append(s)
                has_action = True
            if pending_lower & {"war", "civilwar"}:
                buckets["conflict_pending"].append(s)
                has_action = True

            if prediction:
                if prediction.get("conflict_risk"):
                    buckets["conflict_risk"].append(s)
                    has_action = True
                elif prediction.get("days_in_expansion_range") is not None:
                    buckets["expansion_likely"].append(s)
                    has_action = True
                elif prediction.get("days_in_retreat_range") is not None:
                    buckets["retreat_risk"].append(s)
                    has_action = True

            snapshot_date = s.get("snapshot_date")
            if isinstance(snapshot_date, str):
                try:
                    if (today - date.fromisoformat(snapshot_date[:10])).days > 7:
                        buckets["stale"].append(s)
                except ValueError:
                    pass

            if not isinstance(s.get("influence"), (int, float)):
                buckets["no_data"].append(s)

            if not has_action:
                buckets["no_action"].append(s)

        return buckets

    def _rebuild_buckets(self, systems: List[dict]) -> None:
        self._last_buckets = self._compute_buckets(systems)
        self._update_data_freshness_label(systems)

        names = sorted({s.get("system_name") for s in systems if s.get("system_name")})
        model = self._system_search_completer.model()
        if isinstance(model, QStringListModel):
            model.setStringList(names)
        else:
            self._system_search_completer.setModel(QStringListModel(names, self._system_search_completer))

        while self._buckets_layout.count():
            item = self._buckets_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        cols = 4
        for i, (key, label, color) in enumerate(_BUCKET_DEFS):
            count = len(self._last_buckets[key])
            btn = QPushButton(f"{label}\n{count} system{'s' if count != 1 else ''}")
            btn.setMinimumHeight(54)
            btn.setEnabled(count > 0)
            btn.setStyleSheet(
                f"QPushButton {{ background:{color}; color:#e6e6e6; border:1px solid #2a5a8a;"
                " border-radius:5px; font-weight:bold; padding:6px; }"
                "QPushButton:hover { background:#2a5a8a; }"
                "QPushButton:disabled { background:#161616; color:#555; border-color:#333; }"
            )
            btn.clicked.connect(lambda _checked=False, k=key, l=label: self._open_bucket_dialog(k, l))
            self._buckets_layout.addWidget(btn, i // cols, i % cols)

        for key, dlg in self._bucket_dialogs.items():
            if dlg.isVisible() and key != "search":
                dlg.set_systems(self._last_buckets.get(key, []))

    def _open_bucket_dialog(self, key: str, label: str) -> None:
        systems = self._last_buckets.get(key, [])
        dlg = self._bucket_dialogs.get(key)
        if dlg is None:
            dlg = _FactionBucketDialog(self, label)
            self._bucket_dialogs[key] = dlg
        dlg.set_systems(systems)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _on_system_search(self) -> None:
        query = self._system_search_edit.text().strip().lower()
        if not query or not self._last_overview:
            return
        systems = [
            s for s in (self._last_overview.get("systems") or [])
            if query in (s.get("system_name") or "").lower()
        ]
        self._open_bucket_dialog("search", "Search Results")
        self._bucket_dialogs["search"].set_systems(systems)

    def _build_row_items(self, s: dict) -> List[QTableWidgetItem]:
        """Builds the 9 QTableWidgetItems for one systems-table row from a
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
        is_pirate_attack = "pirateattack" in active_lower

        pending_names = _parse_states(s.get("pending_states"))
        pending_item = QTableWidgetItem(", ".join(pending_names) if pending_names else "—")

        rep = s.get("my_reputation")
        rep_value = float(rep) if isinstance(rep, (int, float)) else -999.0
        rep_item = _NumericTableWidgetItem(f"{rep_value:.1f}" if isinstance(rep, (int, float)) else "—", rep_value)

        action_text, color = derive_bgs_action(s)
        action_item = QTableWidgetItem(action_text)
        action_item.setForeground(QColor(color))
        action_item.setToolTip(action_text)

        system_address = s.get("system_address")
        prediction = self._last_predictions.get(system_address) if isinstance(system_address, int) else None
        forecast_text, forecast_color = _format_forecast(prediction)
        forecast_item = QTableWidgetItem(forecast_text)
        forecast_item.setForeground(QColor(forecast_color))
        forecast_item.setToolTip(forecast_text)

        # Active/Pending states can list several comma-joined names too —
        # same narrow-window truncation risk as Action/Forecast.
        if active_names:
            active_item.setToolTip(", ".join(active_names))
        if pending_names:
            pending_item.setToolTip(", ".join(pending_names))

        for it in (infl_item, ctrl_item, active_item, pending_item, rep_item, forecast_item):
            it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        if s.get("is_controlling"):
            ctrl_item.setForeground(QColor("#6BCB77"))
        if pending_names:
            pending_item.setForeground(QColor("#FFD93D"))

        row_items = [name_item, infl_item, ctrl_item, active_item, pending_item, rep_item, action_item, forecast_item]
        # War/Civil War/Election/Pirate Attack are the states that most
        # urgently need squadron attention — highlight the whole row, not
        # just a cell, so it's obvious scanning down the System column alone.
        if is_war:
            for it in row_items:
                it.setBackground(QColor(90, 30, 30))
            active_item.setForeground(QColor("#FF6B6B"))
        elif is_election:
            for it in row_items:
                it.setBackground(QColor(80, 65, 10))
            active_item.setForeground(QColor("#FFD93D"))
        elif is_pirate_attack:
            for it in row_items:
                it.setBackground(QColor(90, 50, 10))
            active_item.setForeground(QColor("#FF9933"))

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
        Called on arrival in a system — patches just that one system's data
        instead of a full DB requery. BGS state only ticks daily server-side,
        so there's no need to re-check every tracked system just because the
        player jumped somewhere. Bucket tiles are cheap to recompute (a Python
        scan over a few hundred small dicts, no widget churn), so they're
        refreshed every time — unlike the old flat table's per-row rebuild.
        """
        if not self._faction_name or not isinstance(system_address, int) or not self._last_overview:
            return
        try:
            status = self._repo.get_player_faction_system_status(self._faction_name, system_address)
        except Exception:
            log.exception("Failed to load single-system faction status for %s", system_address)
            return
        if not status:
            return  # not a tracked system — nothing to update

        systems = self._last_overview.get("systems") or []
        for i, s in enumerate(systems):
            if s.get("system_address") == system_address:
                systems[i] = status
                break
        self._rebuild_buckets(systems)

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

    def _refresh_faction_stations(self, faction_name: str, state) -> None:
        system_name = getattr(state, "system", None) if state else None
        if not system_name:
            self._stations_status_label.setText("No current system yet — jump to a system first.")
            self._stations_table.setRowCount(0)
            self._stations_table.setVisible(False)
            return

        try:
            stations = self._repo.find_faction_stations_in_system(system_name, faction_name)
        except Exception:
            log.exception("Failed to load faction-controlled stations")
            stations = []

        if not stations:
            self._stations_status_label.setText(
                f"No known stations/settlements controlled by {faction_name} in {system_name}."
            )
            self._stations_table.setRowCount(0)
            self._stations_table.setVisible(False)
            return

        self._stations_status_label.setText(
            f"{len(stations)} known station{'s' if len(stations) != 1 else ''} "
            f"controlled by {faction_name} in {system_name} (from our own visits — "
            "checking EDSM for the full list…)."
        )
        self._populate_stations_table(stations)

    def _populate_stations_table(self, stations: List[dict]) -> None:
        self._stations_table.setVisible(True)
        self._stations_table.setSortingEnabled(False)
        self._stations_table.setRowCount(len(stations))
        for row, s in enumerate(stations):
            name_item = QTableWidgetItem(s.get("station_name") or "—")
            type_item = QTableWidgetItem(s.get("station_type") or "—")
            pad_item = QTableWidgetItem(s.get("pad_size") or "?")
            for it in (type_item, pad_item):
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            self._stations_table.setItem(row, 0, name_item)
            self._stations_table.setItem(row, 1, type_item)
            self._stations_table.setItem(row, 2, pad_item)
        self._stations_table.setSortingEnabled(True)
        row_h = self._stations_table.verticalHeader().defaultSectionSize()
        content_h = self._stations_table.horizontalHeader().height() + len(stations) * row_h + 4
        self._stations_table.setMaximumHeight(min(content_h, 160))

    def _start_station_lookup(self, system_name: Optional[str]) -> None:
        """EDSM's static station catalog knows about every station in a
        system regardless of recent Docked traffic — confirmed live that
        our own EDDN-sourced station_info can know about just 1 of 7
        stations a faction actually controls in a system. Runs once per
        system arrival, on a background thread (real network call)."""
        if not system_name or not self._faction_name:
            return
        if system_name == self._station_lookup_system:
            return  # already queried (or in flight) for this exact system
        if self._station_thread and self._station_thread.isRunning():
            return
        self._station_lookup_system = system_name

        self._station_worker = _EdsmStationLookupWorker(self._repo.db.db_path, system_name)
        self._station_thread = QThread()
        self._station_worker.moveToThread(self._station_thread)
        self._station_thread.started.connect(self._station_worker.run)
        self._station_worker.finished.connect(self._on_station_lookup_finished)
        self._station_worker.finished.connect(self._station_thread.quit)
        self._station_thread.start()

    def _on_station_lookup_finished(self, stations, error, system_name: str) -> None:
        if system_name != self._last_stations_system:
            return  # player already moved on — this result is stale
        if not stations:
            # Blocked/not-found — leave whatever the fast local-DB pass
            # already showed rather than clobbering it with nothing.
            return

        target = self._faction_name.strip().lower() if self._faction_name else ""
        matched = [s for s in stations if (s.get("controlling_faction") or "").strip().lower() == target]

        if not matched:
            self._stations_status_label.setText(
                f"EDSM: no stations/settlements controlled by {self._faction_name} in {system_name}."
            )
            self._stations_table.setRowCount(0)
            self._stations_table.setVisible(False)
            return

        matched.sort(key=lambda s: s.get("station_name") or "")
        self._stations_status_label.setText(
            f"{len(matched)} station{'s' if len(matched) != 1 else ''} controlled by "
            f"{self._faction_name} in {system_name} (EDSM's full system catalog)."
        )
        self._populate_stations_table(matched)

    def _on_stations_cell_clicked(self, row: int, column: int) -> None:
        if column != 0:  # Station
            return
        item = self._stations_table.item(row, column)
        if item and item.text():
            QApplication.clipboard().setText(item.text())

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

    # ── Full EDSM refresh (all systems, all factions) ────────────────────

    def _maybe_auto_refresh_all(self) -> None:
        """Called once per session, the first time a squadron-aligned
        faction is known — auto-starts the full refresh if it's been about
        a day (or never) since the last one."""
        if self._auto_refresh_checked or not self._refresh_tracker or not self._faction_name:
            return
        self._auto_refresh_checked = True
        last = self._refresh_tracker.last_refresh()
        self._update_refresh_status_label(last)
        if last is not None:
            age_hours = (datetime.now(timezone.utc) - last).total_seconds() / 3600.0
            if age_hours < 24.0:
                return
        if _in_weekly_maintenance_window():
            # Frontier's weekly server maintenance (Thursdays ~09:00-11:00
            # local) — EDSM tends to be unreliable then too, no point
            # burning ~700 requests into it. Manual "Refresh All"/"Recheck"
            # clicks are NOT gated — this only skips the automatic trigger.
            return
        self._start_refresh_all()

    def _update_refresh_status_label(self, last) -> None:
        if last is None:
            self._refresh_status_label.setText("Full EDSM refresh: never run yet")
            return
        from datetime import datetime, timezone
        age_hours = (datetime.now(timezone.utc) - last).total_seconds() / 3600.0
        if age_hours < 1:
            age_txt = "less than an hour ago"
        elif age_hours < 24:
            age_txt = f"{int(age_hours)}h ago"
        else:
            age_txt = f"{int(age_hours // 24)}d ago"
        self._refresh_status_label.setText(f"Full EDSM refresh: {age_txt}")

    def _update_data_freshness_label(self, systems: List[dict]) -> None:
        """Per-system snapshot age breakdown — day-granularity only, since
        that's all snapshot_date tracks (no exact BGS tick-time available)."""
        if not systems:
            self._data_freshness_label.setText("")
            return
        today = date.today()
        today_count = 0
        recent_count = 0  # 1-6 days
        stale_count = 0   # 7+ days (matches the Stale Data bucket threshold)
        no_data_count = 0
        for s in systems:
            snapshot_date = s.get("snapshot_date")
            if not isinstance(snapshot_date, str):
                no_data_count += 1
                continue
            try:
                age_days = (today - date.fromisoformat(snapshot_date[:10])).days
            except ValueError:
                no_data_count += 1
                continue
            if age_days <= 0:
                today_count += 1
            elif age_days < 7:
                recent_count += 1
            else:
                stale_count += 1
        self._data_freshness_label.setText(
            f"Data freshness: {today_count} today · {recent_count} this week · "
            f"{stale_count} stale (7d+) · {no_data_count} no data"
        )

    def _on_refresh_all_clicked(self):
        if not self._faction_name:
            self._refresh_status_label.setText(
                "No squadron-aligned faction known yet — this activates once one is detected."
            )
            return
        self._start_refresh_all()

    def _start_refresh_all(self):
        if not self._faction_name:
            return
        if (self._lookup_thread and self._lookup_thread.isRunning()) or \
           (self._csv_thread and self._csv_thread.isRunning()) or \
           (self._refresh_all_thread and self._refresh_all_thread.isRunning()):
            return
        try:
            system_names = sorted(self._repo.get_known_system_names(self._faction_name))
        except Exception:
            log.exception("Failed to load known system names for full refresh")
            return
        if not system_names:
            return

        # Snapshot dates are day-granularity, so "older than 24h" means
        # "not already refreshed today" — skips systems a live arrival (or
        # an earlier refresh today) already updated, cutting EDSM request
        # volume instead of re-querying every tracked system every time.
        today = date.today().isoformat()
        fresh_today = {
            s.get("system_name")
            for s in (self._last_overview.get("systems") if self._last_overview else None) or []
            if isinstance(s.get("snapshot_date"), str) and s["snapshot_date"][:10] == today
        }
        system_names = [n for n in system_names if n not in fresh_today]
        if not system_names:
            self._refresh_status_label.setText("Full EDSM refresh: all systems already current today.")
            return

        self._refresh_all_btn.setEnabled(False)
        self._cancel_refresh_btn.setVisible(True)
        self._refresh_status_label.setText(f"Refreshing 0 / {len(system_names)}…")

        self._refresh_all_worker = _FactionRefreshWorker(self._repo.db.db_path, system_names)
        self._refresh_all_thread = QThread()
        self._refresh_all_worker.moveToThread(self._refresh_all_thread)
        self._refresh_all_thread.started.connect(self._refresh_all_worker.run)
        self._refresh_all_worker.progress.connect(self._on_refresh_all_progress)
        self._refresh_all_worker.finished.connect(self._on_refresh_all_finished)
        self._refresh_all_worker.finished.connect(self._refresh_all_thread.quit)
        self._refresh_all_thread.start()

    def _on_cancel_refresh_clicked(self):
        if self._refresh_all_worker:
            self._refresh_all_worker.cancel()
        self._cancel_refresh_btn.setEnabled(False)

    def _on_refresh_all_progress(self, current: int, total: int, system_name: str):
        self._refresh_status_label.setText(f"Refreshing {current} / {total}: {system_name}")

    def _on_refresh_all_finished(self, refreshed: int, failed: int):
        self._refresh_all_btn.setEnabled(True)
        self._cancel_refresh_btn.setVisible(False)
        self._cancel_refresh_btn.setEnabled(True)

        if self._refresh_tracker:
            self._refresh_tracker.mark_refreshed()

        failed_txt = f", {failed} failed (blocked/not found)" if failed else ""
        self._refresh_status_label.setText(
            f"Full EDSM refresh: just now — {refreshed} refreshed{failed_txt}"
        )
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


class _FactionBucketDialog(QDialog):
    """
    Non-modal detail window for one status bucket — stays open, movable, and
    independent of the main window's tab switching (a plain QDialog with no
    parent-modality set does this for free). Reuses PlayerFactionPanel's own
    row-building so a bucket's table looks identical to the old flat table.
    """

    def __init__(self, panel: "PlayerFactionPanel", label: str):
        super().__init__(None)
        self.setStyleSheet("QDialog { background:#080f18; color:#c8c8c8; }")
        self._panel = panel
        self._all_systems: List[dict] = []
        self.setWindowTitle(f"Player Faction — {label}")
        self.resize(900, 500)

        layout = QVBoxLayout(self)
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Search:"))
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("System name…")
        self._search_edit.textChanged.connect(self._apply_filter)
        search_row.addWidget(self._search_edit, 1)
        self._sort_distance_btn = QPushButton("Sort by Distance")
        self._sort_distance_btn.setToolTip(
            "Distance from your current system — visit the closest first. "
            "Systems with no known coordinates sink to the bottom."
        )
        self._sort_distance_btn.clicked.connect(self._sort_by_distance)
        search_row.addWidget(self._sort_distance_btn)
        self._recheck_btn = QPushButton("Recheck via EDSM")
        self._recheck_btn.setToolTip("Re-queries EDSM for exactly the systems currently shown here.")
        self._recheck_btn.clicked.connect(self._on_recheck_clicked)
        search_row.addWidget(self._recheck_btn)
        layout.addLayout(search_row)

        self._recheck_status = QLabel("")
        self._recheck_status.setStyleSheet("background:transparent; border:none; color:#888888; font-size:11px;")
        layout.addWidget(self._recheck_status)

        self._table = QTableWidget()
        self._table.setColumnCount(10)
        self._table.setHorizontalHeaderLabels(
            ["System", "Influence", "Controlling", "Active", "Pending", "Reputation", "Action", "Forecast", "Distance (ly)", ""]
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
            " padding:3px; font-size:12px; font-weight:bold; letter-spacing:1px; }"
            "QTableWidget::item:selected { background:#1a3a5a; color:#FFB347; }"
        )
        h = self._table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in (1, 2, 3, 4, 5, 8, 9):
            h.setSectionResizeMode(c, QHeaderView.ResizeMode.Interactive)
        h.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
        self._table.setColumnWidth(1, 70)
        self._table.setColumnWidth(2, 90)
        self._table.setColumnWidth(3, 160)
        self._table.setColumnWidth(4, 140)
        self._table.setColumnWidth(5, 80)
        self._table.setColumnWidth(8, 90)
        self._table.setColumnWidth(9, 90)
        self._table.setSortingEnabled(True)
        self._table.cellClicked.connect(self._on_cell_clicked)
        layout.addWidget(self._table, 1)

    def set_systems(self, systems: List[dict]) -> None:
        self._all_systems = systems
        self._apply_filter()

    def _reference_coords(self):
        """Returns (x, y, z) of the player's current system, or None if unknown."""
        state = self._panel._last_state
        x = getattr(state, "system_x", None) if state else None
        y = getattr(state, "system_y", None) if state else None
        z = getattr(state, "system_z", None) if state else None
        if all(isinstance(v, (int, float)) for v in (x, y, z)):
            return (x, y, z)
        return None

    def _apply_filter(self) -> None:
        query = self._search_edit.text().strip().lower()
        rows = [
            s for s in self._all_systems
            if not query or query in (s.get("system_name") or "").lower()
        ]

        ref = self._reference_coords()
        coords = self._panel._repo.get_system_coords_for_names(
            [s.get("system_name") for s in rows if s.get("system_name")]
        ) if ref else {}

        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(rows))
        for row, s in enumerate(rows):
            items = self._panel._build_row_items(s)

            dist_value = float("inf")
            dist_text = "—"
            c = coords.get(s.get("system_name"))
            if ref and c:
                dist_value = ((c[0] - ref[0]) ** 2 + (c[1] - ref[1]) ** 2 + (c[2] - ref[2]) ** 2) ** 0.5
                dist_text = f"{dist_value:.1f} ly"
            dist_item = _NumericTableWidgetItem(dist_text, dist_value)
            dist_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            items.insert(8, dist_item)

            for col, item in enumerate(items):
                self._table.setItem(row, col, item)
        self._table.setSortingEnabled(True)

    def _sort_by_distance(self) -> None:
        ref = self._reference_coords()
        if not ref:
            return
        names = [s.get("system_name") for s in self._all_systems if s.get("system_name")]
        coords = self._panel._repo.get_system_coords_for_names(names)

        def _dist(s: dict) -> float:
            c = coords.get(s.get("system_name"))
            if not c:
                return float("inf")
            return ((c[0] - ref[0]) ** 2 + (c[1] - ref[1]) ** 2 + (c[2] - ref[2]) ** 2) ** 0.5

        self._all_systems.sort(key=_dist)
        self._apply_filter()

    def _on_recheck_clicked(self) -> None:
        names = [s.get("system_name") for s in self._all_systems if s.get("system_name")]
        if not names:
            return
        self._recheck_btn.setEnabled(False)
        self._recheck_status.setText(f"Rechecking 0 / {len(names)}…")
        self._recheck_worker = _FactionRefreshWorker(self._panel._repo.db.db_path, names)
        self._recheck_thread = QThread()
        self._recheck_worker.moveToThread(self._recheck_thread)
        self._recheck_thread.started.connect(self._recheck_worker.run)
        self._recheck_worker.progress.connect(
            lambda cur, total, name: self._recheck_status.setText(f"Rechecking {cur} / {total}: {name}")
        )
        self._recheck_worker.finished.connect(self._on_recheck_finished)
        self._recheck_worker.finished.connect(self._recheck_thread.quit)
        self._recheck_thread.start()

    def _on_recheck_finished(self, refreshed: int, failed: int) -> None:
        self._recheck_btn.setEnabled(True)
        self._recheck_status.setText(f"Done — {refreshed} refreshed, {failed} failed.")
        self._panel.refresh(self._panel._last_state)
        self._apply_filter()

    def _on_cell_clicked(self, row: int, column: int) -> None:
        if column == 9:  # Remove
            item = self._table.item(row, 9)
            if item is None:
                return
            system_address = item.data(Qt.ItemDataRole.UserRole)
            self._panel._on_remove_system_clicked(system_address)
            self._all_systems = [s for s in self._all_systems if s.get("system_address") != system_address]
            self._apply_filter()
            return
        if column == 0:  # System name — click to copy
            item = self._table.item(row, 0)
            if item and item.text():
                QApplication.clipboard().setText(item.text())
