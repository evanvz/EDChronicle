# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the PolyForm Noncommercial License 1.0.0.
# See the LICENSE file in the project root for full terms.

"""Colonisation tab — tracked construction sites (squadron-wide projects,
personal-visit-only since no EDDN schema exists for this event) and the
nearby-unpopulated-system candidate finder. Split out of squadron_panel.py
once colonisation stopped being a small side feature and started needing
its own room to grow (candidate system details, a future build-resource
planner).
"""
from __future__ import annotations

import logging
from html import escape
from typing import Dict, Optional

from PyQt6.QtCore import Qt, QThread, QObject, QStringListModel, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QComboBox, QCompleter,
    QTableWidget, QTableWidgetItem, QHeaderView, QFrame, QDialog, QApplication,
)

from edc.ui.style import (
    CARD_STYLE as _CARD_STYLE, HDR_STYLE as _HDR_STYLE, PRIMARY_BUTTON_STYLE as _BTN_STYLE,
    TABLE_STYLE as _TABLE_STYLE,
    card_style as _card_style, hdr_style as _hdr_style,
    set_table_empty_message as _empty, set_table_rows as _rows,
)
from edc.core.spansh_client import SpanshClient
from edc.core import raven_colonial
from edc.ui.formatting import clean_token

log = logging.getLogger(__name__)

# Update 3 colony economy override table, verbatim from Frontier's own
# patch notes (cross-checked against the ed-colonisation-planner /
# ed-colonisation-planner-solver community tools' own verbatim citation of
# the same patch notes) -- which economies a port gets from the body it's
# built on/around, stacking. Only strong links (same body, or a facility
# directly linked to that port) actually apply this; a weak link (different
# body, same system) only ever contributes a flat 5% regardless of type.
# Ordered so a more specific match (e.g. "rocky ice") is checked before a
# substring it also contains ("rocky"). Organics/geologicals aren't
# included -- those need an actual FSS/DSS scan signal, not available for
# a not-yet-visited candidate from Spansh's body list alone.
_ECONOMY_BY_BODY_ATTR: list[tuple[str, list[str]]] = [
    ("neutron", ["High Tech", "Tourism"]),
    ("white dwarf", ["High Tech", "Tourism"]),
    ("black hole", ["High Tech", "Tourism"]),
    ("earth-like", ["Agriculture", "High Tech", "Military", "Tourism"]),
    ("water world", ["Agriculture", "Tourism"]),
    ("ammonia world", ["High Tech", "Tourism"]),
    ("gas giant", ["High Tech", "Industrial"]),
    ("metal-rich", ["Extraction"]),
    ("metal content", ["Extraction"]),
    ("rocky ice", ["Industrial", "Refinery"]),
    ("icy", ["Industrial"]),
    ("rocky", ["Refinery"]),
]


# clean_token("$economy_HighTech;") -> "HighTech" (no space) -- Frontier's
# only multi-word economy label, so it's the only one that needs fixing up
# to match _HIGH_VALUE's "High Tech" spelling used for highlighting below.
def _economy_display(token: str) -> str:
    name = clean_token(token)
    return "High Tech" if name == "HighTech" else name


def _predict_economies(planet_class: str, has_rings: bool) -> list[str]:
    """Which Update 3 economy types this body would contribute as a strong
    link, based only on what Spansh's body list already tells us (planet
    class, ring presence) -- pure function, no I/O, so it's independently
    testable without a QWidget."""
    pc = (planet_class or "").lower()
    economies: list[str] = []
    for needle, adds in _ECONOMY_BY_BODY_ATTR:
        if needle in pc:
            for e in adds:
                if e not in economies:
                    economies.append(e)
            break  # first (most specific) match wins -- these are mutually exclusive body classes
    if has_rings and "Extraction" not in economies:
        economies.append("Extraction")
    return economies


def _current_system_summary(state) -> Optional[tuple[str, str, str, str]]:
    """Returns (system_name, occupied_text, occupied_color, economy_text)
    for the "Current System" card, or None if there's no current system yet
    (state.system unset). Pure function, no I/O -- independently testable.

    Occupied/Unoccupied comes from state.population (live journal data, not
    a guess). Economy: real state.system_economy when occupied (we're
    physically there, no need to predict); the same body-attribute
    prediction the candidate dialog uses when unoccupied (an uninhabited
    system has no real economy to report)."""
    system_name = getattr(state, "system", None) if state else None
    if not system_name:
        return None

    population = getattr(state, "population", None)
    if isinstance(population, int) and population > 0:
        occupied_text, occupied_color = "Occupied", "#FF8080"
        economy = _economy_display(getattr(state, "system_economy", "") or "")
        secondary = _economy_display(getattr(state, "system_economy_secondary", "") or "")
        if economy:
            economy_text = economy + (f" / {secondary}" if secondary and secondary != economy else "")
        else:
            economy_text = "—"
    elif population == 0:
        occupied_text, occupied_color = "Unoccupied", "#6BCB77"
        bodies = getattr(state, "bodies", None) or {}
        economies: list[str] = []
        for rec in bodies.values():
            if not isinstance(rec, dict):
                continue
            for e in _predict_economies(rec.get("PlanetClass") or "", False):
                if e not in economies:
                    economies.append(e)
        economy_text = f"Likely: {', '.join(economies)}" if economies else "not enough scanned yet"
    else:
        occupied_text, occupied_color = "—", "#9aa4b0"
        economy_text = "—"

    return system_name, occupied_text, occupied_color, economy_text


def _aggregate_shopping_list(depots: list[dict]) -> list[tuple[str, int, int]]:
    """Sums still-needed amounts (required - provided, floored at 0) for
    every commodity across every incomplete tracked depot. Returns
    [(commodity_name, total_amount, site_count), ...] sorted by amount
    descending. Pure function, no I/O -- independently testable."""
    totals: dict[str, int] = {}
    site_counts: dict[str, int] = {}
    for d in depots:
        if d.get("complete"):
            continue  # nothing left to buy for a finished site
        for r in (d.get("resources") or []):
            if not isinstance(r, dict):
                continue
            name = r.get("name")
            if not name:
                continue
            required = r.get("required") or 0
            provided = r.get("provided") or 0
            remaining = max(0, required - provided)
            if remaining <= 0:
                continue
            totals[name] = totals.get(name, 0) + remaining
            site_counts[name] = site_counts.get(name, 0) + 1

    return sorted(
        ((name, amount, site_counts[name]) for name, amount in totals.items()),
        key=lambda row: row[1],
        reverse=True,
    )


