"""Non-modal "System Design" window: phased build plan for one claimable system, from the hub's body details.
The hub fetch runs on a worker thread; the plan itself is edc.core.colonisation_design.plan_system."""
from __future__ import annotations

from itertools import count
from typing import Callable, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QComboBox, QDialog, QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
    QRadioButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from edc.core import colonisation_facilities
from edc.core.colonisation_design import plan_system
from edc.core.colonisation_plan_status import own_systems, status_updates, unlinked_depots
from edc.core.colonisation_planner import TYPE_NAMES, TYPES, plan as plan_by_type, slot_table
from edc.core.eddatahub_client import fetch_colonisation_system, put_colonisation_mark, put_colonisation_slots
from edc.core.raven_colonial import get_system_slots
from edc.ui.panels.colonisation_finder_dialog import _BTN_STYLE, _INPUT_STYLE, _TABLE_STYLE, _WorkerThreads, mark_text

_HINT = "Find the flag in the system map's Architect View"
_FOOTER = ("Sources (community-reported, not official): CMDR Dubior's Advanced ED Colonization Guide (ref. 2026-08-11, read 2026-10-30); "
           "Colonization 101 (CMDR PhoenixBlue0, read 2026-10-30); DaftMav Service Unlocks flowchart (read 2026-10-30).\n"
           "Official: Frontier Trailblazers Update 3.3 notes, service activation (read 2026-10-31). Construction points: "
           "ED wiki System Colonisation (rev. 2026-10-26), gaborauth ED Colonisation Planner (read 2026-10-31).\n"
           "Controlling faction = the faction controlling the station you buy the claim at.")
_GREY = "color:#9aa4b0; font-size:13px;"
_RED = "color:#ff6b6b; font-weight:bold; font-size:13px;"
_AMBER = "color:#FFB347; font-weight:bold; font-size:13px;"
# hub service score spread over all systems, 2026-11-04 (after the economy-rule re-score): median 16, top quarter from 38
_SCORE_BANDS = ((16, "bottom half"), (38, "middle"))
_LABEL = "color:#c8c8c8; font-size:12px;"
_SOURCES = {"entered": "entered", "raven": "Raven", "est": "est.", None: "?"}
_NO_SLOTS = ("Check every body's slots in Architect View, then Confirm and save slots to plan by type:"
             " {} of {} bodies not confirmed")


