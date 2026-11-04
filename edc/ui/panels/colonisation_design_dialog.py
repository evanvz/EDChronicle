"""Non-modal "System Design" window: phased build plan for one claimable system, from the hub's body details.
The hub fetch runs on a worker thread; the plan itself is edc.core.colonisation_design.plan_system."""
from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtCore import Qt, QThread
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QRadioButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from edc.core.colonisation_design import plan_system
from edc.core.colonisation_planner import TYPE_NAMES, TYPES, plan as plan_by_type, slot_table
from edc.core.eddatahub_client import fetch_colonisation_system, put_colonisation_mark, put_colonisation_slots
from edc.core.raven_colonial import get_system_slots
from edc.ui.panels.colonisation_finder_dialog import _BTN_STYLE, _INPUT_STYLE, _TABLE_STYLE, _Worker, mark_text

_HINT = "Find the flag in the system map's Architect View"
_FOOTER = ("Sources (community-reported, not official): CMDR Dubior's Advanced ED Colonization Guide (ref. 2026-08-11, read 2026-10-30); "
           "Colonization 101 (CMDR PhoenixBlue0, read 2026-10-30); DaftMav Service Unlocks flowchart (read 2026-10-30).\n"
           "Official: Frontier Trailblazers Update 3.3 notes, service activation (read 2026-10-31). Construction points: "
           "ED wiki System Colonisation (rev. 2026-10-26), gaborauth ED Colonisation Planner (read 2026-10-31).\n"
           "Controlling faction = the faction controlling the station you buy the claim at.")
_GREY = "color:#9aa4b0; font-size:13px;"
_RED = "color:#ff6b6b; font-weight:bold; font-size:13px;"
_AMBER = "color:#FFB347; font-weight:bold; font-size:13px;"
# hub service score spread, 2026-11-03: median 16, top quarter from 37
_SCORE_BANDS = ((16, "bottom half"), (37, "middle"))
_LABEL = "color:#c8c8c8; font-size:12px;"
_SOURCES = {"entered": "entered", "raven": "Raven", "est": "est.", None: "?"}
_NO_SLOTS = "No slot counts yet: enter them to plan by type"


