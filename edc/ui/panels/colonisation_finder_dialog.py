"""Non-modal "Find Systems" window: claimable systems from EDDataHub, ranked by
port types and economies. Every hub/Spansh/DB call runs on a worker thread."""
from __future__ import annotations

import logging
from datetime import date
from typing import Callable, Optional

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
    QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from edc.core.colonisation_eligibility import _spansh_claimed
from edc.core.eddatahub_client import fetch_colonisation_search, fetch_colonisation_system
from edc.ui.panels.market_panel import _NumericTableWidgetItem
from edc.ui.style import PRIMARY_BUTTON_STYLE as _BTN_STYLE, TABLE_STYLE as _TABLE_STYLE

log = logging.getLogger(__name__)

_INPUT_STYLE = "background:#0a1520; color:#c8c8c8; border:1px solid #1e3a5a;"
_PORT_TYPES = ["Orbital", "Asteroid", "Surface"]
_ECONOMIES = ["Agriculture", "Extraction", "HighTech", "Industrial", "Military", "Refinery", "Terraforming",
              "Tourism"]


def _load_squad_ids(db_path) -> list:
    from persistence.database import Database
    from persistence.repository import Repository
    db = Database(db_path)
    try:
        overview = Repository(db).get_player_faction_overview() or {}
        return [s["system_address"] for s in overview.get("systems", []) if s.get("system_address")]
    finally:
        db.close()


def _load_coords(db_path, name: str):
    from persistence.database import Database
    from persistence.repository import Repository
    db = Database(db_path)
    try:
        return Repository(db).get_system_coords_for_names([name]).get(name)
    finally:
        db.close()


class _Worker(QObject):
    finished = pyqtSignal(object)

    def __init__(self, fn: Callable):
        super().__init__()
        self._fn = fn

    def run(self):
        try:
            result = self._fn()
        except Exception:
            log.exception("Colonisation finder worker failed")
            result = None
        self.finished.emit(result)


def _age_days(dump_date) -> str:
    try:
        return f"{(date.today() - date.fromisoformat(str(dump_date)[:10])).days} d"
    except (TypeError, ValueError):
        return ""


def _num(text: str, value) -> QTableWidgetItem:
    return _NumericTableWidgetItem(text, value if value is not None else float("inf"))