class _SystemDetailWorker(QObject):
    """One-shot background fetch of a candidate system's body list and ring
    list from Spansh -- name-only lookup (no system_address available for
    a not-yet-visited candidate). Rings need id64, which fetch_system_bodies
    doesn't resolve, so a separate id64 lookup chains into
    fetch_system_rings(); if that first lookup fails, rings are just
    skipped (empty list) rather than failing the whole dialog -- the body
    list is the more important half."""
    finished = pyqtSignal(list, str, list, dict, dict)  # bodies, error, rings, mining_signals, system_info

    def __init__(self, system_name: str):
        super().__init__()
        self._system_name = system_name

    def run(self):
        client = SpanshClient()
        bodies, error, system_info = client.fetch_system_bodies(self._system_name)
        rings: list = []
        mining_signals: dict = {}
        id64, id64_error = client.fetch_system_id64(self._system_name)
        if id64 is not None:
            rings, rings_error, mining_signals = client.fetch_system_rings(id64)
            if rings_error:
                log.warning("Spansh ring fetch failed for %s: %s", self._system_name, rings_error)
        elif id64_error:
            log.warning("Spansh id64 lookup failed for %s: %s", self._system_name, id64_error)
        self.finished.emit(bodies, error, rings, mining_signals, system_info)


class _RavenColonialWorker(QObject):
    """One-shot background fetch of a Raven Colonial build project --
    network I/O never runs on the UI thread. Emits the raw project dict (or
    None if not found/failed) plus an error string for the "no project"
    vs "request failed" distinction the dialog needs to word its message
    correctly."""
    finished = pyqtSignal(object, str)  # project dict or None, error

    def __init__(self, build_id: Optional[str] = None,
                 system_address: Optional[int] = None, market_id: Optional[int] = None):
        super().__init__()
        self._build_id = build_id
        self._system_address = system_address
        self._market_id = market_id

    def run(self):
        try:
            if self._build_id:
                project = raven_colonial.get_project(self._build_id)
            else:
                project = raven_colonial.get_project_for_station(self._system_address, self._market_id)
            error = "" if project is not None else "No Raven Colonial build found."
        except Exception as exc:
            project = None
            error = str(exc)
        self.finished.emit(project, error)


class _RavenColonialSourcesWorker(QObject):
    """One-shot background fetch of nearby buy sources for every
    still-needed commodity on a Raven Colonial build -- runs
    search_market_buy_prices per commodity (local SQLite, not network) so
    the dialog can show "nearest place to buy" without a per-row click.
    Pad-size filtering is applied client-side afterwards (see
    _RavenColonialDialog._render_table) so changing the pad selector
    doesn't need a re-fetch -- all candidate rows within radius are kept,
    not just the best one."""
    finished = pyqtSignal(dict)  # commodity symbol -> list[dict] (rows, distance_ly + pad_size already computed)

    def __init__(self, db_path, commodities: list, x: float, y: float, z: float, radius_ly: float = 100.0):
        super().__init__()
        self._db_path = db_path
        self._commodities = commodities
        self._x, self._y, self._z = x, y, z
        self._radius_ly = radius_ly

    def run(self):
        from persistence.database import Database
        from persistence.repository import Repository

        db = Database(self._db_path)
        results = {}
        try:
            repo = Repository(db)
            for symbol in self._commodities:
                try:
                    rows = repo.search_market_buy_prices(symbol, self._x, self._y, self._z, self._radius_ly)
                except Exception:
                    log.exception("Nearest-source lookup failed for %r", symbol)
                    rows = []
                rows.sort(key=lambda r: r.get("distance_ly", float("inf")))
                results[symbol] = rows
        finally:
            db.close()
        self.finished.emit(results)


_PAD_RANK = {"S": 1, "M": 2, "L": 3}