class ColonisationDesignDialog(QDialog):
    def __init__(self, parent, hub_url: str, id64: int, name: str):
        super().__init__(parent)
        self.setStyleSheet("QDialog { background:#080f18; color:#c8c8c8; }")
        self.setWindowTitle(f"Colonisation — Design: {name}")
        self.resize(900, 820)
        self.hub_url, self.id64 = hub_url, id64
        self._threads: list = []  # (QThread, _Worker) pairs, kept referenced until finished
        self._system: Optional[dict] = None
        self._raven: Optional[dict] = None
        self._loaded_slots: dict = {}  # body_id: (orbital, surface) as last filled, so Save sends only changed rows

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
        self._kind = QComboBox()
        self._kind.setStyleSheet(_INPUT_STYLE)
        self._kind.addItem("Template", None)
        for t in TYPES:
            self._kind.addItem(TYPE_NAMES[t], t)
        self._kind.currentIndexChanged.connect(self._replan)
        row.addWidget(self._solo)
        row.addWidget(self._group)
        row.addWidget(self._kind)
        root.addLayout(row)

        self._hint = QLabel(_HINT)
        self._hint.setStyleSheet("color:#9aa4b0; font-size:11px;")
        root.addWidget(self._hint)

        self._banner = QLabel("")
        self._banner.setWordWrap(True)
        self._banner.setStyleSheet("color:#ff6b6b; font-weight:bold; font-size:13px;")
        self._banner.setVisible(False)
        root.addWidget(self._banner)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["Step", "Body", "Unlocks", "Needs", "Points"])
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.setWordWrap(True)
        self._table.setStyleSheet(_TABLE_STYLE)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self._table, 1)

        self._outcome = QLabel("")
        self._outcome.setWordWrap(True)
        self._outcome.setStyleSheet(_LABEL)
        root.addWidget(self._outcome)

        self._warnings = QLabel("")
        self._warnings.setWordWrap(True)
        self._warnings.setStyleSheet("color:#e0b040; font-size:12px;")
        root.addWidget(self._warnings)

        # Free slot counts per body: entered on the hub > Raven Colonial > hub ground-slot estimate; Save writes the hub
        self._slots = QTableWidget(0, 4)
        self._slots.setHorizontalHeaderLabels(["Body", "Orbital", "Surface", "Source"])
        self._slots.verticalHeader().setVisible(False)
        self._slots.setAlternatingRowColors(True)
        self._slots.setStyleSheet(_TABLE_STYLE)
        self._slots.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._slots.horizontalHeader().setStretchLastSection(True)
        self._slots.itemChanged.connect(self._replan)
        self._edit_triggers = self._slots.editTriggers()  # restored after a save, which locks the grid
        root.addWidget(self._slots, 1)
        slots_row = QHBoxLayout()
        self._save_slots_btn = QPushButton("Save slots")
        self._save_slots_btn.setStyleSheet(_BTN_STYLE)
        self._save_slots_btn.setEnabled(False)
        self._save_slots_btn.clicked.connect(self._save_slots)
        self._slots_lbl = QLabel("")
        self._slots_lbl.setStyleSheet(_LABEL)
        slots_row.addWidget(self._save_slots_btn)
        slots_row.addWidget(self._slots_lbl, 1)
        root.addLayout(slots_row)

        # Squad verdict, stored on the hub with the primary body picked above (finder hides "bad" systems)
        mark_row = QHBoxLayout()
        self._note = QLineEdit()
        self._note.setPlaceholderText("Note (e.g. primary on gas giant 3, no moons)")
        self._note.setMaxLength(200)
        self._note.setStyleSheet(_INPUT_STYLE)
        self._mark_btns = {}
        for verdict, text in (("good", "Mark good"), ("bad", "Mark bad"), (None, "Clear mark")):
            b = QPushButton(text)
            b.setStyleSheet(_BTN_STYLE)
            b.setEnabled(False)
            b.clicked.connect(lambda _, v=verdict: self._save_mark(v))
            self._mark_btns[verdict] = b
        mark_row.addWidget(self._note, 1)
        for b in self._mark_btns.values():
            mark_row.addWidget(b)
        root.addLayout(mark_row)
        self._mark_lbl = QLabel("")
        self._mark_lbl.setStyleSheet(_LABEL)
        root.addWidget(self._mark_lbl)
        self.on_marked: Optional[Callable] = None  # (id64, mark or None), set by the finder to update its row

        footer = QLabel(_FOOTER)
        footer.setWordWrap(True)
        footer.setStyleSheet("color:#7a8694; font-size:11px;")
        root.addWidget(footer)

        self.load(id64, name)

    def load(self, id64: int, name: str) -> None:
        """Point the window at a system; a still-running fetch for the previous one is ignored when it lands."""
        self.id64, self._system, self._raven = id64, None, None
        self.setWindowTitle(f"Colonisation — Design: {name}")
        while self._combo.count() > 1:
            self._combo.removeItem(1)
        self._combo.setCurrentIndex(0)
        self._combo.setEnabled(False)
        self._table.setRowCount(0)
        self._slots.setRowCount(0)
        self._slots.setEditTriggers(self._edit_triggers)
        self._save_slots_btn.setEnabled(False)
        self._slots_lbl.setText("")
        self._outcome.setText("")
        self._warnings.setText("")
        self._note.clear()
        self._mark_lbl.setText("")
        for b in self._mark_btns.values():
            b.setEnabled(False)
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
        for b in self._mark_btns.values():
            b.setEnabled(True)
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
        self._fill_slots()
        self._save_slots_btn.setEnabled(True)
        self._show_mark(system.get("mark"))
        self._replan()
        id64 = self.id64
        self._start(lambda: (id64, get_system_slots(sysname)), self._on_raven)

    # ── slot grid ──────────────────────────────────────────────────────
    def _on_raven(self, result) -> None:
        if result is None or result[0] != self.id64 or self._system is None or not result[1]:
            return
        self._raven = result[1]
        edited = {r["body_id"]: r for r in self._grid_slots()
                  if (r["orbital"], r["surface"]) != self._loaded_slots.get(r["body_id"])}
        self._fill_slots()
        self._slots.blockSignals(True)  # edits made before Raven Colonial answered stay, against the new baseline
        for i in range(self._slots.rowCount()):
            r = edited.get(self._slots.item(i, 0).data(Qt.ItemDataRole.UserRole)["body_id"])
            if r:
                self._slots.item(i, 1).setText("" if r["orbital"] is None else str(r["orbital"]))
                self._slots.item(i, 2).setText("" if r["surface"] is None else str(r["surface"]))
        self._slots.blockSignals(False)
        self._replan()

    def _fill_slots(self) -> None:
        sysname = self._system.get("name") or ""
        rows = slot_table(self._system, self._raven)
        self._loaded_slots = {r["body_id"]: (r["orbital"], r["surface"]) for r in rows}
        self._slots.blockSignals(True)
        self._slots.setRowCount(len(rows))
        for i, r in enumerate(rows):
            label = r["name"] or f"Body {r['body_id']}"
            name = QTableWidgetItem(label.removeprefix(sysname).strip() or label)
            name.setData(Qt.ItemDataRole.UserRole, r)
            src = QTableWidgetItem(f"{_SOURCES[r['orbital_source']]} / {_SOURCES[r['surface_source']]}")
            for it in (name, src):
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._slots.setItem(i, 0, name)
            self._slots.setItem(i, 1, QTableWidgetItem("" if r["orbital"] is None else str(r["orbital"])))
            self._slots.setItem(i, 2, QTableWidgetItem("" if r["surface"] is None else str(r["surface"])))
            self._slots.setItem(i, 3, src)
        self._slots.blockSignals(False)

    def _grid_slots(self) -> list:
        def count(r, c):
            t = self._slots.item(r, c).text().strip()
            return int(t) if t.isdigit() else None
        return [{**self._slots.item(r, 0).data(Qt.ItemDataRole.UserRole), "orbital": count(r, 1), "surface": count(r, 2)}
                for r in range(self._slots.rowCount())]

    def _save_slots(self) -> None:
        changed = [r for r in self._grid_slots() if r["body_id"] is not None
                   and (r["orbital"], r["surface"]) != self._loaded_slots.get(r["body_id"])]
        if not changed:
            self._slots_lbl.setText("No slot changes to save")
            return
        id64, url = self.id64, self.hub_url
        cmdr = getattr(getattr(getattr(self.parent(), "_panel", None), "_last_state", None), "commander", None)
        self._save_slots_btn.setEnabled(False)
        self._slots.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._slots_lbl.setText("Saving…")
        self._start(lambda: (id64, [(r, put_colonisation_slots(url, id64, r["body_id"], r["orbital"], r["surface"], cmdr))
                                    for r in changed]), self._on_slots_saved)

    def _on_slots_saved(self, result) -> None:
        if result is None:  # the worker raised
            self._save_slots_btn.setEnabled(True)
            self._slots.setEditTriggers(self._edit_triggers)
            self._slots_lbl.setText("Slots not saved (error, see the log)")
            return
        if result[0] != self.id64 or self._system is None:
            return
        self._save_slots_btn.setEnabled(True)
        self._slots.setEditTriggers(self._edit_triggers)
        saved = {r["body_id"]: r for r, ok in result[1] if ok}
        for b in self._system.get("bodies") or []:
            if b.get("body_id") in saved:
                b["orbital_slots"], b["surface_slots"] = saved[b["body_id"]]["orbital"], saved[b["body_id"]]["surface"]
        failed = len(result[1]) - len(saved)
        if failed:
            self._loaded_slots.update({k: (r["orbital"], r["surface"]) for k, r in saved.items()})
            self._slots_lbl.setText(f"Hub did not store {failed} of {len(result[1])} bodies (not reachable, or not updated yet)")
            return
        self._fill_slots()
        self._slots_lbl.setText(f"Saved slots for {len(saved)} bodies")

    def _replan(self, *_) -> None:
        if self._system is None:
            return
        primary = self._combo.currentData()
        self._table.setRowCount(0)
        self._warnings.setText("")
        self._outcome.setText("")
        if primary is None:
            has_details = plan_system(self._system, "", False)["poor"] != "Hub has no body details yet"
            self._banner.setText("" if has_details else "Hub has no body details yet")
            self._banner.setStyleSheet(_RED)
            self._banner.setVisible(not has_details)
            return
        plan = plan_system(self._system, primary, self._group.isChecked())
        self._banner.setStyleSheet(_RED)
        self._mark_btns["bad"].setStyleSheet(_BTN_STYLE + ("QPushButton { border:2px solid #ff6b6b; }" if plan["poor"] else ""))
        kind, slots = self._kind.currentData(), self._grid_slots()
        typed = kind and any(r["orbital"] is not None or r["surface"] is not None for r in slots)
        if plan["poor"]:
            self._banner.setText(f"Poor pick: {plan['poor']}" if plan["poor"] != "Hub has no body details yet"
                                 else plan["poor"])
            self._banner.setVisible(True)
            if not typed:  # a typed plan with slot counts still shows, under the template's red banner
                self._warnings.setText(_NO_SLOTS if kind else "")
                return
        else:
            self._banner.setVisible(bool(plan["weak"]))
            if plan["weak"]:
                score = self._system.get("service_score")
                band = next((b for lim, b in _SCORE_BANDS if score < lim), "top quarter") if score is not None else "unknown"
                self._banner.setText(f"Usable, but a weak pick: {'; '.join(plan['weak'])}"
                                     f" — hub service score {score if score is not None else '?'} ({band})")
                self._banner.setStyleSheet(_AMBER)
        if typed:
            p = plan_by_type(self._system, slots, primary, self._group.isChecked(), kind)
            sysname = self._system.get("name") or ""
            short = lambda n: (n or "").removeprefix(sysname).strip() or n
            rows = [[s["title"], short(s["body"]), s["note"] or "", "", f"T2 {s['t2']}, T3 {s['t3']}; {s['haul']:,} t"]
                    for s in p["steps"]]
            # per-body "slots unknown" warnings fold into one line: p["unknown"] lists the same bodies
            lines = [w for w in p["warnings"] if " slots unknown: " not in w] + ([p["note"]] if p.get("note") else [])
            lines.append(f"Slots left: {p['unused']['orbital']} orbital, {p['unused']['surface']} surface"
                         + (f"; counts unknown on {', '.join(map(short, p['unknown']))}" if p["unknown"] else ""))
            o = p["outcome"]
            self._outcome.setText("Projected: " + ", ".join(f"{k} {o['stats'][k]}" for k in
                                                            ("pop", "mpop", "sec", "wealth", "tech", "sol", "dev"))
                                  + f" — haul {o['haul']:,} t — score {o['score']} (Raven Colonial-style, for comparison only)")
        else:
            rows = [[s["title"], s["body"], ", ".join(s["unlocks"]), s["needs"] or "", s["points"]] for s in plan["steps"]]
            lines = list(plan["warnings"]) + ([plan["note"]] if plan["note"] else []) + ([_NO_SLOTS] if kind else [])
        self._table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, text in enumerate(row):
                self._table.setItem(r, c, QTableWidgetItem(text))
        self._table.resizeRowsToContents()
        self._warnings.setText("\n".join(lines))

    # ── squad mark ─────────────────────────────────────────────────────
    def _show_mark(self, mark: Optional[dict]) -> None:
        self._note.setText((mark or {}).get("note") or "")
        self._mark_lbl.setText(mark_text(mark))
        body = (mark or {}).get("primary_body")
        i = self._combo.findData(body) if body else -1
        if i > 0 and self._combo.currentIndex() <= 0:
            self._combo.setCurrentIndex(i)

    def _save_mark(self, verdict: Optional[str]) -> None:
        primary = self._combo.currentData()
        if verdict and primary is None:
            self._mark_lbl.setText("Pick the primary slot body first: the mark records it")
            return
        id64, url, note = self.id64, self.hub_url, self._note.text().strip() or None
        state = getattr(getattr(self.parent(), "_panel", None), "_last_state", None)
        cmdr = getattr(state, "commander", None)
        mark = {"verdict": verdict, "primary_body": primary, "note": note, "cmdr": cmdr} if verdict else None
        for b in self._mark_btns.values():
            b.setEnabled(False)
        self._mark_lbl.setText("Saving…")
        self._start(lambda: (id64, mark, put_colonisation_mark(url, id64, verdict, primary if verdict else None,
                                                               note if verdict else None, cmdr)), self._on_mark_saved)

    def _on_mark_saved(self, result) -> None:
        if result is None or result[0] != self.id64:
            return
        id64, mark, ok = result
        for b in self._mark_btns.values():
            b.setEnabled(True)
        if not ok:
            self._mark_lbl.setText("Hub did not store the mark (not reachable, or not updated yet)")
            return
        if self._system is not None:
            self._system["mark"] = mark
        self._mark_lbl.setText(mark_text(mark))
        if self.on_marked:
            self.on_marked(id64, mark)