class ColonisationDesignDialog(_WorkerThreads, QDialog):
    def __init__(self, parent, hub_url: str, id64: int, name: str, repo=None):
        super().__init__(parent)
        self.setStyleSheet("QDialog { background:#080f18; color:#c8c8c8; }")
        self.setWindowTitle(f"Colonisation — Design: {name}")
        self.resize(900, 820)
        self.hub_url, self.id64 = hub_url, id64
        self._repo = repo  # None on the finder path: read-only plan
        self._sync_depots = False  # apply depot statuses once per load, at the first typed plan
        self._stored: dict = {}  # (body, location, slot_index): stored step
        self._links: list = []  # (label, combo, button) per unlinked construction site
        self._threads: list = []  # (QThread, _Worker) pairs, kept referenced until finished
        self._system: Optional[dict] = None
        self._raven: Optional[dict] = None
        self._loaded_slots: dict = {}  # body_id: (orbital, surface) as last filled, so Save sends only changed rows

        root = QVBoxLayout(self)
        self._sys = QComboBox()  # your colonisation systems (every system with a construction site)
        self._sys.setStyleSheet(_INPUT_STYLE)
        self._sys.activated.connect(lambda i: self.load(self._sys.itemData(i), self._sys.itemText(i)))
        if repo is not None:
            sys_row = QHBoxLayout()
            sys_lbl = QLabel("System")
            sys_lbl.setStyleSheet(_LABEL)
            sys_row.addWidget(sys_lbl)
            sys_row.addWidget(self._sys, 1)
            root.addLayout(sys_row)
        row = QHBoxLayout()
        lbl = QLabel("Primary slot body")
        lbl.setStyleSheet(_LABEL)
        self._combo = QComboBox()
        self._combo.setStyleSheet(_INPUT_STYLE)
        self._combo.setToolTip(_HINT)
        self._combo.addItem("Pick the primary slot body…", None)
        self._combo.setEnabled(False)
        self._combo.currentIndexChanged.connect(self._on_setting)
        self._solo = QRadioButton("Solo")
        self._group = QRadioButton("Group")
        self._solo.setChecked(True)
        for r in (self._solo, self._group):
            r.setStyleSheet(_LABEL)
            r.toggled.connect(self._on_setting)
        row.addWidget(lbl)
        row.addWidget(self._combo, 1)
        self._kind = QComboBox()
        self._kind.setStyleSheet(_INPUT_STYLE)
        self._kind.addItem("Template", None)
        for t in TYPES:
            self._kind.addItem(TYPE_NAMES[t], t)
        self._kind.currentIndexChanged.connect(self._on_setting)
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

        self._table = QTableWidget(0, 11)
        self._table.setHorizontalHeaderLabels(["#", "Step", "Body", "Status", "Unlocks", "Needs",
                                               "Cost", "Earns", "Points after", "Haul", ""])
        for c, tip in ((6, "Construction points this build uses up (from your system's T2/T3 balance)"),
                       (7, "Construction points you get once this build completes"),
                       (8, "Your T2/T3 balance once this step completes, if every step above it is done"),
                       (9, "Commodities to deliver for this build")):
            self._table.horizontalHeaderItem(c).setToolTip(tip)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.setWordWrap(True)
        self._table.setStyleSheet(_TABLE_STYLE)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self._table, 1)

        self._sites = QGroupBox("Construction sites")
        self._sites.setStyleSheet(_LABEL)
        self._sites_grid = QGridLayout(self._sites)
        self._sites.setVisible(False)
        root.addWidget(self._sites)

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
        self._slots.itemChanged.connect(self._on_slot_edit)
        self._edit_triggers = self._slots.editTriggers()  # restored after a save, which locks the grid
        root.addWidget(self._slots, 1)
        slots_row = QHBoxLayout()
        self._save_slots_btn = QPushButton("Confirm and save slots")
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
        if self._repo is not None:
            self._sys.clear()
            for addr, n in {**own_systems(self._repo.get_colonisation_depots()), id64: name}.items():
                self._sys.addItem(n, addr)
            self._sys.setCurrentIndex(self._sys.findData(id64))
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
            self._banner.setText("EDDataHub not reachable, or this system isn't on its colonisation list")
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
        widgets = (self._combo, self._kind, self._solo, self._group)
        for w in widgets:  # restoring picks is not a change: no save, one re-plan below
            w.blockSignals(True)
        self._show_mark(system.get("mark"))
        s = self._repo.get_colonisation_plan(self.id64)["settings"] if self._repo else None
        if self._repo and not s:  # defaults, so the previous system's picks don't carry over
            s = {"kind": None, "group": False, "primary_body": None}
        if s:
            self._kind.setCurrentIndex(max(self._kind.findData(s["kind"]), 0) if s["kind"] else 0)
            (self._group if s["group"] else self._solo).setChecked(True)
            i = self._combo.findData(s["primary_body"]) if s["primary_body"] else -1
            if i > 0:
                self._combo.setCurrentIndex(i)
        for w in widgets:
            w.blockSignals(False)
        self._sync_depots = self._repo is not None
        self._replan()
        id64 = self.id64
        self._start(lambda: (id64, get_system_slots(sysname)), self._on_raven)

    # ── slot grid ──────────────────────────────────────────────────────
    def _on_raven(self, result) -> None:
        if result is None or result[0] != self.id64 or self._system is None or not result[1]:
            return
        self._raven = result[1]
        self._refill()
        self._replan()

    def _refill(self) -> None:
        edited = {r["body_id"]: r for r in self._grid_slots()
                  if (r["orbital"], r["surface"]) != self._loaded_slots.get(r["body_id"])}
        self._fill_slots()
        self._slots.blockSignals(True)  # unsaved edits stay, against the new baseline
        for i in range(self._slots.rowCount()):
            r = edited.get(self._slots.item(i, 0).data(Qt.ItemDataRole.UserRole)["body_id"])
            if r:
                for c, k in ((1, "orbital"), (2, "surface")):
                    t = "" if r[k] is None else str(r[k])
                    self._slots.item(i, c).setText(t)
                    self._slots.item(i, c).setData(Qt.ItemDataRole.UserRole, t)
        self._slots.blockSignals(False)

    def _fill_slots(self) -> None:
        sysname = self._system.get("name") or ""
        rows = slot_table(self._system, self._raven)
        for r in rows:  # an estimate is a hint, not a confirmed count: the cell stays blank until entered
            if r["surface_source"] == "est":
                r["est"], r["surface"] = r["surface"], None
        self._loaded_slots = {r["body_id"]: (r["orbital"], r["surface"]) for r in rows}
        self._slots.blockSignals(True)
        self._slots.setRowCount(len(rows))
        for i, r in enumerate(rows):
            label = r["name"] or f"Body {r['body_id']}"
            name = QTableWidgetItem(label.removeprefix(sysname).strip() or label)
            name.setData(Qt.ItemDataRole.UserRole, r)
            sur = f"est. {r['est']}" if r["surface_source"] == "est" and r.get("est") is not None else _SOURCES[r["surface_source"]]
            src = QTableWidgetItem(f"{_SOURCES[r['orbital_source']]} / {sur}")
            for it in (name, src):
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._slots.setItem(i, 0, name)
            for c, k in ((1, "orbital"), (2, "surface")):
                cell = QTableWidgetItem("" if r[k] is None else str(r[k]))
                cell.setData(Qt.ItemDataRole.UserRole, cell.text())  # last good text, for reverting a bad edit
                self._slots.setItem(i, c, cell)
            self._slots.setItem(i, 3, src)
        self._slots.blockSignals(False)

    def _on_slot_edit(self, item) -> None:
        t = item.text().strip()
        self._slots.blockSignals(True)  # 0-20 or blank (cleared); anything else reverts, so a typo never saves
        item.setText(t if not t or (t.isdigit() and int(t) <= 20) else item.data(Qt.ItemDataRole.UserRole))
        item.setData(Qt.ItemDataRole.UserRole, item.text())
        self._slots.blockSignals(False)
        self._replan()

    def _grid_slots(self) -> list:
        def count(r, c):
            t = self._slots.item(r, c).text().strip()
            return int(t) if t.isdigit() else None
        return [{**self._slots.item(r, 0).data(Qt.ItemDataRole.UserRole), "orbital": count(r, 1), "surface": count(r, 2)}
                for r in range(self._slots.rowCount())]

    def _confirmed(self, r: dict) -> bool:
        return (r["orbital_source"] == r["surface_source"] == "entered"
                and (r["orbital"], r["surface"]) == self._loaded_slots.get(r["body_id"]))

    def _save_slots(self) -> None:
        # saving confirms the grid as checked: Raven counts shown in it become squad facts; estimates never fill a cell
        changed = [r for r in self._grid_slots() if r["body_id"] is not None
                   and ((r["orbital"], r["surface"]) != self._loaded_slots.get(r["body_id"])
                        or any(r[k] is not None and r[f"{k}_source"] != "entered" for k in ("orbital", "surface")))]
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
            self._refill()  # stored rows reload with their sources, refused edits stay
            self._slots_lbl.setText(f"Hub did not store {failed} of {len(result[1])} bodies (not reachable, or not updated yet)")
            self._replan()
            return
        self._fill_slots()
        self._slots_lbl.setText(f"Saved slots for {len(saved)} bodies")
        self._replan()

    def _on_setting(self, *_) -> None:
        if self._repo and self._system is not None:
            self._repo.save_colonisation_plan_settings(self.id64, self._kind.currentData(), self._group.isChecked(),
                                                       self._combo.currentData())
        self._replan()

    def _save_step(self, s: dict, **change) -> None:
        old = self._stored.get((s["body"], s["location"], s["slot_index"]), {})
        r = {"facility": s["facility"], "status": s["status"], "market_id": old.get("market_id"), **change}
        if r["facility"] is None:  # "left empty" picked again
            return
        self._repo.save_colonisation_plan_step(self.id64, s["body"], s["location"], s["slot_index"],
                                               r["facility"], r["status"], r["market_id"])
        self._replan()

    def _reset_step(self, s: dict) -> None:
        self._repo.delete_colonisation_plan_step(self.id64, s["body"], s["location"], s["slot_index"])
        self._replan()

    def _replan(self, *_) -> None:
        if self._system is None:
            return
        primary = self._combo.currentData()
        self._table.setRowCount(0)
        self._links = []
        while self._sites_grid.count():
            self._sites_grid.takeAt(0).widget().deleteLater()  # a Link button may be the sender
        self._sites.setVisible(False)
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
        # a typed plan only once every body's counts are checked and saved: a part-known system plans the wrong build
        unconfirmed = sum(not self._confirmed(r) for r in slots)
        typed = kind and not unconfirmed
        no_slots = _NO_SLOTS.format(unconfirmed, len(slots))
        if plan["poor"]:
            self._banner.setText(f"Poor pick: {plan['poor']}" if plan["poor"] != "Hub has no body details yet"
                                 else plan["poor"])
            self._banner.setVisible(True)
            if not typed:  # a typed plan with slot counts still shows, under the template's red banner
                self._warnings.setText(no_slots if kind else "")
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
            stored = self._repo.get_colonisation_plan(self.id64)["steps"] if self._repo else None
            p = plan_by_type(self._system, slots, primary, self._group.isChecked(), kind, stored)
            depots = self._repo.get_colonisation_depots() if self._repo else []
            if self._sync_depots:
                self._sync_depots = False
                prim = {k: p["steps"][0][k] for k in ("facility", "body", "location", "slot_index")}
                ups = status_updates(stored, depots, self.id64, prim)
                for u in ups:
                    self._repo.save_colonisation_plan_step(self.id64, u["body"], u["location"], u["slot_index"],
                                                           u["facility"], u["status"], u["market_id"])
                if ups:
                    stored = self._repo.get_colonisation_plan(self.id64)["steps"]
                    p = plan_by_type(self._system, slots, primary, self._group.isChecked(), kind, stored)
            self._stored = {(r["body"], r["location"], r["slot_index"]): r for r in stored or []}
            sysname = self._system.get("name") or ""
            short = lambda n: (n or "").removeprefix(sysname).strip() or n
            fac = colonisation_facilities.load()

            def cp(s, kind):  # "T2 1 · T3 2"; the primary is free
                f = fac.get(s["facility"])
                if f is None or (kind == "cp_cost" and s["n"] == 1):
                    return "free" if f else ""
                return " · ".join(f"T{t} {f[kind][f't{t}']}" for t in (2, 3) if f[kind][f"t{t}"]) or "—"

            rows = [[str(s["n"]), s["title"], short(s["body"]), "", s["note"] or "", s["error"] or "",
                     cp(s, "cp_cost"), cp(s, "cp_reward"), f"T2 {s['t2']} · T3 {s['t3']}", f"{s['haul']:,} t"]
                    for s in p["steps"]]
            rows += [["", "left empty", short(e["body"]), "", "", e["reason"].removeprefix("left empty: "), "", "", "", ""]
                     for e in p["empty"]]
            colors = ["#ff6b6b" if s["error"] or s["t2"] < 0 or s["t3"] < 0 else None for s in p["steps"]] \
                + ["#9aa4b0"] * len(p["empty"])
            lines = list(p["warnings"]) + ([p["note"]] if p.get("note") else [])
            lines.append(f"Slots left: {p['unused']['orbital']} orbital, {p['unused']['surface']} surface")
            o = p["outcome"]
            self._outcome.setText("Projected: " + ", ".join(f"{k} {o['stats'][k]}" for k in
                                                            ("pop", "mpop", "sec", "wealth", "tech", "sol", "dev"))
                                  + f" — haul {o['haul']:,} t — score {o['score']} (Raven Colonial-style, for comparison only)")
        else:
            rows = [[str(n), s["title"], s["body"], "", ", ".join(s["unlocks"]), s["needs"] or "", "", "", s["points"], ""]
                    for n, s in enumerate(plan["steps"], 1)]
            colors = [None] * len(rows)
            lines = list(plan["warnings"]) + ([plan["note"]] if plan["note"] else []) + ([no_slots] if kind else [])
        self._table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, text in enumerate(row):
                it = QTableWidgetItem(text)
                if colors[r]:
                    it.setForeground(QColor(colors[r]))
                self._table.setItem(r, c, it)
        if typed and self._repo:
            self._fill_selectors(p, depots, short)
        self._table.resizeRowsToContents()
        self._warnings.setText("\n".join(lines))

    def _fill_selectors(self, p: dict, depots: list, short: Callable) -> None:
        fac = colonisation_facilities.load()
        steps = list(p["steps"])
        for e in p["empty"]:  # a pick here becomes a Planned step in the next free slot of that body
            used = {s["slot_index"] for s in p["steps"] if (s["body"], s["location"]) == (e["body"], e["location"])}
            steps.append({"body": e["body"], "location": e["location"], "facility": None, "status": "Planned",
                          "slot_index": next(i for i in count() if i not in used)})
        for r, s in enumerate(steps):  # signals connected after filling, so filling never saves
            step = QComboBox()
            step.setStyleSheet(_INPUT_STYLE)
            step.wheelEvent = lambda e: e.ignore()  # the wheel scrolls the table, never changes a step
            if s["facility"] is None:
                step.addItem("left empty", None)
            for k, f in fac.items():
                if f["location"] == s["location"]:
                    # settlements and the port: the game's last click is a layout name (Mantus, Orcus), same facility
                    layouts = f" ({', '.join(x.title() for x in f['rc_types'])})" if f["name"].startswith(("Settlement >", "Planetary Port > Port")) else ""
                    step.addItem(f["name"] + layouts, k)
            step.setCurrentIndex(max(step.findData(s["facility"]), 0) if s["facility"] else 0)
            step.setEnabled(s.get("n") != 1 or bool(s.get("fixed")))  # an unstored primary follows Solo/Group
            step.currentIndexChanged.connect(lambda _, s=s, c=step: self._save_step(s, facility=c.currentData()))
            self._table.setCellWidget(r, 1, step)
            if "n" not in s:
                continue
            st = QComboBox()
            st.setStyleSheet(_INPUT_STYLE)
            st.wheelEvent = lambda e: e.ignore()
            st.addItems(["Planned", "Building", "Complete"])
            st.setCurrentText(s["status"])
            st.currentTextChanged.connect(lambda t, s=s: self._save_step(s, status=t))
            self._table.setCellWidget(r, 3, st)
            if s["fixed"] and s["n"] != 1:
                b = QPushButton("Reset")
                b.setStyleSheet(_BTN_STYLE)
                b.clicked.connect(lambda _, s=s: self._reset_step(s))
                self._table.setCellWidget(r, 10, b)
        targets = [s for s in p["steps"] if s["n"] != 1]
        for i, d in enumerate(unlinked_depots(list(self._stored.values()), depots, self.id64)):
            lbl = QLabel(f"{d['station_name']} — {(d['progress'] or 0) * 100:.1f}%")
            c = QComboBox()
            c.setStyleSheet(_INPUT_STYLE)
            for s in targets:
                c.addItem(f"#{s['n']} {s['title']} — {short(s['body'])}", s)
            b = QPushButton("Link")
            b.setStyleSheet(_BTN_STYLE)
            b.clicked.connect(lambda _, c=c, d=d: c.currentData() and self._save_step(
                c.currentData(), status="Complete" if d["complete"] else "Building", market_id=d["market_id"]))
            for col, w in enumerate((lbl, c, b)):
                self._sites_grid.addWidget(w, i, col)
            self._links.append((lbl, c, b))
        self._sites.setVisible(bool(self._links))

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
