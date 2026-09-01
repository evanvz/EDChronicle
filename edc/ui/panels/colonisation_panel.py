"""Colonisation tab — tracked construction sites (squadron-wide projects,
personal-visit-only since no EDDN schema exists for this event) and the
nearby-unpopulated-system candidate finder. Split out of squadron_panel.py
once colonisation stopped being a small side feature and started needing
its own room to grow (candidate system details, a future build-resource
planner).
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

from edc.ui.style import (
    CARD_STYLE as _CARD_STYLE, HDR_STYLE as _HDR_STYLE, PRIMARY_BUTTON_STYLE as _BTN_STYLE,
    TABLE_STYLE as _TABLE_STYLE,
    card_style as _card_style, hdr_style as _hdr_style,
)

log = logging.getLogger(__name__)


class _ColonisationDetailDialog(QDialog):
    """Non-modal detail window for one construction site — full resource
    breakdown, with a per-commodity button to jump to Market tab and search
    for the nearest place to buy whatever's still needed."""

    def __init__(self, panel: "ColonisationPanel", depot: dict, dist_text: str = "—"):
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
    def _find_closest_trailblazer(panel: "ColonisationPanel", system_name: Optional[str]) -> Optional[dict]:
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


class ColonisationPanel(QWidget):
    buy_search_requested = pyqtSignal(str)
    eligibility_check_requested = pyqtSignal(str)  # system name to check

    def __init__(self, repo, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._depots: list = []
        self._depot_dialogs: dict = {}
        self._last_state = None
        self._colonisation_candidates: list = []
        self._colonisation_candidates_system: Optional[str] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 8)
        root.setSpacing(6)

        # ── Colonisation construction — tracked sites ───────────────────────
        # Only ever populated from our own personal visits (no EDDN schema
        # exists for this event) — manually adding a site here lets you keep
        # a checklist of squadron construction projects before you've been.
        colon_card = QFrame()
        colon_card.setStyleSheet(_CARD_STYLE)
        self._colon_card = colon_card
        colon_l = QVBoxLayout(colon_card)
        colon_l.setContentsMargins(8, 6, 8, 6)
        colon_l.setSpacing(4)

        colon_hdr = QLabel("COLONISATION CONSTRUCTION — TRACKED SITES")
        colon_hdr.setStyleSheet(_HDR_STYLE)
        self._colon_hdr = colon_hdr
        colon_l.addWidget(colon_hdr)

        colon_note = QLabel(
            "Progress only updates when you personally dock at the site — add one before "
            "visiting to keep a checklist, or it appears automatically once you dock there."
        )
        colon_note.setWordWrap(True)
        colon_note.setStyleSheet("color:#9aa4b0; font-size:11px; background:transparent; border:none;")
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
        self._depot_table.setStyleSheet(_TABLE_STYLE)
        dh = self._depot_table.horizontalHeader()
        dh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        dh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for c in (2, 3, 4, 5):
            dh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self._depot_table.cellClicked.connect(self._on_depot_cell_clicked)
        self._depot_table.setMaximumHeight(160)
        colon_l.addWidget(self._depot_table)

        root.addWidget(colon_card)

        # ── Colonisation candidates — nearby unpopulated systems ────────────
        cand_card = QFrame()
        cand_card.setStyleSheet(_CARD_STYLE)
        cand_l = QVBoxLayout(cand_card)
        cand_l.setContentsMargins(8, 6, 8, 6)
        cand_l.setSpacing(4)

        cand_hdr = QLabel("COLONISATION CANDIDATES — NEAR CURRENT SYSTEM")
        cand_hdr.setStyleSheet(_HDR_STYLE)
        cand_l.addWidget(cand_hdr)

        self._candidates_status_label = QLabel("Waiting for current system…")
        self._candidates_status_label.setWordWrap(True)
        self._candidates_status_label.setStyleSheet("color:#9aa4b0; font-size:11px; background:transparent; border:none;")
        cand_l.addWidget(self._candidates_status_label)

        self._candidates_table = QTableWidget()
        self._candidates_table.setColumnCount(3)
        self._candidates_table.setHorizontalHeaderLabels(["System", "Dist (ly)", "Via"])
        self._candidates_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._candidates_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._candidates_table.verticalHeader().setVisible(False)
        self._candidates_table.setAlternatingRowColors(True)
        self._candidates_table.setStyleSheet(
            "QTableWidget { background:#080f18; alternate-background-color:#0a1520;"
            " gridline-color:#1e3a5a; border:1px solid #1e3a5a; }"
            "QHeaderView::section { background:#0d1a2a; color:#888888; border:none;"
            " padding:3px; font-size:12px; font-weight:bold; letter-spacing:1px; }"
        )
        cch = self._candidates_table.horizontalHeader()
        cch.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        cch.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._candidates_table.setMaximumHeight(160)
        cand_l.addWidget(self._candidates_table)

        check_hdr = QLabel("CHECK ANY SYSTEM — NOT LIMITED TO YOUR CURRENT LOCATION")
        check_hdr.setStyleSheet("color:#9aa4b0; font-size:10px; font-weight:bold; letter-spacing:1px; background:transparent; border:none;")
        cand_l.addWidget(check_hdr)

        check_row = QHBoxLayout()
        self._check_system_edit = QLineEdit()
        self._check_system_edit.setPlaceholderText("System name — anywhere in the galaxy")
        self._check_system_edit.setStyleSheet("background:#0a1520; color:#c8c8c8; border:1px solid #1e3a5a;")
        check_btn = QPushButton("Check")
        check_btn.setStyleSheet(_BTN_STYLE)
        check_btn.clicked.connect(self._on_check_clicked)
        check_row.addWidget(self._check_system_edit, 1)
        check_row.addWidget(check_btn)
        cand_l.addLayout(check_row)

        self._check_result_label = QLabel("")
        self._check_result_label.setWordWrap(True)
        self._check_result_label.setStyleSheet("background:transparent; border:none;")
        cand_l.addWidget(self._check_result_label)

        cand_caveat = QLabel(
            "Advisory only — based on EDSM's crowdsourced population data, which can lag "
            "real-time changes. Confirms what's in range, not that you're currently at a "
            "valid Colonisation Contact."
        )
        cand_caveat.setWordWrap(True)
        cand_caveat.setStyleSheet("color:#9aa4b0; font-size:11px; background:transparent; border:none;")
        cand_l.addWidget(cand_caveat)

        root.addWidget(cand_card)
        root.addStretch(1)

    def refresh(self, state) -> None:
        self._last_state = state
        self._refresh_depots(state)

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
        any_in_progress = False
        any_complete = False
        for row, d in enumerate(self._depots):
            progress = d.get("progress")
            if d.get("complete"):
                status_text, status_color = "Complete", "#6BCB77"
                any_complete = True
            elif isinstance(progress, (int, float)):
                status_text, status_color = "In Progress", "#FFD93D"
                any_in_progress = True
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

        # Card reads as "in progress" (yellow) while any site is actively
        # under construction, "done" (green) once everything tracked is
        # complete and nothing is still building, and stays the neutral
        # default when there's nothing tracked yet or every site is
        # untouched — no status to call out either way.
        if any_in_progress:
            variant = "yellow"
        elif any_complete and self._depots:
            variant = "green"
        else:
            variant = "blue"
        self._colon_card.setStyleSheet(_card_style(variant))
        self._colon_hdr.setStyleSheet(_hdr_style(variant))

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

    # ── Colonisation candidates ─────────────────────────────────────────

    def set_colonisation_candidates(self, system_name: str, result: dict) -> None:
        candidates = result.get("candidates") or []
        center_populated = result.get("center_populated")
        lookup_failed = bool(result.get("lookup_failed"))

        self._colonisation_candidates = candidates
        self._colonisation_candidates_system = system_name

        self._candidates_table.setRowCount(len(candidates))
        for row, c in enumerate(candidates):
            name_item = QTableWidgetItem(c.get("name") or "—")
            dist_item = QTableWidgetItem(f"{c.get('distance_ly', 0):.1f}")
            dist_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            via = c.get("via")
            via_item = QTableWidgetItem(f"colony: {via}" if via else "current system")
            self._candidates_table.setItem(row, 0, name_item)
            self._candidates_table.setItem(row, 1, dist_item)
            self._candidates_table.setItem(row, 2, via_item)

        if lookup_failed:
            self._candidates_status_label.setText("Lookup failed — EDSM unreachable.")
        elif center_populated is None and not candidates:
            self._candidates_status_label.setText(f"{system_name} not found in EDSM.")
        elif not candidates:
            self._candidates_status_label.setText(
                f"No unpopulated systems found within 15 ly of {system_name}."
            )
        elif center_populated is False:
            self._candidates_status_label.setText(
                f"Your current system ({system_name}) is unpopulated — these systems are nearby "
                "but not verified eligible. Use Check below to confirm a specific one."
            )
        else:
            self._candidates_status_label.setText(f"Near {system_name}:")

    def _on_check_clicked(self) -> None:
        system_name = self._check_system_edit.text().strip()
        if not system_name:
            return
        self._check_result_label.setText("Checking…")
        self._check_result_label.setStyleSheet("color:#888888; background:transparent; border:none;")
        self.eligibility_check_requested.emit(system_name)

    def set_eligibility_check_result(self, result: dict) -> None:
        eligible = result.get("eligible")
        reason = result.get("reason") or ""
        if eligible is True:
            color = "#6BCB77"
            prefix = "✓ Eligible — "
        elif eligible is False:
            color = "#FF6B6B"
            prefix = "✗ Not eligible — "
        else:
            color = "#FFB347"
            prefix = "⚠ "
        self._check_result_label.setStyleSheet(f"color:{color}; background:transparent; border:none;")
        self._check_result_label.setText(f"{prefix}{reason}")
