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
from typing import Optional

from PyQt6.QtCore import Qt, QThread, QObject, pyqtSignal
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
from edc.core.spansh_client import SpanshClient

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
    finished = pyqtSignal(list, str, list, dict)  # bodies, error, rings, mining_signals

    def __init__(self, system_name: str):
        super().__init__()
        self._system_name = system_name

    def run(self):
        client = SpanshClient()
        bodies, error = client.fetch_system_bodies(self._system_name)
        rings: list = []
        mining_signals: dict = {}
        id64, id64_error = client.fetch_system_id64(self._system_name)
        if id64 is not None:
            rings, rings_error, mining_signals = client.fetch_system_rings(id64)
            if rings_error:
                log.warning("Spansh ring fetch failed for %s: %s", self._system_name, rings_error)
        elif id64_error:
            log.warning("Spansh id64 lookup failed for %s: %s", self._system_name, id64_error)
        self.finished.emit(bodies, error, rings, mining_signals)


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


class _SystemDetailDialog(QDialog):
    """Non-modal window showing a candidate system's body and ring list from
    Spansh -- planet types, water worlds/ELWs, landable flags, distance,
    ring presence/hotspots -- the things a player normally checks before
    deciding whether a system is worth building in. Fetches in the
    background so opening it never blocks the UI; shown immediately in a
    loading state."""

    def __init__(self, system_name: str):
        super().__init__(None)
        self.setStyleSheet("QDialog { background:#080f18; color:#c8c8c8; }")
        self.setWindowTitle(f"System Detail — {system_name}")
        self.resize(760, 460)
        self._system_name = system_name

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

    def _on_loaded(self, bodies: list, error: str, rings: list, mining_signals: dict) -> None:
        self._render_rings(rings)
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
            f"Likely economy here: {', '.join(system_economies)}" if system_economies
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
            line = f"<b>{ring_name}</b> ({ring_type}) — {parent_body}"
            if sig_txt:
                line += f" — hotspots: {sig_txt}"
            lines.append(line)
        self._rings_label.setText("<br>".join(lines))


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
        self._detail_dialogs: dict = {}

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
            dlg = _SystemDetailDialog(system_name)
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