class _RavenColonialDialog(QDialog):
    """Non-modal, read-only view of a Raven Colonial squad build project --
    see edc/core/raven_colonial.py for why this only ever reads (never
    pushes our own data to a third-party platform). Opened either
    pre-fetched via a depot's own (system_address, market_id) -- auto-detect,
    since Raven Colonial has no project for most stations -- or with a
    pasted build link/id for viewing someone else's shared build.

    Commodity table mirrors the website's own layout as closely as the
    data allows -- category-grouped (EDCD/FDevIDs commodity.csv's own
    category field, see commodity_categories.py), Need + Assigned columns
    (the latter inverted from the project's own commander->commodities
    map). NOT replicated: the site's delivery-rate chart and "system
    effects" block, neither reachable from any documented Raven Colonial
    endpoint (confirmed via njthomson/SrvSurvey's own client, the only
    reference available) -- not guessing at undocumented API surface.

    Once a build loads, also finds the nearest place to buy each still-
    needed commodity, filtered to stations the selected ship can actually
    land at -- defaults to the commander's currently-flown ship
    (state.ship, via ShipPadSizeTable) with a dropdown to check a
    different ship/pad size. This lookup is EDChronicle's own addition,
    not something the website itself offers."""

    def __init__(self, panel: "ColonisationPanel"):
        super().__init__(None)
        self.setStyleSheet("QDialog { background:#080f18; color:#c8c8c8; }")
        self._panel = panel
        self._thread: Optional[QThread] = None
        self._worker: Optional[_RavenColonialWorker] = None
        self._sources_thread: Optional[QThread] = None
        self._sources_worker: Optional[_RavenColonialSourcesWorker] = None
        self._project: Optional[dict] = None
        self._sources_by_commodity: Dict[str, list] = {}
        self.setWindowTitle("Raven Colonial — Squad Build")
        self.resize(820, 560)

        layout = QVBoxLayout(self)

        paste_row = QHBoxLayout()
        self._paste_edit = QLineEdit()
        self._paste_edit.setPlaceholderText("Paste a ravencolonial.com build link or id…")
        self._paste_edit.setStyleSheet("background:#0a1520; color:#c8c8c8; border:1px solid #1e3a5a;")
        self._paste_edit.returnPressed.connect(self._on_load_clicked)
        load_btn = QPushButton("Load")
        load_btn.setStyleSheet(_BTN_STYLE)
        load_btn.clicked.connect(self._on_load_clicked)
        paste_row.addWidget(self._paste_edit, 1)
        paste_row.addWidget(load_btn)
        layout.addLayout(paste_row)

        site_link = QLabel('<a href="https://ravencolonial.com" style="color:#8CC8FF;">https://ravencolonial.com</a>')
        site_link.setOpenExternalLinks(True)
        site_link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        site_link.setStyleSheet("font-size:11px; background:transparent; border:none;")
        layout.addWidget(site_link)

        pin_row = QHBoxLayout()
        self._pin_label = QLabel("")
        self._pin_label.setStyleSheet("color:#888888; font-size:11px; background:transparent; border:none;")
        pin_row.addWidget(self._pin_label, 1)
        refresh_btn = QPushButton("⟳ Refresh")
        refresh_btn.setStyleSheet(_BTN_STYLE)
        refresh_btn.setToolTip("Re-fetch the currently loaded build's latest progress.")
        refresh_btn.clicked.connect(self._on_refresh_clicked)
        pin_row.addWidget(refresh_btn)
        self._unpin_btn = QPushButton("Unpin")
        self._unpin_btn.setStyleSheet(_BTN_STYLE)
        self._unpin_btn.setToolTip("Stop remembering this build -- it won't reopen automatically next time.")
        self._unpin_btn.setEnabled(False)
        self._unpin_btn.clicked.connect(self._on_unpin_clicked)
        pin_row.addWidget(self._unpin_btn)
        layout.addLayout(pin_row)

        # Auto-refreshes whatever's currently loaded every 2 minutes while
        # this dialog exists, on top of the refresh-on-open (see
        # showEvent) and manual Refresh button -- a squad build's numbers
        # move as often as anyone docks and delivers, not something a
        # one-shot load stays accurate for very long.
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(2 * 60 * 1000)
        self._refresh_timer.timeout.connect(self._on_auto_refresh_tick)

        pad_row = QHBoxLayout()
        pad_label = QLabel("Landing pad:")
        pad_label.setStyleSheet("color:#9aa4b0; background:transparent; border:none;")
        pad_row.addWidget(pad_label)
        self._pad_combo = QComboBox()
        self._pad_combo.addItem("Auto (current ship)", None)
        self._pad_combo.addItem("Small", "S")
        self._pad_combo.addItem("Medium", "M")
        self._pad_combo.addItem("Large", "L")
        self._pad_combo.setStyleSheet("background:#0a1520; color:#c8c8c8; border:1px solid #1e3a5a;")
        self._pad_combo.currentIndexChanged.connect(self._render_table)
        pad_row.addWidget(self._pad_combo)
        self._pad_auto_label = QLabel("")
        self._pad_auto_label.setStyleSheet("color:#888888; font-size:11px; background:transparent; border:none;")
        pad_row.addWidget(self._pad_auto_label)
        pad_row.addStretch(1)
        layout.addLayout(pad_row)

        self._status_label = QLabel("")
        self._status_label.setWordWrap(True)
        self._status_label.setStyleSheet("color:#888888; font-size:11px; background:transparent; border:none;")
        layout.addWidget(self._status_label)

        self._header_label = QLabel("")
        self._header_label.setWordWrap(True)
        self._header_label.setStyleSheet("color:#FFB347; font-size:14px; font-weight:bold; background:transparent; border:none;")
        layout.addWidget(self._header_label)

        self._info_label = QLabel("")
        self._info_label.setWordWrap(True)
        self._info_label.setStyleSheet("color:#9aa4b0; font-size:11px; background:transparent; border:none;")
        layout.addWidget(self._info_label)

        self._table = QTableWidget()
        self._table.setColumnCount(8)
        self._table.setHorizontalHeaderLabels(
            ["Commodity", "Need", "Assigned", "Source Station", "Pad", "Source System", "Dist (ly)", "Stock"]
        )
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet(_TABLE_STYLE)
        self._table.setToolTip("Click a Source Station or Source System cell to copy its name to the clipboard.")
        self._table.cellClicked.connect(self._on_table_cell_clicked)
        th = self._table.horizontalHeader()
        th.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        th.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        th.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        th.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        th.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        th.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        th.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        th.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self._table, 1)

        note = QLabel(
            "Build progress is read-only, live from Raven Colonial's public API (community "
            "platform, not EDDN) -- EDChronicle never pushes data there. Nearest-source lookups "
            "are this app's own EDDN-derived market data, within 100 ly of your current system."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#9aa4b0; font-size:11px; background:transparent; border:none;")
        layout.addWidget(note)

        self._load_pinned_build()

    def showEvent(self, event) -> None:
        """Refresh-on-open: whatever's already loaded (pinned or not) gets
        a fresh fetch every time this dialog is reopened, on top of the
        interval timer and the manual Refresh button."""
        super().showEvent(event)
        if self._project:
            self._on_refresh_clicked()
        elif not (self._thread and self._thread.isRunning()):
            self._load_pinned_build()

    def _load_pinned_build(self) -> None:
        store = self._panel._raven_pin_store
        build_id = store.load() if store else None
        if not build_id:
            return
        self._status_label.setText("Loading your pinned build…")
        self._start_fetch(_RavenColonialWorker(build_id=build_id))

    def load_for_station(self, system_address: int, market_id: int) -> None:
        self._paste_edit.clear()
        self._status_label.setText("Looking up Raven Colonial build for this station…")
        self._start_fetch(_RavenColonialWorker(system_address=system_address, market_id=market_id))

    def _on_refresh_clicked(self) -> None:
        build_id = (self._project or {}).get("buildId")
        if not build_id:
            self._load_pinned_build()
            return
        self._status_label.setText("Refreshing…")
        self._start_fetch(_RavenColonialWorker(build_id=build_id))

    def _on_auto_refresh_tick(self) -> None:
        build_id = (self._project or {}).get("buildId")
        if build_id:
            self._start_fetch(_RavenColonialWorker(build_id=build_id))

    def _on_unpin_clicked(self) -> None:
        store = self._panel._raven_pin_store
        if store:
            store.clear()
        self._refresh_timer.stop()
        self._project = None
        self._sources_by_commodity = {}
        self._unpin_btn.setEnabled(False)
        self._pin_label.setText("")
        self._header_label.setText("")
        self._info_label.setText("")
        self._status_label.setText("Unpinned.")
        _empty(self._table, "")

    def _on_load_clicked(self) -> None:
        build_id = raven_colonial.parse_build_id(self._paste_edit.text())
        if not build_id:
            self._status_label.setText("Could not find a build id in that text.")
            return
        self._status_label.setText("Loading…")
        self._start_fetch(_RavenColonialWorker(build_id=build_id))

    def _start_fetch(self, worker: "_RavenColonialWorker") -> None:
        if self._thread and self._thread.isRunning():
            return
        self._worker = worker
        if self._thread is not None:
            self._thread.wait()  # old-thread teardown race -- see main_window.py's _start_spansh_enrich docstring
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_fetched)
        self._worker.finished.connect(self._thread.quit)
        self._thread.start()

    def _current_ship_pad(self) -> Optional[str]:
        state = self._panel._last_state
        table = self._panel._ship_pad_table
        if table is None or state is None:
            return None
        return table.pad_size_for(getattr(state, "ship", None))

    def _effective_pad_filter(self) -> Optional[str]:
        override = self._pad_combo.currentData()
        if override:
            return override
        return self._current_ship_pad()

    def _on_fetched(self, project, error: str) -> None:
        self._project = project
        self._sources_by_commodity = {}
        if project is None:
            self._status_label.setText(error or "No Raven Colonial build found.")
            self._header_label.setText("")
            self._info_label.setText("")
            _empty(self._table, "")
            return

        self._status_label.setText("")
        build_name = project.get("buildName") or "—"
        system_name = project.get("systemName") or "—"
        build_type = project.get("buildType") or "—"
        complete = "Complete" if project.get("complete") else "In progress"
        self._header_label.setText(f"{build_name} — {system_name} ({build_type}) — {complete}")

        sum_need = project.get("sumNeed")
        max_need = project.get("maxNeed")
        progress_text = "progress unknown"
        if isinstance(sum_need, (int, float)) and isinstance(max_need, (int, float)) and max_need > 0:
            pct = max(0.0, min(100.0, (1 - sum_need / max_need) * 100))
            progress_text = f"{pct:.0f}% delivered"

        architect = project.get("architectName") or "unknown"
        ready_count = len(project.get("ready") or [])
        fc_count = len(project.get("linkedFC") or [])
        commanders = project.get("commanders") or {}
        cmdr_text = f"{len(commanders)} commander{'s' if len(commanders) != 1 else ''}" if commanders else "no commanders listed"

        self._info_label.setText(
            f"Architect: {architect}  •  {progress_text}  •  Ready on Fleet Carriers: {ready_count}  "
            f"•  Linked Fleet Carriers: {fc_count}  •  {cmdr_text}"
        )

        build_id = project.get("buildId")
        store = self._panel._raven_pin_store
        if build_id and store:
            store.save(build_id)
        self._unpin_btn.setEnabled(True)
        from datetime import datetime
        self._pin_label.setText(f"Pinned — auto-refreshes every 2 min. Last refreshed {datetime.now().strftime('%H:%M:%S')}.")
        if not self._refresh_timer.isActive():
            self._refresh_timer.start()

        self._render_table()
        self._start_sources_fetch()

    def _remaining_commodities(self) -> Dict[str, float]:
        if not self._project:
            return {}
        commodities = self._project.get("commodities") or {}
        return {sym: qty for sym, qty in commodities.items() if isinstance(qty, (int, float)) and qty > 0}

    def _assigned_commanders(self) -> Dict[str, list]:
        """commodity symbol -> sorted list of commander names assigned to
        deliver it -- inverted from the project's own commander->[commodities]
        map (the shape Raven Colonial's API actually returns)."""
        commanders = (self._project or {}).get("commanders") or {}
        assigned: Dict[str, list] = {}
        for cmdr, symbols in commanders.items():
            if not isinstance(symbols, list):
                continue
            for sym in symbols:
                assigned.setdefault(sym, []).append(cmdr)
        for names in assigned.values():
            names.sort()
        return assigned

    def _start_sources_fetch(self) -> None:
        remaining = self._remaining_commodities()
        state = self._panel._last_state
        x, y, z = getattr(state, "system_x", None), getattr(state, "system_y", None), getattr(state, "system_z", None)
        if not remaining or x is None or y is None or z is None:
            return
        if self._sources_thread and self._sources_thread.isRunning():
            return
        self._sources_worker = _RavenColonialSourcesWorker(self._panel._repo.db.db_path, list(remaining.keys()), x, y, z)
        if self._sources_thread is not None:
            self._sources_thread.wait()  # old-thread teardown race -- see main_window.py's _start_spansh_enrich docstring
        self._sources_thread = QThread()
        self._sources_worker.moveToThread(self._sources_thread)
        self._sources_thread.started.connect(self._sources_worker.run)
        self._sources_worker.finished.connect(self._on_sources_fetched)
        self._sources_worker.finished.connect(self._sources_thread.quit)
        self._sources_thread.start()

    def _on_sources_fetched(self, sources: dict) -> None:
        self._sources_by_commodity = sources
        self._render_table()

    def _best_source_for(self, symbol: str):
        rows = self._sources_by_commodity.get(symbol) or []
        min_pad = self._effective_pad_filter()
        if not min_pad:
            return rows[0] if rows else None
        min_rank = _PAD_RANK[min_pad]
        for r in rows:
            pad = r.get("pad_size")
            if pad in _PAD_RANK and _PAD_RANK[pad] >= min_rank:
                return r
        return None

    def _grouped_rows(self, remaining: Dict[str, float]) -> list:
        """[(category, [(symbol, display_name, qty), ...]), ...], category-
        grouped and alphabetized both ways to match the website's own
        layout -- falls back to "Other" for any symbol not in our
        category reference (a commodity too new for the pinned FDevIDs
        snapshot, omitted rather than silently miscategorized)."""
        cat_table = self._panel._commodity_categories
        by_category: Dict[str, list] = {}
        for symbol, qty in remaining.items():
            category = (cat_table.category_for(symbol) if cat_table else None) or "Other"
            display = (cat_table.display_name_for(symbol) if cat_table else None) or clean_token(symbol)
            by_category.setdefault(category, []).append((symbol, display, qty))
        for entries in by_category.values():
            entries.sort(key=lambda e: e[1])
        return sorted(by_category.items(), key=lambda kv: kv[0])

    def _render_table(self) -> None:
        remaining = self._remaining_commodities()
        grouped = self._grouped_rows(remaining)
        assigned = self._assigned_commanders()

        ship_pad = self._current_ship_pad()
        override = self._pad_combo.currentData()
        if override:
            self._pad_auto_label.setText("")
        elif ship_pad:
            self._pad_auto_label.setText(f"(current ship needs {ship_pad})")
        else:
            self._pad_auto_label.setText("(current ship's pad size unknown — showing all)")

        total_rows = sum(1 + len(entries) for _, entries in grouped)  # +1 per category header row
        self._table.setSortingEnabled(False)
        _rows(self._table, total_rows)

        row = 0
        for category, entries in grouped:
            self._table.setSpan(row, 0, 1, self._table.columnCount())
            header_item = QTableWidgetItem(category.upper())
            header_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            header_item.setBackground(QColor("#12324d"))
            header_item.setForeground(QColor("#8CC8FF"))
            font = header_item.font()
            font.setBold(True)
            header_item.setFont(font)
            self._table.setItem(row, 0, header_item)
            row += 1

            for symbol, display, qty in entries:
                name_item = QTableWidgetItem(display)
                qty_item = QTableWidgetItem(f"{qty:,.0f}")
                qty_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                assigned_item = QTableWidgetItem(", ".join(assigned.get(symbol, [])) or "—")

                best = self._best_source_for(symbol)
                if best is not None:
                    stock = best.get("stock")
                    stock_known = isinstance(stock, (int, float))
                    short = stock_known and stock < qty
                    colour = QColor("#FF6B6B") if short else None

                    station_item = QTableWidgetItem(best.get("station_name") or "—")
                    pad_item = QTableWidgetItem(best.get("pad_size") or "?")
                    pad_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    system_item = QTableWidgetItem(best.get("system_name") or "—")
                    dist_value = best.get("distance_ly")
                    dist_text = f"{dist_value:.1f}" if isinstance(dist_value, (int, float)) else "—"
                    dist_item = QTableWidgetItem(dist_text)
                    dist_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    stock_text = f"{stock:,.0f}" + (" (short)" if short else "") if stock_known else "unknown"
                    stock_item = QTableWidgetItem(stock_text)
                    stock_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    if colour:
                        for it in (station_item, pad_item, system_item, dist_item, stock_item):
                            it.setForeground(colour)
                else:
                    placeholder = "No matching source within 100 ly." if symbol in self._sources_by_commodity else "Looking up…"
                    station_item = QTableWidgetItem(placeholder)
                    station_item.setForeground(QColor("#888888"))
                    pad_item = QTableWidgetItem("")
                    system_item = QTableWidgetItem("")
                    dist_item = QTableWidgetItem("")
                    stock_item = QTableWidgetItem("")

                self._table.setItem(row, 0, name_item)
                self._table.setItem(row, 1, qty_item)
                self._table.setItem(row, 2, assigned_item)
                self._table.setItem(row, 3, station_item)
                self._table.setItem(row, 4, pad_item)
                self._table.setItem(row, 5, system_item)
                self._table.setItem(row, 6, dist_item)
                self._table.setItem(row, 7, stock_item)
                row += 1
        # Sorting stays off -- category header rows use setSpan(), and
        # user-driven column sort would scramble those spanned rows in
        # among the data rows instead of respecting the grouping.
        if not grouped:
            complete = self._project.get("complete") if self._project else False
            _empty(self._table, "Nothing still needed — build complete." if complete else "No shortfall data.")

    def _on_table_cell_clicked(self, row: int, column: int) -> None:
        if column not in (3, 5):  # Source Station, Source System
            return
        item = self._table.item(row, column)
        if item and item.text() and item.text() not in ("—", "No matching source within 100 ly.", "Looking up…"):
            QApplication.clipboard().setText(item.text())


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
        if depot.get("system_address") and depot.get("market_id"):
            raven_btn = QPushButton("Raven Colonial")
            raven_btn.setStyleSheet(_BTN_STYLE)
            raven_btn.setToolTip("Look up this station's squad build on Raven Colonial (read-only).")
            raven_btn.clicked.connect(
                lambda: self._open_raven_for_station(depot["system_address"], depot["market_id"])
            )
            hdr_row.addWidget(raven_btn)
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

    def _open_raven_for_station(self, system_address: int, market_id: int) -> None:
        self._panel._open_raven_dialog()
        self._panel._raven_dialog.load_for_station(system_address, market_id)

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


