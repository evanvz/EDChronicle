"""Non-modal "System Design" window: phased build plan for one claimable system, from the hub's body details.
The hub fetch runs on a worker thread; the plan itself is edc.core.colonisation_design.plan_system."""
from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtCore import Qt, QThread
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QRadioButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from edc.core.colonisation_design import plan_system
from edc.core.eddatahub_client import fetch_colonisation_system
from edc.ui.panels.colonisation_finder_dialog import _INPUT_STYLE, _TABLE_STYLE, _Worker

_HINT = "Find the flag in the system map's Architect View"
_FOOTER = ("Sources (community-reported, not official): CMDR Dubior's Advanced ED Colonization Guide (ref. 2026-08-11, read 2026-10-30); "
           "Colonization 101 (CMDR PhoenixBlue0, read 2026-10-30); DaftMav Service Unlocks flowchart (read 2026-10-30).\n"
           "Controlling faction = the faction controlling the station you buy the claim at.")
_GREY = "color:#9aa4b0; font-size:13px;"
_RED = "color:#ff6b6b; font-weight:bold; font-size:13px;"
_LABEL = "color:#c8c8c8; font-size:12px;"


class ColonisationDesignDialog(QDialog):
    def __init__(self, parent, hub_url: str, id64: int, name: str):
        super().__init__(parent)
        self.setStyleSheet("QDialog { background:#080f18; color:#c8c8c8; }")
        self.setWindowTitle(f"Colonisation — Design: {name}")
        self.resize(900, 560)
        self.hub_url, self.id64 = hub_url, id64
        self._threads: list = []  # (QThread, _Worker) pairs, kept referenced until finished
        self._system: Optional[dict] = None

        root = QVBoxLayout(self)
        row = QHBoxLayout()
        lbl = QLabel("Primary slot body")
        lbl.setStyleSheet(_LABEL)
        self._combo = QComboBox()
        self._combo.setStyleSheet(_INPUT_STYLE)
        self._combo.setToolTip(_HINT)
        self._combo.addItem("Pick the primary slot body…", None)
        self._combo.setEnabled(False)
        self._combo.currentIndexChanged.connect(self._replan)
        self._solo = QRadioButton("Solo")
        self._group = QRadioButton("Group")
        self._solo.setChecked(True)
        for r in (self._solo, self._group):
            r.setStyleSheet(_LABEL)
            r.toggled.connect(self._replan)
        row.addWidget(lbl)
        row.addWidget(self._combo, 1)
        row.addWidget(self._solo)
        row.addWidget(self._group)
        root.addLayout(row)

        self._hint = QLabel(_HINT)
        self._hint.setStyleSheet("color:#9aa4b0; font-size:11px;")
        root.addWidget(self._hint)

        self._banner = QLabel("")
        self._banner.setWordWrap(True)
        self._banner.setStyleSheet("color:#ff6b6b; font-weight:bold; font-size:13px;")
        self._banner.setVisible(False)
        root.addWidget(self._banner)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["Step", "Body", "Unlocks", "Needs"])
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.setWordWrap(True)
        self._table.setStyleSheet(_TABLE_STYLE)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self._table, 1)

        self._warnings = QLabel("")
        self._warnings.setWordWrap(True)
        self._warnings.setStyleSheet("color:#e0b040; font-size:12px;")
        root.addWidget(self._warnings)

        footer = QLabel(_FOOTER)
        footer.setWordWrap(True)
        footer.setStyleSheet("color:#7a8694; font-size:11px;")
        root.addWidget(footer)

        self.load(id64, name)

    def load(self, id64: int, name: str) -> None:
        """Point the window at a system; a still-running fetch for the previous one is ignored when it lands."""
        self.id64, self._system = id64, None
        self.setWindowTitle(f"Colonisation — Design: {name}")
        while self._combo.count() > 1:
            self._combo.removeItem(1)
        self._combo.setCurrentIndex(0)
        self._combo.setEnabled(False)
        self._table.setRowCount(0)
        self._warnings.setText("")
        self._banner.setText("Loading…")
        self._banner.setStyleSheet(_GREY)
        self._banner.setVisible(True)
        url = self.hub_url
        self._start(lambda: (id64, fetch_colonisation_system(url, id64)), self._on_loaded)

    # ── threading (same pattern as the finder) ─────────────────────────
    def _start(self, fn: Callable, slot: Callable) -> None:
        self._threads = [p for p in self._threads if not p[0].isFinished()]
        thread, worker = QThread(), _Worker(fn)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(slot)
        worker.finished.connect(thread.quit, Qt.ConnectionType.DirectConnection)
        self._threads.append((thread, worker))
        thread.start()

    def stop(self) -> None:
        """App shutdown only (blocks): a QThread destroyed while running is a Qt fatal."""
        for thread, _ in self._threads:
            thread.quit()
        for thread, _ in self._threads:
            thread.wait(10000)

    def closeEvent(self, event) -> None:
        for thread, _ in self._threads:  # never wait on the GUI thread; the threads stay referenced until finished
            thread.quit()
        super().closeEvent(event)

    # ── data ───────────────────────────────────────────────────────────
    def _on_loaded(self, result) -> None:
        if result is None or result[0] != self.id64:
            return
        system = result[1]
        if not system:
            self._banner.setText("EDDataHub not reachable")
            self._banner.setStyleSheet(_RED)
            return
        self._system = system
        self._banner.setVisible(False)
        bodies = sorted(system.get("bodies") or [], key=lambda b: b.get("distance_ls") or 0)
        sysname = system.get("name") or ""
        roots = {b.get("body_id"): b for b in bodies}
        groups: dict = {}
        for b in bodies:
            groups.setdefault(b.get("cluster"), []).append(b)

        def label(b, indent):
            name = b.get("name") or f"Body {b.get('body_id')}"
            return ("      " if indent else "") + (name.removeprefix(sysname).strip() or name)

        for cl, members in groups.items():
            root_b = roots.get(cl)
            ordered = ([root_b] if root_b in members else []) + [b for b in members if b is not root_b]
            for b in ordered:
                self._combo.addItem(label(b, cl is not None and b is not root_b), b.get("name"))
        self._combo.setEnabled(True)
        self._replan()

    def _replan(self, *_) -> None:
        if self._system is None:
            return
        primary = self._combo.currentData()
        self._table.setRowCount(0)
        self._warnings.setText("")
        if primary is None:
            has_details = plan_system(self._system, "", False)["poor"] != "Hub has no body details yet"
            self._banner.setText("" if has_details else "Hub has no body details yet")
            self._banner.setStyleSheet(_RED)
            self._banner.setVisible(not has_details)
            return
        plan = plan_system(self._system, primary, self._group.isChecked())
        self._banner.setStyleSheet(_RED)
        if plan["poor"]:
            self._banner.setText(f"Poor pick: {plan['poor']}" if plan["poor"] != "Hub has no body details yet"
                                 else plan["poor"])
            self._banner.setVisible(True)
            return
        self._banner.setVisible(False)
        self._table.setRowCount(len(plan["steps"]))
        for r, s in enumerate(plan["steps"]):
            for c, text in enumerate([s["title"], s["body"], ", ".join(s["unlocks"]), s["needs"] or ""]):
                self._table.setItem(r, c, QTableWidgetItem(text))
        self._table.resizeRowsToContents()
        lines = list(plan["warnings"]) + ([plan["note"]] if plan["note"] else [])
        self._warnings.setText("\n".join(lines))
