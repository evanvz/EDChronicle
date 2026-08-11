"""Squadron tab — name, rank, rank history, and trophies from journal-
exposed squadron events. The game does not expose a member roster, chat,
or wing-mission data to third-party tools, so that's not something this
panel can show; the squadron-aligned minor faction BGS data is tracked
separately on the Player Faction tab.
"""
from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame, QDialog, QApplication,
)

log = logging.getLogger(__name__)

_CARD_STYLE = "QFrame { background:#0d1a2a; border:1px solid #1e3a5a; border-radius:5px; }"
_HDR_STYLE = "color:#7a7a7a; font-size:12px; font-weight:bold; letter-spacing:1px; background:transparent; border:none;"
_BTN_STYLE = (
    "QPushButton { background:#1a3a5a; color:#FFB347; border:1px solid #2a5a8a;"
    " border-radius:3px; padding:3px 12px; font-weight:bold; }"
    "QPushButton:hover { background:#2a5a8a; }"
)


class _ColonisationDetailDialog(QDialog):
    """Non-modal detail window for one construction site — full resource
    breakdown, with a per-commodity button to jump to Market tab and search
    for the nearest place to buy whatever's still needed."""

    def __init__(self, panel: "SquadronPanel", depot: dict, dist_text: str = "—"):
        super().__init__(None)
        self.setStyleSheet("QDialog { background:#080f18; color:#c8c8c8; }")
        self._panel = panel
        title = f"{depot.get('station_name')} — {depot.get('system_name')}"
        self.setWindowTitle(f"Colonisation Construction — {title}")
        self.resize(700, 420)

        layout = QVBoxLayout(self)
        hdr_row = QHBoxLayout()
        hdr = QLabel(title)
        hdr.setStyleSheet("color:#FFB347; font-size:14px; font-weight:bold; background:transparent; border:none;")
        hdr_row.addWidget(hdr, 1)
        copy_system_btn = QPushButton("Copy System")
        copy_system_btn.setStyleSheet(_BTN_STYLE)
        copy_system_btn.clicked.connect(
            lambda: QApplication.clipboard().setText(depot.get("system_name") or "")
        )
        hdr_row.addWidget(copy_system_btn)
        copy_station_btn = QPushButton("Copy Station")
        copy_station_btn.setStyleSheet(_BTN_STYLE)
        copy_station_btn.clicked.connect(
            lambda: QApplication.clipboard().setText(depot.get("station_name") or "")
        )
        hdr_row.addWidget(copy_station_btn)
        layout.addLayout(hdr_row)

        progress = depot.get("progress")
        status = "Complete" if depot.get("complete") else (
            f"{progress * 100:.1f}% complete" if isinstance(progress, (int, float)) else "Not yet visited"
        )
        dist_suffix = f" — {dist_text} ly from your current location" if dist_text and dist_text != "—" else ""
        status_label = QLabel(status + dist_suffix)
        status_label.setStyleSheet("color:#888888; background:transparent; border:none;")
        layout.addWidget(status_label)

        trailblazer = self._find_closest_trailblazer(panel, depot.get("system_name"))
        trailblazer_row = QHBoxLayout()
        if trailblazer:
            text = (
                f"Nearest Trailblazer supply ship: {trailblazer['station_name']} "
                f"({trailblazer['system_name']}) — {trailblazer['distance_ly']:.1f} ly"
            )
            trailblazer_system = trailblazer["system_name"]
        else:
            text = "Nearest Trailblazer supply ship: none known yet."
            trailblazer_system = ""
        trailblazer_label = QLabel(text)
        trailblazer_label.setWordWrap(True)
        trailblazer_label.setToolTip(
            "Brewer Corporation's colonisation-materials supply ships — best-effort only. "
            "They reportedly relocate occasionally and EDDN coverage of them is patchy, "
            "so this is whatever we happen to have on file, not guaranteed current."
        )
        trailblazer_label.setStyleSheet("color:#4D96FF; background:transparent; border:none;")
        trailblazer_row.addWidget(trailblazer_label, 1)
        copy_trailblazer_btn = QPushButton("Copy System")
        copy_trailblazer_btn.setStyleSheet(_BTN_STYLE)
        copy_trailblazer_btn.setEnabled(bool(trailblazer_system))
        copy_trailblazer_btn.clicked.connect(
            lambda: QApplication.clipboard().setText(trailblazer_system)
        )
        trailblazer_row.addWidget(copy_trailblazer_btn)
        layout.addLayout(trailblazer_row)

        table = QTableWidget()
        table.setColumnCount(5)
        table.setHorizontalHeaderLabels(["Commodity", "Required", "Provided", "Still Needed", ""])
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setStyleSheet(
            "QTableWidget { background:#080f18; alternate-background-color:#0a1520;"
            " gridline-color:#1e3a5a; border:1px solid #1e3a5a; }"
            "QHeaderView::section { background:#0d1a2a; color:#888888; border:none;"
            " padding:3px; font-size:12px; font-weight:bold; letter-spacing:1px; }"
        )
        h = table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in (1, 2, 3, 4):
            h.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)

        resources = depot.get("resources") or []
        table.setRowCount(len(resources))
        for row, r in enumerate(resources):
            required = r.get("required") or 0
            provided = r.get("provided") or 0
            remaining = max(0, required - provided)

            name_item = QTableWidgetItem(r.get("name") or "—")
            req_item = QTableWidgetItem(f"{required:,}")
            prov_item = QTableWidgetItem(f"{provided:,}")
            rem_item = QTableWidgetItem(f"{remaining:,}")
            for it in (req_item, prov_item, rem_item):
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if remaining <= 0:
                rem_item.setForeground(QColor("#6BCB77"))
            else:
                rem_item.setForeground(QColor("#FF6B6B"))

            table.setItem(row, 0, name_item)
            table.setItem(row, 1, req_item)
            table.setItem(row, 2, prov_item)
            table.setItem(row, 3, rem_item)

            if remaining > 0:
                btn = QPushButton("Find Source")
                btn.setStyleSheet(_BTN_STYLE)
                name = r.get("name") or ""
                btn.clicked.connect(lambda _checked=False, n=name: self._panel.buy_search_requested.emit(n))
                table.setCellWidget(row, 4, btn)

        layout.addWidget(table, 1)

    @staticmethod
    def _find_closest_trailblazer(panel: "SquadronPanel", system_name: Optional[str]) -> Optional[dict]:
        if not system_name:
            return None
        try:
            coords = panel._repo.get_system_coords_for_names([system_name])
            here = coords.get(system_name)
            if not here:
                return None
            return panel._repo.find_closest_trailblazer(here[0], here[1], here[2])
        except Exception:
            log.exception("Failed to look up closest Trailblazer for %s", system_name)
            return None