class _SystemDetailDialog(QDialog):
    """Non-modal window showing a candidate system's body and ring list from
    Spansh -- planet types, water worlds/ELWs, landable flags, distance,
    ring presence/hotspots -- the things a player normally checks before
    deciding whether a system is worth building in. Fetches in the
    background so opening it never blocks the UI; shown immediately in a
    loading state."""

    def __init__(self, system_name: str, repo=None):
        super().__init__(None)
        self.setStyleSheet("QDialog { background:#080f18; color:#c8c8c8; }")
        self.setWindowTitle(f"System Detail — {system_name}")
        self.resize(760, 460)
        self._system_name = system_name
        self._repo = repo
        self._confirmed_economy_text = ""
        if repo is not None:
            try:
                profile = repo.get_system_profile_by_name(system_name)
            except Exception:
                profile = None
            if profile and profile["economy"]:
                economy = _economy_display(profile["economy"])
                second = _economy_display(profile["second_economy"]) if profile["second_economy"] else ""
                self._confirmed_economy_text = (
                    f"Confirmed economy (EDDN sighting): {economy}" + (f" / {second}" if second else "")
                )

        layout = QVBoxLayout(self)
        hdr_row = QHBoxLayout()
        hdr = QLabel(system_name)
        hdr.setStyleSheet("color:#FFB347; font-size:14px; font-weight:bold; background:transparent; border:none;")
        hdr_row.addWidget(hdr, 1)
        copy_btn = QPushButton("Copy System")
        copy_btn.setStyleSheet(_BTN_STYLE)
        copy_btn.clicked.connect(lambda: QApplication.clipboard().setText(system_name))
        hdr_row.addWidget(copy_btn)
        layout.addLayout(hdr_row)

        self._status_label = QLabel("Loading from Spansh…")
        self._status_label.setStyleSheet("color:#9aa4b0; background:transparent; border:none;")
        layout.addWidget(self._status_label)

        self._claim_label = QLabel("")
        self._claim_label.setWordWrap(True)
        self._claim_label.setStyleSheet("color:#FF6B6B; font-weight:bold; background:transparent; border:none;")
        self._claim_label.setVisible(False)
        layout.addWidget(self._claim_label)

        self._economy_summary_label = QLabel("")
        self._economy_summary_label.setWordWrap(True)
        self._economy_summary_label.setStyleSheet("color:#7CFC98; font-weight:bold; background:transparent; border:none;")
        layout.addWidget(self._economy_summary_label)

        self._table = QTableWidget()
        self._table.setColumnCount(8)
        self._table.setHorizontalHeaderLabels(
            ["Body", "Type", "Landable", "Dist (ls)", "Mass (Em)", "Gravity (G)", "Temp (K)", "Likely Economy"]
        )
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet(_TABLE_STYLE)
        h = self._table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
        for c in (2, 3, 4, 5, 6):
            h.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self._table, 1)

        rings_hdr = QLabel("RINGS")
        rings_hdr.setStyleSheet(_HDR_STYLE)
        layout.addWidget(rings_hdr)
        self._rings_label = QLabel("Loading…")
        self._rings_label.setWordWrap(True)
        self._rings_label.setTextFormat(Qt.TextFormat.RichText)
        self._rings_label.setStyleSheet("background:transparent; border:none;")
        layout.addWidget(self._rings_label)

        caveat = QLabel(
            "Community-sourced via Spansh — reflects whoever last scanned each body/ring, not "
            "necessarily current. Likely Economy is a prediction from Update 3's body-attribute "
            "table (strong link only — same body as your port); doesn't account for organics/"
            "geologicals, which need an actual scan. High-value economies (Agriculture/Tourism/"
            "High Tech/Military) highlighted green, Extraction/Industrial/Refinery-only teal."
        )
        caveat.setWordWrap(True)
        caveat.setStyleSheet("color:#9aa4b0; font-size:11px; background:transparent; border:none;")
        layout.addWidget(caveat)

        self._thread = QThread()
        self._worker = _SystemDetailWorker(system_name)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_loaded)
        self._worker.finished.connect(self._thread.quit)
        self._thread.start()

    def _on_loaded(self, bodies: list, error: str, rings: list, mining_signals: dict, system_info: dict) -> None:
        self._render_rings(rings)
        if system_info.get("is_being_colonised") or system_info.get("is_colonised"):
            state = "already colonised" if system_info.get("is_colonised") else "already being colonised"
            self._claim_label.setText(f"⚠ Spansh reports this system is {state} by someone.")
            self._claim_label.setVisible(True)
        if error:
            self._status_label.setText(f"Lookup failed — {error}")
            return
        if not bodies:
            self._status_label.setText(f"No body data on Spansh yet for {self._system_name}.")
            return
        self._status_label.setText(f"{len(bodies)} bodies known:")

        ringed_bodies = {r.get("parent_body") for r in rings if r.get("parent_body")}

        # High-value economies (Agriculture/Tourism/High Tech/Military come
        # from Earth-like/water/ammonia worlds or stellar remnants) get the
        # same green as the rest of the app's "notable" convention;
        # Extraction/Industrial/Refinery-only bodies (rings, gas giants,
        # metal-rich, icy, rocky) get teal -- matches the resources/mining
        # semantic color already used elsewhere (style.py's CARD_VARIANTS).
        _HIGH_VALUE = {"Agriculture", "Tourism", "High Tech", "Military"}

        self._table.setRowCount(len(bodies))
        system_economies: list[str] = []
        for row, b in enumerate(bodies):
            planet_class = b.get("planet_class") or "—"
            name = b.get("name") or "—"
            is_ringed = name in ringed_bodies
            economies = _predict_economies(planet_class, is_ringed)
            for e in economies:
                if e not in system_economies:
                    system_economies.append(e)

            mining_count = mining_signals.get(name)
            suffix = (" 💍" if is_ringed else "") + (f" ⛏️{mining_count}" if mining_count else "")
            name_item = QTableWidgetItem(name + suffix)
            type_item = QTableWidgetItem(planet_class)
            landable = b.get("landable")
            landable_item = QTableWidgetItem("Yes" if landable else ("No" if landable is not None else "—"))
            dist_item = QTableWidgetItem(f"{b.get('distance_ls', 0):,.0f}")
            mass = b.get("mass_em")
            mass_item = QTableWidgetItem(f"{mass:.2f}" if isinstance(mass, (int, float)) else "—")
            gravity = b.get("surface_gravity")
            gravity_item = QTableWidgetItem(f"{gravity / 9.80665:.2f}" if isinstance(gravity, (int, float)) else "—")
            temp = b.get("surface_temperature")
            temp_item = QTableWidgetItem(f"{temp:.0f}" if isinstance(temp, (int, float)) else "—")
            economy_item = QTableWidgetItem(", ".join(economies) if economies else "—")

            for it in (landable_item, dist_item, mass_item, gravity_item, temp_item):
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            color = None
            if any(e in _HIGH_VALUE for e in economies):
                color = "#6BCB77"
            elif economies:
                color = "#6BE6D9"
            if color:
                all_items = (name_item, type_item, landable_item, dist_item, mass_item, gravity_item, temp_item, economy_item)
                for it in all_items:
                    it.setForeground(QColor(color))

            self._table.setItem(row, 0, name_item)
            self._table.setItem(row, 1, type_item)
            self._table.setItem(row, 2, landable_item)
            self._table.setItem(row, 3, dist_item)
            self._table.setItem(row, 4, mass_item)
            self._table.setItem(row, 5, gravity_item)
            self._table.setItem(row, 6, temp_item)
            self._table.setItem(row, 7, economy_item)

        self._economy_summary_label.setText(
            self._confirmed_economy_text if self._confirmed_economy_text
            else f"Likely economy here: {', '.join(system_economies)}" if system_economies
            else "No strong economy signal from known bodies (no ELW/water/ammonia/gas giant/rings/etc. yet)."
        )

    def _render_rings(self, rings: list) -> None:
        if not rings:
            self._rings_label.setText("No rings known on Spansh for this system.")
            return
        # Ring/signal names are Spansh community data, not trusted input --
        # escape before interpolating into RichText (security review finding).
        lines = []
        for r in rings:
            signals = r.get("signals") or []
            sig_txt = ", ".join(
                f"{escape(str(s.get('name')))} x{s.get('count')}" for s in signals if s.get("name")
            )
            ring_name = escape(str(r.get("ring_name") or "—"))
            ring_type = escape(str(r.get("ring_type") or "—"))
            parent_body = escape(str(r.get("parent_body") or "—"))
            reserve_level = escape(str(r.get("reserve_level") or ""))
            line = f"<b>{ring_name}</b> ({ring_type}) — {parent_body}"
            if reserve_level:
                line += f" — {reserve_level} reserves"
            if sig_txt:
                line += f" — hotspots: {sig_txt}"
            lines.append(line)
        self._rings_label.setText("<br>".join(lines))