class ColonisationFinderDialog(QDialog):
    def __init__(self, panel, hub_url: str):
        super().__init__(panel)
        self.setStyleSheet("QDialog { background:#080f18; color:#c8c8c8; }")
        self.setWindowTitle("Colonisation — Find Systems")
        self.resize(980, 640)
        self._panel = panel
        self.hub_url = hub_url
        self._threads: list = []  # (QThread, _Worker) pairs, kept referenced until finished
        self._detail_id: Optional[int] = None

        state = getattr(panel, "_last_state", None)
        root = QVBoxLayout(self)

        row = QHBoxLayout()
        self._centre = QLineEdit(getattr(state, "system", "") or "")
        self._centre.setPlaceholderText("Centre system")
        self._centre.setStyleSheet(_INPUT_STYLE)
        self._radius = QSpinBox()
        self._radius.setRange(10, 200)
        self._radius.setValue(100)
        self._radius.setSuffix(" ly")
        self._port = QComboBox()
        self._port.addItems(["Any"] + _PORT_TYPES)
        self._economy = QComboBox()
        self._economy.addItems(["Any"] + _ECONOMIES)
        self._near_chk = QCheckBox("Near squad")
        self._near_ly = QSpinBox()
        self._near_ly.setRange(1, 200)
        self._near_ly.setValue(30)
        self._near_ly.setSuffix(" ly")
        self._search_btn = QPushButton("Search")
        self._search_btn.setStyleSheet(_BTN_STYLE)
        self._search_btn.clicked.connect(self._on_search)
        for w in (self._radius, self._port, self._economy, self._near_ly):
            w.setStyleSheet(_INPUT_STYLE)
        row.addWidget(self._centre, 1)
        for w in (self._radius, self._port, self._economy, self._near_chk, self._near_ly, self._search_btn):
            row.addWidget(w)
        root.addLayout(row)

        self._status = QLabel("")
        self._status.setStyleSheet("color:#9aa4b0; font-size:11px;")
        root.addWidget(self._status)

        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Filter by system…")
        self._filter.setClearButtonEnabled(True)
        self._filter.setStyleSheet(_INPUT_STYLE)
        self._filter.textChanged.connect(self._apply_filter)
        root.addWidget(self._filter)

        self._table = QTableWidget(0, 9)
        self._table.setHorizontalHeaderLabels(
            ["System", "Dist (ly)", "To squad (ly)", "Score", "Port types", "Economies", "Bodies", "Data age", "Claim from"])
        self._table.horizontalHeaderItem(8).setToolTip("Nearest populated system within 15 ly: claim from a station there")
        self._table.horizontalHeaderItem(3).setToolTip(
            "Score = 10 × port types + economies (rules: Update 3 body economies)")
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(20)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet(_TABLE_STYLE)
        self._table.setSortingEnabled(True)
        self._table.sortItems(3, Qt.SortOrder.DescendingOrder)  # default indicator is System, would reorder the hub's ranking
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.cellClicked.connect(self._on_cell_clicked)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        root.addWidget(self._table, 3)

        self._spansh = QLabel("")
        self._spansh.setStyleSheet("color:#c8c8c8; font-size:12px;")
        self._spansh.setWordWrap(True)  # the claim-from list can name 20+ systems
        root.addWidget(self._spansh)

        self._bodies = QTableWidget(0, 6)
        self._bodies.setHorizontalHeaderLabels(["Body", "Type", "Landable", "Dist (ls)", "Port types", "Economies"])
        self._bodies.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._bodies.verticalHeader().setVisible(False)
        self._bodies.verticalHeader().setDefaultSectionSize(20)
        self._bodies.setAlternatingRowColors(True)
        self._bodies.setStyleSheet(_TABLE_STYLE)
        self._bodies.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._bodies.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self._bodies, 2)

    # ── threading ──────────────────────────────────────────────────────
    def _start(self, fn: Callable, slot: Callable) -> None:
        self._threads = [p for p in self._threads if not p[0].isFinished()]  # never wait on the GUI thread
        thread, worker = QThread(), _Worker(fn)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(slot)
        worker.finished.connect(thread.quit, Qt.ConnectionType.DirectConnection)
        self._threads.append((thread, worker))
        thread.start()

    def stop(self) -> None:
        """App shutdown: a QThread destroyed while running is a Qt fatal."""
        for thread, _ in self._threads:
            thread.quit()
        for thread, _ in self._threads:
            thread.wait(10000)

    # ── search ─────────────────────────────────────────────────────────
    def _on_search(self) -> None:
        name = self._centre.text().strip()
        if not name:
            self._status.setText("Enter a centre system")
            return
        state = getattr(self._panel, "_last_state", None)
        here = None
        if (state is not None and (getattr(state, "system", "") or "").lower() == name.lower()
                and None not in (getattr(state, "system_x", None), getattr(state, "system_y", None),
                                 getattr(state, "system_z", None))):
            here = (state.system_x, state.system_y, state.system_z)
        db_path = self._panel._repo.db.db_path
        port = [] if self._port.currentIndex() == 0 else [self._port.currentText()]
        eco = [] if self._economy.currentIndex() == 0 else [self._economy.currentText()]
        near = self._near_chk.isChecked()
        near_ly = float(self._near_ly.value())
        radius = float(self._radius.value())
        url = self.hub_url

        def work():
            xyz = here or _load_coords(db_path, name)
            if xyz is None:
                return "Unknown system — jump there or pick a known one"
            ids = _load_squad_ids(db_path) if near else []
            rows = fetch_colonisation_search(url, xyz[0], xyz[1], xyz[2], radius, port, eco, ids[:200],
                                             near_ly if near else None)
            return rows if rows is not None else "EDDataHub not reachable"

        self._search_btn.setEnabled(False)
        self._status.setText("Searching…")
        self._start(work, self._on_search_done)

    def _on_search_done(self, result) -> None:
        self._search_btn.setEnabled(True)
        if not isinstance(result, list):
            self._status.setText(result or "Search failed")
            return
        self._status.setText(f"{len(result)} claimable system(s)")
        self._detail_id = None
        self._spansh.setText("")
        self._bodies.setRowCount(0)
        self._table.setSortingEnabled(False)  # sorting while filling scrambles the row indexes
        self._table.setRowCount(len(result))
        for r, row in enumerate(result):
            ports = ", ".join(row.get("port_types") or []) if row.get("body_count") else "unknown"
            first = QTableWidgetItem(row["name"])
            first.setData(Qt.ItemDataRole.UserRole, row["id64"])
            squad = row.get("to_squad_ly")
            claim = row.get("claim_from")
            items = [
                first,
                _num("" if row.get("distance_ly") is None else f"{row['distance_ly']:.1f}", row.get("distance_ly")),
                _num("" if squad is None else f"{squad:.1f}", squad),
                _num(str(row.get("score", 0)), row.get("score", 0)),
                QTableWidgetItem(ports),
                QTableWidgetItem(", ".join(row.get("economies") or [])),
                _num(str(row.get("body_count", 0)), row.get("body_count", 0)),
                QTableWidgetItem(_age_days(row.get("dump_date"))),
                QTableWidgetItem(f"{claim['name']} ({claim['ly']:.1f} ly)" if claim else ""),
            ]
            for c, item in enumerate(items):
                self._table.setItem(r, c, item)
        self._table.setSortingEnabled(True)
        self._apply_filter()

    def _apply_filter(self) -> None:
        needle = self._filter.text().strip().lower()
        for r in range(self._table.rowCount()):
            self._table.setRowHidden(r, needle not in self._table.item(r, 0).text().lower())

    # ── selection ──────────────────────────────────────────────────────
    def _on_cell_clicked(self, row: int, col: int) -> None:
        if col == 0:
            QApplication.clipboard().setText(self._table.item(row, 0).text())

    def _on_selection_changed(self) -> None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return
        item = self._table.item(rows[0].row(), 0)
        id64, name = item.data(Qt.ItemDataRole.UserRole), item.text()
        self._detail_id = id64
        self._spansh.setText("Spansh: checking…")
        self._bodies.setRowCount(0)
        url = self.hub_url

        def work():
            return id64, fetch_colonisation_system(url, id64), _spansh_claimed(name)

        self._start(work, self._on_detail_done)

    def _on_detail_done(self, result) -> None:
        if result is None or result[0] != self._detail_id:
            return
        _, system, claimed = result
        claim = ", ".join(f"{c['name']} ({c['ly']:.1f} ly)" for c in (system or {}).get("claim_from") or [])
        self._spansh.setText("Spansh: " + {True: "claimed", False: "free", None: "unknown"}[claimed]
                             + (f"    Claim from: {claim}" if claim else ""))
        bodies = (system or {}).get("bodies") or []
        self._bodies.setRowCount(len(bodies))
        for r, b in enumerate(bodies):
            dist = b.get("distance_ls")
            cells = [b.get("name", ""), b.get("sub_type", ""), "Yes" if b.get("landable") else "No",
                     "" if dist is None else f"{dist:,.0f}", ", ".join(b.get("port_types") or []),
                     ", ".join(b.get("economies") or [])]
            for c, text in enumerate(cells):
                self._bodies.setItem(r, c, QTableWidgetItem(text))