class SquadronPanel(QWidget):
    buy_search_requested = pyqtSignal(str)

    def __init__(self, repo, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._depots: list = []
        self._depot_dialogs: dict = {}
        self._last_state = None

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 8)
        root.setSpacing(6)

        # ── Status card ──────────────────────────────────────────────────
        status_card = QFrame()
        status_card.setStyleSheet(_CARD_STYLE)
        status_l = QVBoxLayout(status_card)
        status_l.setContentsMargins(8, 6, 8, 6)
        status_l.setSpacing(4)

        hdr = QLabel("SQUADRON")
        hdr.setStyleSheet(_HDR_STYLE)
        status_l.addWidget(hdr)

        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet("background:transparent; border:none; color:#c8c8c8; font-size:13px;")
        status_l.addWidget(self._status_label)

        root.addWidget(status_card)

        # ── BGS pointer ──────────────────────────────────────────────────
        bgs_card = QFrame()
        bgs_card.setStyleSheet(_CARD_STYLE)
        bgs_l = QVBoxLayout(bgs_card)
        bgs_l.setContentsMargins(8, 6, 8, 6)
        bgs_l.setSpacing(4)

        bgs_hdr = QLabel("SQUADRON-ALIGNED FACTION (BGS)")
        bgs_hdr.setStyleSheet(_HDR_STYLE)
        bgs_l.addWidget(bgs_hdr)

        self._bgs_label = QLabel("")
        self._bgs_label.setWordWrap(True)
        self._bgs_label.setStyleSheet("background:transparent; border:none; color:#888888;")
        bgs_l.addWidget(self._bgs_label)

        root.addWidget(bgs_card)

        # ── Colonisation construction — tracked sites ───────────────────────
        # Only ever populated from our own personal visits (no EDDN schema
        # exists for this event) — manually adding a site here lets you keep
        # a checklist of squadron construction projects before you've been.
        colon_card = QFrame()
        colon_card.setStyleSheet(_CARD_STYLE)
        colon_l = QVBoxLayout(colon_card)
        colon_l.setContentsMargins(8, 6, 8, 6)
        colon_l.setSpacing(4)

        colon_hdr = QLabel("COLONISATION CONSTRUCTION — TRACKED SITES")
        colon_hdr.setStyleSheet(_HDR_STYLE)
        colon_l.addWidget(colon_hdr)

        colon_note = QLabel(
            "Progress only updates when you personally dock at the site — add one before "
            "visiting to keep a checklist, or it appears automatically once you dock there."
        )
        colon_note.setWordWrap(True)
        colon_note.setStyleSheet("color:#7a7a7a; font-size:11px; background:transparent; border:none;")
        colon_l.addWidget(colon_note)

        add_row = QHBoxLayout()
        self._depot_system_edit = QLineEdit()
        self._depot_system_edit.setPlaceholderText("System name")
        self._depot_system_edit.setStyleSheet("background:#0a1520; color:#c8c8c8; border:1px solid #1e3a5a;")
        self._depot_station_edit = QLineEdit()
        self._depot_station_edit.setPlaceholderText("Station/site name")
        self._depot_station_edit.setStyleSheet("background:#0a1520; color:#c8c8c8; border:1px solid #1e3a5a;")
        add_btn = QPushButton("Add")
        add_btn.setStyleSheet(_BTN_STYLE)
        add_btn.clicked.connect(self._on_add_depot_clicked)
        add_row.addWidget(self._depot_system_edit, 1)
        add_row.addWidget(self._depot_station_edit, 1)
        add_row.addWidget(add_btn)
        colon_l.addLayout(add_row)

        self._depot_table = QTableWidget()
        self._depot_table.setColumnCount(6)
        self._depot_table.setHorizontalHeaderLabels(["System", "Station", "Dist (ly)", "Progress", "Status", ""])
        self._depot_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._depot_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._depot_table.verticalHeader().setVisible(False)
        self._depot_table.verticalHeader().setDefaultSectionSize(20)
        self._depot_table.setAlternatingRowColors(True)
        self._depot_table.setStyleSheet(
            "QTableWidget { background:#080f18; alternate-background-color:#0a1520;"
            " gridline-color:#1e3a5a; border:1px solid #1e3a5a; }"
            "QHeaderView::section { background:#0d1a2a; color:#888888; border:none;"
            " padding:3px; font-size:12px; font-weight:bold; letter-spacing:1px; }"
            "QTableWidget::item:selected { background:#1a3a5a; color:#FFB347; }"
        )
        dh = self._depot_table.horizontalHeader()
        dh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        dh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for c in (2, 3, 4, 5):
            dh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self._depot_table.cellClicked.connect(self._on_depot_cell_clicked)
        self._depot_table.setMaximumHeight(160)
        colon_l.addWidget(self._depot_table)

        root.addWidget(colon_card)

        # ── Rank history ─────────────────────────────────────────────────
        history_hdr = QLabel("RANK HISTORY")
        history_hdr.setStyleSheet(_HDR_STYLE)
        root.addWidget(history_hdr)

        self._history_table = QTableWidget()
        self._history_table.setColumnCount(3)
        self._history_table.setHorizontalHeaderLabels(["Date", "Change", "Rank"])
        self._history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._history_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._history_table.verticalHeader().setVisible(False)
        self._history_table.setAlternatingRowColors(True)
        self._history_table.setStyleSheet(
            "QTableWidget { background:#080f18; alternate-background-color:#0a1520;"
            " gridline-color:#1e3a5a; border:1px solid #1e3a5a; }"
            "QHeaderView::section { background:#0d1a2a; color:#888888; border:none;"
            " padding:3px; font-size:12px; font-weight:bold; letter-spacing:1px; }"
        )
        h = self._history_table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self._history_table, 1)

    def refresh(self, state) -> None:
        self._last_state = state
        self._refresh_depots(state)

        name = getattr(state, "squadron_name", None)
        if not name:
            self._status_label.setText(
                "No squadron detected yet — this populates automatically once you're in one."
            )
            self._bgs_label.setText("")
            self._history_table.setRowCount(0)
            return

        rank = getattr(state, "squadron_rank", None)
        trophies = getattr(state, "squadron_trophies", 0) or 0
        status = getattr(state, "squadron_status", None)
        status_ts = getattr(state, "squadron_status_timestamp", None)

        rank_txt = f"Rank {rank}" if rank is not None else "Rank unknown"
        trophy_word = "trophy" if trophies == 1 else "trophies"
        lines = [f"<b>{name}</b> — {rank_txt} — {trophies} {trophy_word} won"]
        if status:
            lines.append(f"Last status: {status} ({status_ts or 'unknown date'})")
        self._status_label.setText("<br>".join(lines))

        try:
            overview = self._repo.get_player_faction_overview()
        except Exception:
            log.exception("Failed to load player faction overview")
            overview = None
        if overview:
            self._bgs_label.setText(
                f"{overview['faction_name']} — see the Player Faction tab for full system-by-system detail."
            )
        else:
            self._bgs_label.setText("No squadron-aligned minor faction recorded yet.")

        history = list(getattr(state, "squadron_rank_history", None) or [])
        history.sort(key=lambda h: h.get("timestamp") or "", reverse=True)
        self._history_table.setRowCount(len(history))
        for row, h in enumerate(history):
            date_item = QTableWidgetItem(str(h.get("timestamp") or ""))
            change_item = QTableWidgetItem("Promoted" if h.get("promotion") else "Demoted")
            rank_item = QTableWidgetItem(f"{h.get('old_rank')} → {h.get('new_rank')}")
            rank_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._history_table.setItem(row, 0, date_item)
            self._history_table.setItem(row, 1, change_item)
            self._history_table.setItem(row, 2, rank_item)

    # ── Colonisation construction tracking ──────────────────────────────

    def _refresh_depots(self, state=None) -> None:
        try:
            self._depots = self._repo.get_colonisation_depots()
        except Exception:
            log.exception("Failed to load colonisation depots")
            self._depots = []

        ref_x = getattr(state, "system_x", None) if state else None
        ref_y = getattr(state, "system_y", None) if state else None
        ref_z = getattr(state, "system_z", None) if state else None
        ref = (ref_x, ref_y, ref_z) if all(isinstance(v, (int, float)) for v in (ref_x, ref_y, ref_z)) else None
        coords = {}
        if ref and self._depots:
            try:
                coords = self._repo.get_system_coords_for_names(
                    [d.get("system_name") for d in self._depots if d.get("system_name")]
                )
            except Exception:
                log.exception("Failed to load system coords for colonisation depots")

        self._depot_table.setRowCount(len(self._depots))
        for row, d in enumerate(self._depots):
            progress = d.get("progress")
            if d.get("complete"):
                status_text, status_color = "Complete", "#6BCB77"
            elif isinstance(progress, (int, float)):
                status_text, status_color = "In Progress", "#FFD93D"
            else:
                status_text, status_color = "Not yet visited", "#888888"
            progress_text = f"{progress * 100:.1f}%" if isinstance(progress, (int, float)) else "—"

            dist_text = "—"
            if ref:
                c = coords.get(d.get("system_name"))
                if c:
                    dist = ((c[0] - ref[0]) ** 2 + (c[1] - ref[1]) ** 2 + (c[2] - ref[2]) ** 2) ** 0.5
                    dist_text = f"{dist:.1f}"

            sys_item = QTableWidgetItem(d.get("system_name") or "—")
            station_item = QTableWidgetItem(d.get("station_name") or "—")
            dist_item = QTableWidgetItem(dist_text)
            progress_item = QTableWidgetItem(progress_text)
            status_item = QTableWidgetItem(status_text)
            status_item.setForeground(QColor(status_color))
            remove_item = QTableWidgetItem("✕ Remove")
            remove_item.setForeground(QColor("#d06060"))
            for it in (dist_item, progress_item, status_item, remove_item):
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            self._depot_table.setItem(row, 0, sys_item)
            self._depot_table.setItem(row, 1, station_item)
            self._depot_table.setItem(row, 2, dist_item)
            self._depot_table.setItem(row, 3, progress_item)
            self._depot_table.setItem(row, 4, status_item)
            self._depot_table.setItem(row, 5, remove_item)

        row_h = self._depot_table.verticalHeader().defaultSectionSize()
        content_h = self._depot_table.horizontalHeader().height() + len(self._depots) * row_h + 4
        self._depot_table.setMaximumHeight(min(content_h, 160) if self._depots else 60)

    def _on_add_depot_clicked(self) -> None:
        system_name = self._depot_system_edit.text().strip()
        station_name = self._depot_station_edit.text().strip()
        if not system_name or not station_name:
            return
        try:
            self._repo.add_colonisation_depot_manual(system_name, station_name)
        except Exception:
            log.exception("Failed to add colonisation depot")
            return
        self._depot_system_edit.clear()
        self._depot_station_edit.clear()
        self._refresh_depots(self._last_state)

    def _on_depot_cell_clicked(self, row: int, column: int) -> None:
        if row < 0 or row >= len(self._depots):
            return
        depot = self._depots[row]
        if column == 5:  # Remove
            try:
                self._repo.remove_colonisation_depot(depot["id"])
            except Exception:
                log.exception("Failed to remove colonisation depot")
                return
            self._depot_dialogs.pop(depot["id"], None)
            self._refresh_depots(self._last_state)
            return

        depot_id = depot["id"]
        dlg = self._depot_dialogs.get(depot_id)
        if dlg is None or not dlg.isVisible():
            dist_text = self._depot_table.item(row, 2).text() if self._depot_table.item(row, 2) else "—"
            dlg = _ColonisationDetailDialog(self, depot, dist_text)
            self._depot_dialogs[depot_id] = dlg
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