class ColonisationPanel(QWidget):
    buy_search_requested = pyqtSignal(str)
    eligibility_check_requested = pyqtSignal(str)  # system name to check

    def __init__(self, repo, ship_pad_table=None, commodity_categories=None, raven_pin_store=None, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._ship_pad_table = ship_pad_table
        self._commodity_categories = commodity_categories
        self._raven_pin_store = raven_pin_store
        self._depots: list = []
        self._depot_dialogs: dict = {}
        self._last_state = None
        self._colonisation_candidates: list = []
        self._colonisation_candidates_system: Optional[str] = None
        self._detail_dialogs: dict = {}
        self._raven_dialog: Optional["_RavenColonialDialog"] = None
        self._known_sites: list = []

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 8)
        root.setSpacing(6)

        # ── Current system — one-line at-a-glance ────────────────────────────
        # Purple accent (see edc/ui/style.py's CARD_VARIANTS) to stand out from
        # the neutral-blue cards below -- this is "where you are", not a
        # candidate/tracked-site row. Occupied/economy come straight from live
        # journal state (state.population/system_economy), no lookup needed.
        current_card = QFrame()
        current_card.setStyleSheet(_card_style("purple"))
        current_l = QVBoxLayout(current_card)
        current_l.setContentsMargins(8, 5, 8, 5)
        self._current_system_label = QLabel("Waiting for current system…")
        self._current_system_label.setTextFormat(Qt.TextFormat.RichText)
        self._current_system_label.setStyleSheet("background:transparent; border:none; font-size:12px;")
        current_l.addWidget(self._current_system_label)
        root.addWidget(current_card)

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
            "Docking at a site tracks it automatically, real name and progress included — no "
            "need to add it yourself. Adding one below is only for a checklist before you've "
            "visited; it must match the real station name EXACTLY (pick from Known Sites below, "
            "once you've docked there at least once) or your dock won't be recognised as the "
            "same site and a second, correctly-named row will appear instead."
        )
        colon_note.setWordWrap(True)
        colon_note.setStyleSheet("color:#9aa4b0; font-size:11px; background:transparent; border:none;")
        colon_l.addWidget(colon_note)

        known_sites_row = QHBoxLayout()
        self._known_sites_combo = QComboBox()
        self._known_sites_combo.setStyleSheet("background:#0a1520; color:#c8c8c8; border:1px solid #1e3a5a;")
        self._known_sites_combo.setToolTip(
            "Stations you've personally docked at whose name marks them as a construction site -- "
            "picking one fills in the fields below exactly, avoiding a typo that would stop the app "
            "matching it to the real site once you dock (see the note above)."
        )
        self._known_sites_combo.activated.connect(self._on_known_site_selected)
        known_sites_refresh_btn = QPushButton("⟳")
        known_sites_refresh_btn.setToolTip("Refresh this list from your dock history.")
        known_sites_refresh_btn.setStyleSheet(_BTN_STYLE)
        known_sites_refresh_btn.setFixedWidth(28)
        known_sites_refresh_btn.clicked.connect(self._refresh_known_sites_combo)
        known_sites_row.addWidget(self._known_sites_combo, 1)
        known_sites_row.addWidget(known_sites_refresh_btn)
        colon_l.addLayout(known_sites_row)

        add_row = QHBoxLayout()
        self._depot_system_edit = QLineEdit()
        self._depot_system_edit.setPlaceholderText("System name")
        self._depot_system_edit.setStyleSheet("background:#0a1520; color:#c8c8c8; border:1px solid #1e3a5a;")
        self._depot_system_edit.textChanged.connect(self._on_depot_system_text_changed)
        self._depot_station_edit = QLineEdit()
        self._depot_station_edit.setPlaceholderText("Station/site name")
        self._depot_station_edit.setStyleSheet("background:#0a1520; color:#c8c8c8; border:1px solid #1e3a5a;")
        self._depot_station_completer = QCompleter([])
        self._depot_station_completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._depot_station_completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._depot_station_completer.popup().setStyleSheet(
            "QAbstractItemView { background:#0a1520; color:#c8c8c8; border:1px solid #1e3a5a;"
            " selection-background-color:#1a3a5a; selection-color:#FFB347; }"
        )
        self._depot_station_edit.setCompleter(self._depot_station_completer)
        add_btn = QPushButton("Add")
        add_btn.setStyleSheet(_BTN_STYLE)
        add_btn.clicked.connect(self._on_add_depot_clicked)
        add_row.addWidget(self._depot_system_edit, 1)
        add_row.addWidget(self._depot_station_edit, 1)
        add_row.addWidget(add_btn)
        raven_btn = QPushButton("Raven Colonial…")
        raven_btn.setStyleSheet(_BTN_STYLE)
        raven_btn.setToolTip(
            "View a squad's shared Raven Colonial build (community platform, read-only) -- "
            "paste a ravencolonial.com build link or id."
        )
        raven_btn.clicked.connect(self._open_raven_dialog)
        add_row.addWidget(raven_btn)
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

        # ── Combined resource shopping list — all tracked sites at once ─────
        shop_card = QFrame()
        shop_card.setStyleSheet(_CARD_STYLE)
        shop_l = QVBoxLayout(shop_card)
        shop_l.setContentsMargins(8, 6, 8, 6)
        shop_l.setSpacing(4)

        shop_hdr = QLabel("COMBINED RESOURCE SHOPPING LIST — ALL TRACKED SITES")
        shop_hdr.setStyleSheet(_HDR_STYLE)
        shop_l.addWidget(shop_hdr)

        shop_note = QLabel(
            "Still-needed amounts summed across every tracked site above — one list instead of "
            "checking each site's own breakdown separately."
        )
        shop_note.setWordWrap(True)
        shop_note.setStyleSheet("color:#9aa4b0; font-size:11px; background:transparent; border:none;")
        shop_l.addWidget(shop_note)

        self._shopping_table = QTableWidget()
        self._shopping_table.setColumnCount(4)
        self._shopping_table.setHorizontalHeaderLabels(["Commodity", "Still Needed", "Sites", ""])
        self._shopping_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._shopping_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._shopping_table.verticalHeader().setVisible(False)
        self._shopping_table.verticalHeader().setDefaultSectionSize(20)
        self._shopping_table.setAlternatingRowColors(True)
        self._shopping_table.setStyleSheet(_TABLE_STYLE)
        sh = self._shopping_table.horizontalHeader()
        sh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in (1, 2, 3):
            sh.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self._shopping_table.setMaximumHeight(160)
        shop_l.addWidget(self._shopping_table)

        root.addWidget(shop_card)

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
        self._candidates_table.setColumnCount(4)
        self._candidates_table.setHorizontalHeaderLabels(["System", "Dist (ly)", "Via", ""])
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
        cch.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._candidates_table.setMinimumHeight(160)
        self._candidates_table.setToolTip("Click the System cell to copy its name to the clipboard.")
        self._candidates_table.cellClicked.connect(self._on_candidates_cell_clicked)
        cand_l.addWidget(self._candidates_table, 1)

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

        root.addWidget(cand_card, 1)

        self._refresh_known_sites_combo()

    def refresh(self, state) -> None:
        system_name = getattr(state, "system", None)
        system_changed = system_name != getattr(self._last_state, "system", None)
        self._last_state = state
        self._refresh_current_system(state)
        self._refresh_depots(state)
        if system_changed:
            # Cheap in-memory re-filter of the already-fetched known-sites
            # cache -- no DB hit, safe to run on every system change even
            # though refresh() itself can fire often.
            self._rebuild_known_sites_combo_for_system(system_name)

    def _refresh_current_system(self, state) -> None:
        summary = _current_system_summary(state)
        if summary is None:
            self._current_system_label.setText("Waiting for current system…")
            return
        system_name, occupied_text, occupied_color, economy_text = summary
        self._current_system_label.setText(
            f'<b>CURRENT SYSTEM:</b> {escape(system_name)} &nbsp;—&nbsp; '
            f'<span style="color:{occupied_color};font-weight:bold;">{escape(occupied_text)}</span> '
            f'&nbsp;—&nbsp; {escape(economy_text)}'
        )

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

        self._refresh_shopping_list()

    def _refresh_shopping_list(self) -> None:
        """Sums still-needed amounts for every commodity across every
        tracked depot (not just the current one) -- one list instead of
        opening each site's own detail dialog separately."""
        rows = _aggregate_shopping_list(self._depots)
        self._shopping_table.setRowCount(len(rows))
        for row, (name, amount, site_count) in enumerate(rows):
            name_item = QTableWidgetItem(name)
            amount_item = QTableWidgetItem(f"{amount:,}")
            amount_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            sites_item = QTableWidgetItem(str(site_count))
            sites_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._shopping_table.setItem(row, 0, name_item)
            self._shopping_table.setItem(row, 1, amount_item)
            self._shopping_table.setItem(row, 2, sites_item)

            btn = QPushButton("Find Source")
            btn.setStyleSheet(_BTN_STYLE)
            btn.clicked.connect(lambda _checked=False, n=name: self.buy_search_requested.emit(n))
            self._shopping_table.setCellWidget(row, 3, btn)

        row_h = self._shopping_table.verticalHeader().defaultSectionSize()
        content_h = self._shopping_table.horizontalHeader().height() + len(rows) * row_h + 4
        self._shopping_table.setMaximumHeight(min(content_h, 160) if rows else 60)

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

    def _refresh_known_sites_combo(self) -> None:
        """Re-fetches the full (all-systems) known-sites list from the DB
        -- the ⟳ button's job, and once at construction. Cheap enough to
        call from refresh() too (guarded so it only re-queries on an
        actual system change, see refresh())."""
        try:
            self._known_sites = self._repo.get_known_construction_sites()
        except Exception:
            log.exception("Failed to load known construction sites")
            self._known_sites = []
        self._rebuild_known_sites_combo_for_system(getattr(self._last_state, "system", None))

    def _rebuild_known_sites_combo_for_system(self, system_name) -> None:
        """Filters the cached (already-fetched) known-sites list down to
        the current system only -- a squad tracking sites across many
        systems doesn't need every one of them cluttering this combo when
        only the current system's sites are ever relevant to "add a site
        here". Pure in-memory filter, no DB hit."""
        system_key = (system_name or "").strip().lower()
        matches = [s for s in self._known_sites if s["system_name"].strip().lower() == system_key] if system_key else []

        self._known_sites_combo.blockSignals(True)
        self._known_sites_combo.clear()
        label = f"Known sites in {system_name} ({len(matches)})…" if system_key else "Known sites — waiting for current system…"
        self._known_sites_combo.addItem(label, None)
        for site in matches:
            self._known_sites_combo.addItem(site["station_name"], site)
        self._known_sites_combo.setCurrentIndex(0)
        self._known_sites_combo.blockSignals(False)

    def _on_known_site_selected(self, index: int) -> None:
        site = self._known_sites_combo.itemData(index)
        if not site:
            return
        self._depot_system_edit.setText(site["system_name"])
        self._depot_station_edit.setText(site["station_name"])

    def _on_depot_system_text_changed(self, text: str) -> None:
        """Manual-add flow: once the typed system name exactly matches a
        system we have known sites for, offer their station names in the
        station field's own completer -- a system can have more than one
        construction site (multiple ports being built at once), so this
        narrows the picker instead of leaving it to a full free-text
        guess."""
        system_key = text.strip().lower()
        if not system_key:
            self._depot_station_completer.setModel(None)
            return
        names = sorted({
            s["station_name"] for s in self._known_sites
            if s["system_name"].strip().lower() == system_key
        })
        self._depot_station_completer.setModel(QStringListModel(names))

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

    def _open_raven_dialog(self) -> None:
        if self._raven_dialog is None:
            self._raven_dialog = _RavenColonialDialog(self)
        self._raven_dialog.show()
        self._raven_dialog.raise_()
        self._raven_dialog.activateWindow()

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

            name = c.get("name") or ""
            info_btn = QPushButton("Details")
            info_btn.setStyleSheet(_BTN_STYLE)
            info_btn.clicked.connect(lambda _checked=False, n=name: self._show_system_detail(n))
            self._candidates_table.setCellWidget(row, 3, info_btn)

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

    def _show_system_detail(self, system_name: str) -> None:
        if not system_name:
            return
        dlg = self._detail_dialogs.get(system_name)
        if dlg is None or not dlg.isVisible():
            dlg = _SystemDetailDialog(system_name, self._repo)
            self._detail_dialogs[system_name] = dlg
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _on_candidates_cell_clicked(self, row: int, column: int) -> None:
        if column != 0:  # System
            return
        item = self._candidates_table.item(row, column)
        if item and item.text():
            QApplication.clipboard().setText(item.text())

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
