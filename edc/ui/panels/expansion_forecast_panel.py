# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the PolyForm Noncommercial License 1.0.0.
# See the LICENSE file in the project root for full terms.
"""Faction Expansion Tracker -> Forecast tab: the squadron faction's systems
near expansion, a ranked shortlist of likely targets for the likely source,
and the last expansion's result. See
docs/superpowers/specs/2026-10-08-expansion-forecast-design.md."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QHeaderView, QLabel, QPushButton, QScrollArea, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from edc.core.edsm_faction_lookup import fetch_populated_cube, fetch_system_factions
from edc.core.expansion_forecast import (
    CACHE_MAX_AGE_H, CUBE_LY, LOOKUP_MAX, OUTER_CUBE_LY, WATCH_THRESHOLD, alert_text,
    detect_new_systems, faction_expansion_line, first_expansion, in_cube, is_current, likely_source, rank_candidates, watched_systems,
)

NEXT_ROWS = 10   # "next to expand" shows the top 10 by influence
from edc.ui.style import HDR_STYLE, PRIMARY_BUTTON_STYLE, TABLE_STYLE, bulk_table_fill

log = logging.getLogger(__name__)

_NOTE = ("Rules are community-researched, not Frontier documentation. A closer system can be skipped if "
         "the faction left it before tracking began.")
_DIM = "color:#888888; font-size:11px; background:transparent; border:none;"


class _ForecastWorker(QObject):
    """Cube query (slow) + EDSM lookups for the nearest candidates, on its
    own DB connection. Emits ({"rows", "candidates", "unknown_population",
    "failed"}, None) or (None, error text); (None, "cancelled") after cancel()."""
    finished = pyqtSignal(object, object)

    def __init__(self, db_path, source: dict, exclude_names: set, faction: str):
        super().__init__()
        self._db_path, self._source, self._exclude, self._faction = db_path, source, exclude_names, faction
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def _candidates(self, half: float, inner: Optional[float]):
        """Populated candidates in the +-half cube (skipping the +-inner cube
        already searched), nearest first: EDSM's cube search in one request,
        or the app's own coordinates if EDSM can't be reached. Returns
        (candidates, source label, systems skipped for unknown population)."""
        src = (self._source["x"], self._source["y"], self._source["z"])
        cube, label, unknown = fetch_populated_cube(*src, half), "EDSM", 0
        if cube is None:
            from persistence.database import Database
            from persistence.repository import Repository
            db = Database(self._db_path)
            try:
                cube, label = Repository(db).get_cube_systems(*src, half), "local data (EDSM unreachable)"
            finally:
                db.close()
        out = []
        for s in cube:
            xyz = (s["x"], s["y"], s["z"])
            if (s["system_name"] in self._exclude or None in xyz or not in_cube(src, xyz, half)
                    or (inner and in_cube(src, xyz, inner))):   # inner ring already searched
                continue
            if s["population"] is None:
                unknown += 1
                continue
            if s["population"] <= 0:
                continue
            dist = sum((a - b) ** 2 for a, b in zip(xyz, src)) ** 0.5
            if dist > 0:
                out.append({"system_name": s["system_name"], "system_address": s["system_address"],
                            "distance_ly": dist, "ring": half})
        return sorted(out, key=lambda c: c["distance_ly"]), label, unknown

    def _lookup(self, cands: list) -> Optional[tuple]:
        """EDSM faction lists for the candidates (capped); None if cancelled."""
        rows, failed = [], 0
        for c in cands[:LOOKUP_MAX]:
            if self._cancelled:
                return None
            result, _err = fetch_system_factions(c["system_name"])
            if not result:
                failed += 1
                rows.append({**c, "faction_count": None, "faction_present": False, "faction_former": False})
                continue
            factions = result.get("factions") or []
            names = [f.get("Name") for f in factions if (f.get("Influence") or 0) > 0]
            # EDSM keeps factions that left the system, at 0% influence
            former = any(f.get("Name") == self._faction and not (f.get("Influence") or 0) for f in factions)
            rows.append({**c, "system_address": result.get("system_address") or c["system_address"],
                         "faction_count": len(names), "faction_present": self._faction in names,
                         "faction_former": former})
        return rows, failed

    def run(self):
        try:
            cands, label, unknown = self._candidates(CUBE_LY, None)
        except Exception as exc:
            log.exception("Expansion forecast candidate search failed")
            self.finished.emit(None, str(exc))
            return
        looked = self._lookup(cands)
        if looked is None:
            self.finished.emit(None, "cancelled")
            return
        rows, failed = looked
        total, outer = len(cands), False
        eligible = any(r["faction_count"] is not None and r["faction_count"] < 8 and not r["faction_present"]
                       for r in rows)
        # the game only searches +-30 ly when +-20 ly has no eligible system
        if not eligible and len(rows) > failed:
            try:
                more, _label, more_unknown = self._candidates(OUTER_CUBE_LY, CUBE_LY)
            except Exception:
                log.exception("Expansion forecast outer-ring search failed")
                more, more_unknown = [], 0
            looked = self._lookup(more)
            if looked is None:
                self.finished.emit(None, "cancelled")
                return
            rows, failed = rows + looked[0], failed + looked[1]
            total, unknown, outer = total + len(more), unknown + more_unknown, True
        if failed:
            log.warning("Expansion forecast: %d of %d EDSM lookups failed", failed, len(rows))
        self.finished.emit({"rows": rows, "candidates": total, "unknown_population": unknown,
                            "failed": failed, "source": label, "outer_ring": outer}, None)


def _table(headers):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    t.verticalHeader().setVisible(False)
    t.setStyleSheet(TABLE_STYLE)
    h = t.horizontalHeader()
    for c in range(len(headers)):
        h.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
    h.setStretchLastSection(True)
    return t


def _fill(table, rows):
    table.setRowCount(len(rows))
    with bulk_table_fill(table):
        for i, row in enumerate(rows):
            for c, text in enumerate(row):
                table.setItem(i, c, QTableWidgetItem(text))


class ExpansionForecastPanel(QWidget):
    def __init__(self, panel, parent=None):
        super().__init__(parent)
        self._panel = panel
        self._thread: Optional[QThread] = None
        self._worker: Optional[_ForecastWorker] = None
        self._source: Optional[dict] = None
        self._lookup_source: Optional[tuple] = None
        self._been: set = set()
        self._current: set = set()

        # the tab scrolls as a whole: the 10-row "next to expand" table plus
        # the targets table don't fit the tracker's default window height
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer.addWidget(scroll)
        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        self._status = QLabel("")
        self._status.setStyleSheet(_DIM)
        self._status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._status)

        hdr = QLabel(f"NEXT TO EXPAND — top {NEXT_ROWS} faction systems at 70% or more")
        hdr.setStyleSheet(HDR_STYLE)
        layout.addWidget(hdr)
        # Expansion is faction-wide, so its state is one line, not a per-system column
        self._expansion_line = QLabel("")
        self._expansion_line.setTextFormat(Qt.TextFormat.PlainText)
        self._expansion_line.setWordWrap(True)
        self._expansion_line.setStyleSheet("background:transparent; border:none; color:#FFB347;")
        layout.addWidget(self._expansion_line)
        self._next_table = _table(["System", "Influence", "Days ≥75%", "Likely source"])
        # tall enough for all NEXT_ROWS rows without scrolling
        rh = self._next_table.verticalHeader().defaultSectionSize()
        self._next_table.setFixedHeight(self._next_table.horizontalHeader().sizeHint().height()
                                        + rh * NEXT_ROWS + 4)
        layout.addWidget(self._next_table)

        row = QHBoxLayout()
        hdr2 = QLabel("LIKELY TARGETS")
        hdr2.setStyleSheet(HDR_STYLE)
        row.addWidget(hdr2)
        row.addStretch(1)
        self._refresh_btn = QPushButton("Refresh lookups")
        self._refresh_btn.setStyleSheet(PRIMARY_BUTTON_STYLE)
        self._refresh_btn.clicked.connect(lambda: self._start_lookup(force=True))
        row.addWidget(self._refresh_btn)
        layout.addLayout(row)
        self._target_status = QLabel("")
        self._target_status.setWordWrap(True)
        self._target_status.setTextFormat(Qt.TextFormat.PlainText)
        self._target_status.setStyleSheet(_DIM)
        layout.addWidget(self._target_status)
        self._target_table = _table(["#", "Tier", "System", "Distance", "Factions", "Faction here before", "Data"])
        self._target_table.cellClicked.connect(self._copy_name)
        self._target_table.setMinimumHeight(self._target_table.verticalHeader().defaultSectionSize() * 9)
        layout.addWidget(self._target_table, 1)
        note = QLabel(_NOTE)
        note.setWordWrap(True)
        note.setStyleSheet(_DIM)
        layout.addWidget(note)

        hdr3 = QLabel("LAST RESULT")
        hdr3.setStyleSheet(HDR_STYLE)
        layout.addWidget(hdr3)
        self._last_label = QLabel("—")
        self._last_label.setWordWrap(True)
        self._last_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._last_label)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()

    def _faction(self) -> Optional[str]:
        return self._panel._faction_name or self._panel._repo.get_squadron_faction_name()

    def refresh(self) -> None:
        try:
            self._refresh()
        except Exception:
            log.exception("Failed to build expansion forecast")
            self._status.setText("Forecast failed — see log.")

    def _refresh(self) -> None:
        faction = self._faction()
        if not faction:
            self._status.setText("No squadron faction known yet.")
            _fill(self._next_table, [])
            _fill(self._target_table, [])
            return
        repo, today = self._panel._repo, date.today()
        presence = repo.get_squadron_presence(faction)
        histories = {r["system_address"]: list(reversed(repo.get_faction_history(r["system_address"], faction)))
                     for r in presence if is_current(r, today) and (r.get("influence") or 0) >= WATCH_THRESHOLD}
        watched = watched_systems(presence, histories, today)
        self._source = likely_source(watched)
        self._been = {r["system_name"] for r in presence if not is_current(r, today)}
        self._current = {r["system_name"] for r in presence if is_current(r, today)}
        self._status.setText(f"{faction} — {len(self._current)} current systems")
        self._expansion_line.setText(faction_expansion_line(presence, histories, today))
        src_name = self._source["system_name"] if self._source else None
        _fill(self._next_table, [
            [w["system_name"] or str(w["system_address"]), f"{(w['influence'] or 0) * 100:.1f}%",
             str(w["days_above"]),
             ("yes" if w["system_name"] == src_name and self._source["eligible"]
              else "not yet (needs a day at 75%)" if w["system_name"] == src_name else "")]
            for w in watched[:NEXT_ROWS]])
        self._render_last_result(repo, faction, today)
        if not self._source:
            self._target_status.setText("No faction system at 70% or more.")
            _fill(self._target_table, [])
            return
        self._render_targets()
        self._start_lookup(force=False)

    def _render_targets(self, extra: str = "") -> None:
        cached = self._panel._repo.get_expansion_candidates(self._source["system_address"])
        ranked = rank_candidates([dict(c, been_before=c.get("faction_former") or c["system_name"] in self._been)
                                  for c in cached])
        fetched = cached[0]["fetched_at"][:16].replace("T", " ") if cached else "never"

        def before(c):
            if c.get("faction_former"):
                return "yes (EDSM)"
            return "yes (history)" if c["system_name"] in self._been else "unknown"
        _fill(self._target_table, [
            [str(i + 1) if c["tier"] else "", str(c["tier"]) if c["tier"] else "not checked", c["system_name"],
             (f"{c['distance_ly']:.1f} ly" + (" (±30 ring)" if (c.get("ring") or CUBE_LY) > CUBE_LY else ""))
             if c.get("distance_ly") is not None else "",
             "" if c["faction_count"] is None else str(c["faction_count"]), before(c), fetched]
            for i, c in enumerate(ranked)])
        outer = any((c.get("ring") or CUBE_LY) > CUBE_LY for c in cached)
        area = ("the ±20 ly cube and the ±30 ly ring (nothing eligible within ±20 ly)" if outer
                else "the ±20 ly cube")
        self._target_status.setText(
            f"From {self._source['system_name']}: all {len(cached)} candidates "
            f"in {area} (EDSM; faction here before = our history + EDSM's former-faction list; "
            f"{fetched} UTC). Tier 1 = fewer than 7 factions, never there; tier 2 = fewer than 7, "
            f"faction was there before; tier 3 = 7 factions (invasion war).{extra}"
            + ("" if any(c["tier"] for c in ranked) or not cached else
               " No eligible system within ±30 ly — the expansion would fail." if outer else
               " No eligible system within ±20 ly — the game would search ±30 ly next, or the expansion fails."))

    def _render_last_result(self, repo, faction, today) -> None:
        new = detect_new_systems(repo, faction, today)
        item = first_expansion(new) or (new[0] if new else None)
        self._last_label.setText(alert_text(faction, item) if item else
                                 "No new faction system in the last 3 days.")

    def _cache_fresh(self) -> bool:
        cached = self._panel._repo.get_expansion_candidates(self._source["system_address"])
        if not cached:
            return False
        try:
            fetched = datetime.fromisoformat(cached[0]["fetched_at"].replace("Z", "+00:00"))
        except (ValueError, TypeError, AttributeError):
            return False
        return datetime.now(timezone.utc) - fetched < timedelta(hours=CACHE_MAX_AGE_H)

    def _lookup_running(self) -> bool:
        try:
            return self._thread.isRunning()
        except RuntimeError:  # thread already deleteLater'd
            return False

    def _start_lookup(self, force: bool) -> None:
        if not self._source or (self._thread is not None and self._lookup_running()):
            return
        if not force and self._cache_fresh():
            return
        coords = self._panel._repo.get_system_coords_for_names([self._source["system_name"]])
        xyz = coords.get(self._source["system_name"])
        if not xyz:
            self._target_status.setText(f"No coordinates for {self._source['system_name']} yet.")
            return
        self._target_status.setText("Looking up candidates on EDSM…")
        self._worker = _ForecastWorker(self._panel._repo.db.db_path, {"x": xyz[0], "y": xyz[1], "z": xyz[2]},
                                       set(self._current), self._faction())
        self._lookup_source = (self._source["system_address"], self._source["system_name"])
        self._thread = QThread(self)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_lookup_finished)
        self._worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _on_lookup_finished(self, result, error) -> None:
        address = self._lookup_source[0] if self._lookup_source else None
        if not result:
            self._target_status.setText(f"Lookup failed ({error}) — showing the last cached data.")
            return
        rows = result["rows"]
        repo = self._panel._repo
        old = repo.get_expansion_candidates(address) if address is not None else []
        if rows:
            fresh = any(r["faction_count"] is not None for r in rows)
            old_by_name = {c["system_name"]: c for c in old}
            for r in rows:
                prev = old_by_name.get(r["system_name"])
                if r["faction_count"] is None and prev and prev["faction_count"] is not None:
                    r["faction_count"], r["faction_present"] = prev["faction_count"], prev["faction_present"]
                    r["faction_former"] = prev.get("faction_former", False)
            if not fresh:
                when = old[0]["fetched_at"][:16].replace("T", " ") if old else None
                self._target_status.setText(f"Lookup failed — showing data from {when} UTC" if when
                                            else "Lookup failed — EDSM not reachable")
                return
            looked = sum(1 for r in rows if r["faction_count"] is not None)
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            try:
                repo.save_expansion_candidates(address, rows, now)
            except Exception:
                log.exception("Failed to save expansion candidates")
        if address is None or not self._source or self._source["system_address"] != address:
            return
        if not rows:
            self._target_status.setText("No populated system without the faction within ±30 ly — "
                                        "the expansion would fail.")
            return
        skipped = result["unknown_population"]
        self._render_targets(f" Looked up {looked} of {result['candidates']} (candidate list: "
                             f"{result.get('source', 'local data')})."
                             + (f" Skipped {skipped} systems with unknown population." if skipped else ""))

    def _copy_name(self, row: int, _col: int) -> None:
        item = self._target_table.item(row, 2)
        if item:
            QApplication.clipboard().setText(item.text())
