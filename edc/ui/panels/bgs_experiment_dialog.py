# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the GNU General Public License v3.0 or later (GPL-3.0-or-later).
# See the LICENSE file in the project root for full terms.

"""BGS Experiment Log window: one tab per squad test system, one row per tick
window (see edc.core.bgs_experiment), plus a Systems tab to add/remove them."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QPushButton,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from edc.core.bgs_experiment import build_rows
from edc.core.system_ticks import infer_system_ticks, merge_ticks
from edc.ui.style import HDR_STYLE, PRIMARY_BUTTON_STYLE, TAB_STYLE, TABLE_STYLE

log = logging.getLogger(__name__)

HISTORY_DAYS = 14
_COLUMNS = ["Tick (UTC)", "INF", "Bounties", "Trade profit", "Exploration", "SINC pts",
            "Influence", "Change", "% of headroom", "Likely max", "Other arrivals", "Other factions", "States"]
_AMBER = "#FFB347"


class _TrafficWorker(QObject):
    """EDSM traffic per test system, off the UI thread (EDSM is rate-gated)."""
    finished = pyqtSignal(dict)  # {system: {"total", "week", "day"} or None}

    def __init__(self, systems):
        super().__init__()
        self._systems = systems

    def run(self):
        from edc.core.edsm_faction_lookup import fetch_system_traffic
        self.finished.emit({name: fetch_system_traffic(name) for name in self._systems})


def _cr(n: int) -> str:
    if not n:
        return ""
    for div, s in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if n >= div:
            return f"{n / div:.3g}{s}"
    return str(n)


def row_cells(r: dict) -> list:
    e = r["effort"]
    infl = "" if r["before"] is None else (
        ("⏳ " if r.get("provisional") else "")
        + f"{r['before'] * 100:.2f}%" + (f" → {r['after'] * 100:.2f}%" if r["after"] is not None
                                         else " → (next tick)" if r["end"] is None else " → no visit since"))
    window = r["start"][5:16].replace("T", " ") + ("" if r["end"] else "  (running)")
    return [window, str(e["tier_score"] or ""), _cr(e["bounties"]), _cr(e["trade_profit"]), _cr(e["exploration"]),
            f"{r['points']:.1f}" if r["points"] else "", infl or "not visited",
            "" if r["change"] is None else f"{r['change']:+.2f}",
            "" if r["share"] is None else f"{r['share']:.1f}%",
            "" if not r["ceiling"] else f"+{r['ceiling'][0]:.1f}–{r['ceiling'][1]:.1f}",
            ("⚠ " if r.get("other_visits") else "") + str(r.get("other_visits", "")),
            ("⚠ " + ", ".join(r["factions_up"]) + " up") if r.get("factions_up") else ("✓" if r["change"] is not None else ""),
            ("⚠ influence changed again 12 h+ after the tick, with no tick listed; " if r.get("unlisted_update")
             else "")
            + (f"tick seen in this system's own readings ({r['inferred_from'][0][5:16].replace('T', ' ')} → "
               f"{r['inferred_from'][1][5:16].replace('T', ' ')}), not listed by tick.edcd.io; "
               if r.get("inferred_from") else "")
            + r["states"]]


class BgsExperimentDialog(QDialog):
    def __init__(self, panel):
        super().__init__(None)
        self._panel = panel
        self.setStyleSheet("QDialog { background:#080f18; color:#c8c8c8; }")
        self.setWindowTitle("BGS Experiment Log")
        self.resize(1100, 560)

        layout = QVBoxLayout(self)
        hdr_row = QHBoxLayout()
        hdr = QLabel("BGS EXPERIMENT LOG — PER-TICK RESULTS IN TEST SYSTEMS")
        hdr.setStyleSheet(HDR_STYLE)
        hdr_row.addWidget(hdr)
        hdr_row.addStretch(1)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)
        hdr_row.addWidget(refresh_btn)
        layout.addLayout(hdr_row)
        note = QLabel(
            "Each row is one tick window: your effort for the squad faction in that system, its SINC points, the "
            "influence seen during the window and after the next tick. Jump into every test system once after "
            "each tick so the level gets recorded. '% of headroom' = change ÷ (100% − influence); typical best "
            "days are 6–8%. ⏳ = provisional: read under 12 h after a tick, when a system may not have updated "
            "yet (SINC BGS protocol) — a later visit or EDDN reading replaces it. Amber rows are possibly "
            "contaminated: another commander was seen (EDDN, minus your own uploads), another faction gained over "
            "the tick, or influence changed again 12 h+ after a tick with no tick listed. "
            "'Other arrivals' counts EDDN jumps/dockings, not commanders: EDDN hides who uploaded, so one "
            "commander jumping in 19 times shows as 19.")
        note.setWordWrap(True)
        note.setStyleSheet("color:#9aa4b0; font-size:11px;")
        layout.addWidget(note)

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(TAB_STYLE)
        layout.addWidget(self._tabs, 1)
        self._tables: dict = {}
        self._traffic: dict = {}
        self._traffic_labels: dict = {}
        self._traffic_thread = None
        self._traffic_worker = None

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()
        self._start_traffic_lookup()

    def _start_traffic_lookup(self) -> None:
        systems = self._panel._repo.get_experiment_systems()
        if not systems or (self._traffic_thread and self._traffic_thread.isRunning()):
            return
        self._traffic_worker = _TrafficWorker(systems)
        if self._traffic_thread is not None:
            self._traffic_thread.wait()  # old-thread teardown race -- see main_window.py's _start_spansh_enrich docstring
        self._traffic_thread = QThread()
        self._traffic_worker.moveToThread(self._traffic_thread)
        self._traffic_thread.started.connect(self._traffic_worker.run)
        self._traffic_worker.finished.connect(self._on_traffic)
        self._traffic_worker.finished.connect(self._traffic_thread.quit, Qt.ConnectionType.DirectConnection)
        self._traffic_thread.start()

    def _on_traffic(self, traffic: dict) -> None:
        self._traffic = traffic
        for name, label in self._traffic_labels.items():
            label.setText(self._traffic_text(name))

    def _traffic_text(self, name: str) -> str:
        t = self._traffic.get(name)
        if name not in self._traffic:
            return "EDSM traffic: checking…"
        return ("EDSM traffic: unavailable" if not t else
                f"EDSM traffic (EDSM users only): {t.get('day', 0)} today, {t.get('week', 0)} this week")

    def _faction(self):
        return getattr(self._panel, "_faction_name", None) or self._panel._repo.get_squadron_faction_name()

    def refresh(self) -> None:
        repo = self._panel._repo
        current = self._tabs.tabText(self._tabs.currentIndex()) if self._tabs.count() else ""
        self._tabs.clear()
        self._tables = {}
        self._traffic_labels = {}
        faction = self._faction()
        systems = repo.get_experiment_systems()
        since = (datetime.now(timezone.utc) - timedelta(days=HISTORY_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
        ticks = repo.get_bgs_ticks(since=since)
        addresses = repo.get_system_addresses_for_names(systems) if systems else {}
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for name in systems:
            addr = addresses.get(name)
            page = QWidget()
            pl = QVBoxLayout(page)
            if addr is None or not faction:
                pl.addWidget(QLabel(f"{name}: not visited yet — jump in once so the app knows it."
                                    if addr is None else "Squadron faction not known yet."))
                self._tabs.addTab(page, name)
                continue
            sys_ticks, inferred = merge_ticks(ticks, infer_system_ticks(repo.get_system_readings(addr)))
            sys_ticks = [t for t in sys_ticks if t >= since]
            rows = build_rows(sys_ticks, repo.get_influence_readings(addr, faction),
                              lambda s, e, a=addr: repo.get_faction_activity_between(a, faction, s, e), now=now,
                              visits=repo.get_bgs_visits(addr), faction_readings=repo.get_all_faction_readings(addr),
                              faction=faction, population=repo.get_system_population(addr), inferred=inferred)
            table = self._fill_table(rows)
            self._tables[name] = (table, rows)
            copy_btn = QPushButton("Copy table")
            copy_btn.setStyleSheet(PRIMARY_BUTTON_STYLE)
            copy_btn.clicked.connect(lambda _=False, n=name: self._copy(n))
            top = QHBoxLayout()
            extra = sum(1 for t in inferred if t >= since)
            top.addWidget(QLabel(f"{faction} in {name} — last {HISTORY_DAYS} days, {len(sys_ticks)} ticks"
                                 + (f" ({extra} seen only in this system's own readings)" if extra else "")))
            top.addStretch(1)
            traffic = QLabel(self._traffic_text(name))
            traffic.setStyleSheet("color:#9aa4b0;")
            self._traffic_labels[name] = traffic
            top.addWidget(traffic)
            top.addWidget(copy_btn)
            pl.addLayout(top)
            pl.addWidget(table, 1)
            self._tabs.addTab(page, name)
        self._tabs.addTab(self._systems_page(systems), "Systems")
        for i in range(self._tabs.count()):
            if self._tabs.tabText(i) == current:
                self._tabs.setCurrentIndex(i)

    def _fill_table(self, rows: list) -> QTableWidget:
        t = QTableWidget(len(rows), len(_COLUMNS))
        t.setHorizontalHeaderLabels(_COLUMNS)
        t.setStyleSheet(TABLE_STYLE)
        t.verticalHeader().setVisible(False)
        t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for i, r in enumerate(rows):
            for c, text in enumerate(row_cells(r)):
                item = QTableWidgetItem(text)
                if r.get("contaminated"):
                    item.setForeground(QColor(_AMBER))
                    item.setToolTip("Possibly contaminated: another commander was seen here, or another faction "
                                    "gained over this tick — someone else may have moved influence.")
                elif c == 8 and r["share"] is not None:
                    item.setForeground(QColor("#6BCB77" if r["share"] >= 6 else "#c8c8c8"))
                t.setItem(i, c, item)
        h = t.horizontalHeader()
        for c in range(len(_COLUMNS)):
            h.setSectionResizeMode(c, QHeaderView.ResizeMode.Stretch if c in (6, 11, 12)
                                   else QHeaderView.ResizeMode.ResizeToContents)
        return t

    def _copy(self, name: str) -> None:
        """Plain-text table in a code block, to paste into the squad's channel."""
        _table, rows = self._tables[name]
        lines = [" | ".join(_COLUMNS)] + [" | ".join(row_cells(r)) for r in rows]
        QApplication.clipboard().setText(f"{name}\n```\n" + "\n".join(lines) + "\n```")

    def _systems_page(self, systems: list) -> QWidget:
        page = QWidget()
        pl = QVBoxLayout(page)
        pl.addWidget(QLabel("Test systems (the squad faction's influence is logged in each, per tick):"))
        self._system_list = QListWidget()
        self._system_list.addItems(systems)
        pl.addWidget(self._system_list, 1)
        row = QHBoxLayout()
        self._system_edit = QLineEdit()
        self._system_edit.setPlaceholderText("System name, e.g. ICZ XZ-P b5-1")
        self._system_edit.returnPressed.connect(self._add_system)
        add_btn = QPushButton("Add")
        add_btn.clicked.connect(self._add_system)
        remove_btn = QPushButton("Remove selected")
        remove_btn.clicked.connect(self._remove_system)
        for w in (self._system_edit, add_btn, remove_btn):
            row.addWidget(w)
        pl.addLayout(row)
        return page

    def _add_system(self) -> None:
        name = self._system_edit.text().strip()
        if name:
            self._panel._repo.add_experiment_system(name)
            self.refresh()

    def _remove_system(self) -> None:
        item = self._system_list.currentItem()
        if item:
            self._panel._repo.remove_experiment_system(item.text())
            self.refresh()
