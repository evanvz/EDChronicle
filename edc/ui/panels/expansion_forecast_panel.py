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

from PyQt6.QtCore import QObject, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from edc.core.edsm_faction_lookup import fetch_system_factions
from edc.core.expansion_forecast import (
    CACHE_MAX_AGE_H, CUBE_LY, LOOKUP_COUNT, WATCH_THRESHOLD, alert_text, detect_new_systems, is_current,
    likely_source, rank_candidates, watched_systems,
)
from edc.ui.style import HDR_STYLE, PRIMARY_BUTTON_STYLE, TABLE_STYLE, bulk_table_fill

log = logging.getLogger(__name__)

_NOTE = ("Rules are community-researched, not Frontier documentation. A closer system can be skipped if "
         "the faction left it before tracking began.")
_DIM = "color:#888888; font-size:11px; background:transparent; border:none;"


class _ForecastWorker(QObject):
    """Cube query (slow) + EDSM lookups for the nearest candidates, on its
    own DB connection. Emits ({"rows", "candidates", "unknown_population"}, None)
    or (None, error text)."""
    finished = pyqtSignal(object, object)

    def __init__(self, db_path, source: dict, exclude_names: set, faction: str):
        super().__init__()
        self._db_path, self._source, self._exclude, self._faction = db_path, source, exclude_names, faction

    def run(self):
        from persistence.database import Database
        from persistence.repository import Repository

        db = Database(self._db_path)
        try:
            cube = Repository(db).get_cube_systems(self._source["x"], self._source["y"], self._source["z"], CUBE_LY)
        except Exception as exc:
            log.exception("Expansion forecast cube query failed")
            self.finished.emit(None, str(exc))
            return
        finally:
            db.close()
        sx, sy, sz = self._source["x"], self._source["y"], self._source["z"]
        populated, unknown = [], 0
        for s in cube:
            if s["system_name"] in self._exclude:
                continue
            if s["population"] is None:
                unknown += 1
                continue
            if s["population"] <= 0:
                continue
            dist = ((s["x"] - sx) ** 2 + (s["y"] - sy) ** 2 + (s["z"] - sz) ** 2) ** 0.5
            if dist > 0:
                populated.append({"system_name": s["system_name"], "system_address": s["system_address"],
                                  "distance_ly": dist})
        populated.sort(key=lambda c: c["distance_ly"])
        rows = []
        for c in populated[:LOOKUP_COUNT]:
            result, _err = fetch_system_factions(c["system_name"])
            if not result:
                rows.append({**c, "faction_count": None, "faction_present": False})
                continue
            names = [f.get("Name") for f in result.get("factions") or [] if (f.get("Influence") or 0) > 0]
            rows.append({**c, "system_address": result.get("system_address") or c["system_address"],
                         "faction_count": len(names), "faction_present": self._faction in names})
        self.finished.emit({"rows": rows, "candidates": len(populated), "unknown_population": unknown}, None)


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
        self._been: set = set()
        self._current: set = set()

        layout = QVBoxLayout(self)
        self._status = QLabel("")
        self._status.setStyleSheet(_DIM)
        layout.addWidget(self._status)

        hdr = QLabel("NEXT TO EXPAND — faction systems at 70% or more")
        hdr.setStyleSheet(HDR_STYLE)
        layout.addWidget(hdr)
        self._next_table = _table(["System", "Influence", "Days ≥75%", "State", "Likely source"])
        self._next_table.setMaximumHeight(140)
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
        self._target_status.setStyleSheet(_DIM)
        layout.addWidget(self._target_status)
        self._target_table = _table(["#", "Tier", "System", "Distance", "Factions", "Faction here before", "Data"])
        self._target_table.cellClicked.connect(self._copy_name)
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
        layout.addWidget(self._last_label)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()

    def _faction(self) -> Optional[str]:
        return self._panel._faction_name or self._panel._repo.get_squadron_faction_name()

    def refresh(self) -> None:
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
        src_name = self._source["system_name"] if self._source else None
        _fill(self._next_table, [
            [w["system_name"] or str(w["system_address"]), f"{(w['influence'] or 0) * 100:.1f}%",
             str(w["days_above"]), w["phase"] or "—",
             ("yes" if w["system_name"] == src_name and self._source["eligible"]
              else "not yet (needs a day at 75%)" if w["system_name"] == src_name else "")]
            for w in watched])
        self._render_last_result(repo, faction, today)
        if not self._source:
            self._target_status.setText("No faction system at 70% or more.")
            _fill(self._target_table, [])
            return
        self._render_targets()
        self._start_lookup(force=False)

    def _render_targets(self, extra: str = "") -> None:
        cached = self._panel._repo.get_expansion_candidates(self._source["system_address"])
        ranked = rank_candidates([dict(c, been_before=c["system_name"] in self._been) for c in cached])
        fetched = cached[0]["fetched_at"][:16].replace("T", " ") if cached else "never"
        _fill(self._target_table, [
            [str(i + 1) if c["tier"] else "", str(c["tier"]) if c["tier"] else "not checked", c["system_name"],
             f"{c['distance_ly']:.1f} ly" if c.get("distance_ly") is not None else "",
             "" if c["faction_count"] is None else str(c["faction_count"]),
             "yes" if c["been_before"] else "unknown", fetched]
            for i, c in enumerate(ranked)])
        self._target_status.setText(
            f"From {self._source['system_name']}: nearest {len(cached)} candidates in the ±20 ly cube "
            f"(EDSM, {fetched} UTC). Tier 1 = fewer than 7 factions, never there; tier 2 = fewer than 7, "
            f"faction was there before; tier 3 = 7 factions (invasion war).{extra}"
            + ("" if any(c["tier"] for c in ranked) or not cached else
               " No eligible system within ±20 ly — the game would search ±30 ly next, or the expansion fails."))

    def _render_last_result(self, repo, faction, today) -> None:
        new = detect_new_systems(repo, faction, today)
        self._last_label.setText(alert_text(faction, new[0]) if new else
                                 "No new faction system in the last 3 days.")

    def _cache_fresh(self) -> bool:
        cached = self._panel._repo.get_expansion_candidates(self._source["system_address"])
        if not cached:
            return False
        fetched = datetime.fromisoformat(cached[0]["fetched_at"].replace("Z", "+00:00"))
        return datetime.now(timezone.utc) - fetched < timedelta(hours=CACHE_MAX_AGE_H)

    def _start_lookup(self, force: bool) -> None:
        if not self._source or (self._thread is not None and self._thread.isRunning()):
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
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_lookup_finished)
        self._worker.finished.connect(self._thread.quit)
        self._thread.start()

    def _on_lookup_finished(self, result, error) -> None:
        if not result:
            self._target_status.setText(f"Lookup failed ({error}) — showing the last cached data.")
            return
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            self._panel._repo.save_expansion_candidates(self._source["system_address"], result["rows"], now)
        except Exception:
            log.exception("Failed to save expansion candidates")
        skipped = result["unknown_population"]
        self._render_targets(f" Skipped {skipped} systems with unknown population." if skipped else "")

    def _copy_name(self, row: int, _col: int) -> None:
        item = self._target_table.item(row, 2)
        if item:
            QApplication.clipboard().setText(item.text())
