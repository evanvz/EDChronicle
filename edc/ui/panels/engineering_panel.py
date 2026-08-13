"""Engineering panel — Ships (blueprint wishlist) and Suits & Weapons
(Odyssey on-foot grade/module tracking) sub-tabs, each a master-detail
split: wishlist on the left, materials + engineer info on the right."""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QComboBox, QSpinBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QFrame, QTabWidget, QScrollArea,
)

from edc.core.engineering_blueprints import EngineeringBlueprintTable
from edc.core.engineering_wishlist import EngineeringWishlist
from edc.core.experimental_effects import ExperimentalEffectsTable
from edc.core.material_trading import find_material_trades
from edc.core.odyssey_engineering import OdysseyEngineeringTable
from edc.core.odyssey_material_source import is_bartender_tradeable
from edc.core.odyssey_wishlist import OdysseyWishlist
from edc.ui.formatting import relative_time

log = logging.getLogger(__name__)

_CATEGORY_STATE_ATTR = {
    "raw": "materials_raw",
    "manufactured": "materials_manufactured",
    "encoded": "materials_encoded",
}

_CARD_STYLE = "QFrame { background:#0d1a2a; border:1px solid #1e3a5a; border-radius:5px; }"
_HDR_STYLE = "color:#7a7a7a; font-size:12px; font-weight:bold; letter-spacing:1px; background:transparent; border:none;"
_LABEL_STYLE = "background:transparent; border:none; color:#c8c8c8;"
_COMBO_STYLE = "background:#0a1520; color:#c8c8c8; border:1px solid #1e3a5a;"
_TABLE_STYLE = (
    "QTableWidget { background:#080f18; alternate-background-color:#0a1520;"
    " gridline-color:#1e3a5a; border:1px solid #1e3a5a; }"
    "QHeaderView::section { background:#0d1a2a; color:#888888; border:none;"
    " padding:3px; font-size:12px; font-weight:bold; letter-spacing:1px; }"
    "QTableWidget::item:selected { background:#1a3a5a; color:#FFB347; }"
)


def _format_age(last_updated: str, last_visited: str) -> tuple[str, float]:
    """Compact 'listing age / carrier-location age' for the carrier
    table's Age column -- last_updated is when this material listing was
    last seen on EDDN, last_visited is when we last had a Docked sighting
    of the carrier itself (it may have moved since). Returns (display_text,
    sort_value) -- sort_value is the older (larger) of the two ages in
    seconds, since that's the single number that best represents "how
    stale is this row overall" for column sorting."""
    listed, listed_secs = relative_time(last_updated)
    visited, visited_secs = relative_time(last_visited)
    text = f"{listed.replace(' ago', '')} / {visited.replace(' ago', '')}"
    return text, max(listed_secs, visited_secs)


def _make_table(headers: List[str]) -> QTableWidget:
    t = QTableWidget()
    t.setColumnCount(len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    t.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    t.verticalHeader().setVisible(False)
    t.setAlternatingRowColors(True)
    t.setSortingEnabled(True)
    t.setStyleSheet(_TABLE_STYLE)
    return t


class _NumericTableWidgetItem(QTableWidgetItem):
    """Sorts by an actual numeric value instead of the displayed string
    (plain QTableWidgetItem sorting would put "42.0" before "9.0")."""

    def __init__(self, text: str, sort_value: float):
        super().__init__(text)
        self._sort_value = sort_value

    def __lt__(self, other):
        if isinstance(other, _NumericTableWidgetItem):
            return self._sort_value < other._sort_value
        return super().__lt__(other)


def _humanized_fdname_suffix(fdname: str) -> str:
    """"FSD_LongRange" -> "Long Range" — the internal/community name
    players often search by, which doesn't always match Frontier's
    in-game blueprint name (e.g. that one's actually "Increased range")."""
    suffix = fdname.split("_", 1)[1] if "_" in fdname else fdname
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", suffix)


def _blueprint_label(bp: Dict[str, Any], fdname: str) -> str:
    display_name = bp.get("display_name", fdname)
    short_name = bp.get("short_name", "")
    community_name = _humanized_fdname_suffix(fdname)
    label = f"{display_name} — {short_name}"
    if community_name.strip().lower() != short_name.strip().lower():
        label += f" ({community_name})"
    return label


class EngineeringPanel(QWidget):
    """Owns the Engineering tab: a QTabWidget with Ships and Suits & Weapons
    sub-tabs. Receives state via refresh(state)."""

    def __init__(
        self,
        blueprint_table: EngineeringBlueprintTable,
        wishlist_store: EngineeringWishlist,
        odyssey_table: OdysseyEngineeringTable,
        odyssey_wishlist_store: OdysseyWishlist,
        experimental_effects: ExperimentalEffectsTable,
        repo,
        cfg,
        parent=None,
    ):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(
            "QTabWidget::pane { border:1px solid #1e3a5a; background:#080f18; }"
            "QTabBar::tab { background:#0d1a2a; color:#888888; padding:5px 14px;"
            " border:1px solid #1e3a5a; border-bottom:none; margin-right:2px; }"
            "QTabBar::tab:selected { background:#080f18; color:#FFB347; border-bottom:1px solid #080f18; }"
            "QTabBar::tab:hover { color:#c8c8c8; }"
        )
        root.addWidget(self._tabs)

        self._ship_tab = _ShipEngineeringTab(blueprint_table, wishlist_store, experimental_effects, repo, cfg)
        self._odyssey_tab = _OdysseyEngineeringTab(odyssey_table, blueprint_table, odyssey_wishlist_store, repo, cfg)
        self._engineers_tab = _EngineersTab(blueprint_table)
        self._tabs.addTab(self._ship_tab, "Ships")
        self._tabs.addTab(self._odyssey_tab, "Suits & Weapons")
        self._tabs.addTab(self._engineers_tab, "Engineers")

    def missing_materials_for_wishlist(self) -> Dict[str, int]:
        """Ship-only — used by main_window's farming-location alert hook."""
        return self._ship_tab.missing_materials_for_wishlist()

    def refresh(self, state) -> None:
        self._ship_tab.refresh(state)
        self._odyssey_tab.refresh(state)
        self._engineers_tab.refresh(state)


class _ShipEngineeringTab(QWidget):
    def __init__(
        self,
        blueprint_table: EngineeringBlueprintTable,
        wishlist_store: EngineeringWishlist,
        experimental_effects: ExperimentalEffectsTable,
        repo,
        cfg,
        parent=None,
    ):
        super().__init__(parent)
        self.setStyleSheet("background:#080f18;")
        self._blueprints = blueprint_table
        self._store = wishlist_store
        self._effects = experimental_effects
        self._repo = repo
        self._cfg = cfg
        self._wishlist: List[Dict[str, Any]] = self._store.load()
        self._state = None

        root = QHBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 8)
        root.setSpacing(8)

        # ── Left column: add form + wishlist ────────────────────────────
        left = QVBoxLayout()
        left.setSpacing(6)

        add_frame = QFrame()
        add_frame.setStyleSheet(_CARD_STYLE)
        add_layout = QVBoxLayout(add_frame)
        add_layout.setContentsMargins(8, 6, 8, 8)
        add_layout.setSpacing(6)

        hdr = QLabel("BLUEPRINT WISHLIST")
        hdr.setStyleSheet(_HDR_STYLE)
        add_layout.addWidget(hdr)

        self._bp_combo = QComboBox()
        self._bp_combo.setStyleSheet(_COMBO_STYLE)
        self._bp_fdnames: List[str] = self._blueprints.blueprint_names()
        for fdname in self._bp_fdnames:
            bp = self._blueprints.get(fdname) or {}
            self._bp_combo.addItem(_blueprint_label(bp, fdname), fdname)
        self._bp_combo.currentIndexChanged.connect(self._on_blueprint_changed)
        add_layout.addWidget(self._bp_combo)

        grade_row = QHBoxLayout()
        grade_label = QLabel("Grade:")
        grade_label.setStyleSheet(_LABEL_STYLE)
        self._grade_spin = QSpinBox()
        self._grade_spin.setRange(1, 5)
        self._grade_spin.setStyleSheet(_COMBO_STYLE)
        add_btn = QPushButton("Add")
        add_btn.setStyleSheet(
            "QPushButton { background:#1a3a5a; color:#FFB347; border:1px solid #2a5a8a;"
            " border-radius:3px; padding:3px 12px; font-weight:bold; }"
            "QPushButton:hover { background:#2a5a8a; }"
        )
        add_btn.clicked.connect(self._add_to_wishlist)
        grade_row.addWidget(grade_label)
        grade_row.addWidget(self._grade_spin, 1)
        grade_row.addWidget(add_btn)
        add_layout.addLayout(grade_row)

        self._weapon_type_row = QHBoxLayout()
        self._weapon_type_label = QLabel("Weapon Type:")
        self._weapon_type_label.setStyleSheet(_LABEL_STYLE)
        self._weapon_type_combo = QComboBox()
        self._weapon_type_combo.setStyleSheet(_COMBO_STYLE)
        self._weapon_type_combo.addItem("— Any weapon —", None)
        for name in self._effects.weapon_type_names():
            self._weapon_type_combo.addItem(name, name)
        self._weapon_type_row.addWidget(self._weapon_type_label)
        self._weapon_type_row.addWidget(self._weapon_type_combo, 1)
        add_layout.addLayout(self._weapon_type_row)
        self._weapon_type_combo.currentIndexChanged.connect(self._on_weapon_type_changed)

        effect_row = QHBoxLayout()
        effect_label = QLabel("Experimental:")
        effect_label.setStyleSheet(_LABEL_STYLE)
        self._effect_combo = QComboBox()
        self._effect_combo.setStyleSheet(_COMBO_STYLE)
        effect_row.addWidget(effect_label)
        effect_row.addWidget(self._effect_combo, 1)
        add_layout.addLayout(effect_row)

        self._effect_note = QLabel("")
        self._effect_note.setWordWrap(True)
        self._effect_note.setStyleSheet("color:#FF8C00; font-size:11px; background:transparent; border:none;")
        add_layout.addWidget(self._effect_note)
        self._effect_combo.currentIndexChanged.connect(self._on_effect_changed)

        left.addWidget(add_frame)
        self._on_blueprint_changed()

        wl_hdr_row = QHBoxLayout()
        wl_hdr = QLabel("TRACKED BUILDS")
        wl_hdr.setStyleSheet(_HDR_STYLE)
        wl_hdr_row.addWidget(wl_hdr)
        wl_hdr_row.addStretch()
        remove_btn = QPushButton("Remove")
        remove_btn.setStyleSheet(
            "QPushButton { background:#2a1010; color:#FF8080; border:1px solid #5a2a2a;"
            " border-radius:3px; padding:2px 10px; }"
            "QPushButton:hover { background:#3a1818; }"
        )
        remove_btn.clicked.connect(self._remove_selected)
        wl_hdr_row.addWidget(remove_btn)
        left.addLayout(wl_hdr_row)

        self._wl_table = _make_table(["Blueprint", "Grade", "Status"])
        h = self._wl_table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._wl_table.itemSelectionChanged.connect(self._refresh_detail_table)
        left.addWidget(self._wl_table, 1)

        root.addLayout(left, 2)

        # ── Right column: materials + engineer detail ───────────────────
        right = QVBoxLayout()
        right.setSpacing(6)

        detail_hdr = QLabel("MATERIALS REQUIRED")
        detail_hdr.setStyleSheet(_HDR_STYLE)
        right.addWidget(detail_hdr)

        self._detail_table = _make_table(["Material", "Type", "Held", "Required"])
        dh = self._detail_table.horizontalHeader()
        dh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        dh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        dh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        dh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        right.addWidget(self._detail_table, 1)

        eng_hdr = QLabel("AVAILABLE FROM — CLOSEST FIRST")
        eng_hdr.setStyleSheet(_HDR_STYLE)
        right.addWidget(eng_hdr)

        self._engineer_table = _make_table(["Engineer", "System", "Dist (ly)", "Unlock Status"])
        eh = self._engineer_table.horizontalHeader()
        eh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        eh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        eh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        eh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        right.addWidget(self._engineer_table, 1)

        self._engineer_note = QLabel(
            "Coverage of which engineer offers which blueprint is community-sourced "
            "and not 100% complete — an empty list means unknown, not unavailable."
        )
        self._engineer_note.setWordWrap(True)
        self._engineer_note.setStyleSheet("color:#7a7a7a; font-size:11px; background:transparent; border:none;")
        right.addWidget(self._engineer_note)

        carrier_hdr = QLabel("SOLD BY CARRIERS — CLOSEST FIRST")
        carrier_hdr.setStyleSheet(_HDR_STYLE)
        right.addWidget(carrier_hdr)

        self._carrier_table = _make_table(["Material", "Carrier", "System", "Dist (ly)", "Price", "Stock", "Age"])
        ch = self._carrier_table.horizontalHeader()
        ch.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        ch.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        ch.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        ch.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        ch.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        ch.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        ch.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        right.addWidget(self._carrier_table, 1)

        self._carrier_note = QLabel("")
        self._carrier_note.setWordWrap(True)
        self._carrier_note.setStyleSheet("color:#7a7a7a; font-size:11px; background:transparent; border:none;")
        right.addWidget(self._carrier_note)

        trade_hdr = QLabel("MATERIAL TRADER SUGGESTIONS")
        trade_hdr.setStyleSheet(_HDR_STYLE)
        right.addWidget(trade_hdr)

        self._trade_table = _make_table(["Short On", "Suggested Trade"])
        tth = self._trade_table.horizontalHeader()
        tth.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        tth.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        right.addWidget(self._trade_table, 1)

        root.addLayout(right, 3)

    # ── Helpers ──────────────────────────────────────────────────────────

    def _on_blueprint_changed(self):
        fdname = self._bp_combo.currentData()
        if fdname:
            max_g = self._blueprints.max_grade(fdname) or 5
            self._grade_spin.setMaximum(max_g)

        is_weapon = self._effects.blueprint_category(fdname or "") == "weapon"
        self._weapon_type_label.setVisible(is_weapon)
        self._weapon_type_combo.setVisible(is_weapon)
        if not is_weapon:
            self._weapon_type_combo.blockSignals(True)
            self._weapon_type_combo.setCurrentIndex(0)
            self._weapon_type_combo.blockSignals(False)

        self._repopulate_effect_combo()

    def _repopulate_effect_combo(self):
        fdname = self._bp_combo.currentData()
        weapon_type = self._weapon_type_combo.currentData()
        self._effect_combo.blockSignals(True)
        self._effect_combo.clear()
        self._effect_combo.addItem("— None —", None)
        for edname, label in self._effects.effect_names_for_blueprint(fdname or "", weapon_type):
            self._effect_combo.addItem(label, edname)
        self._effect_combo.setCurrentIndex(0)
        self._effect_combo.blockSignals(False)
        self._on_effect_changed()

    def _on_weapon_type_changed(self):
        self._repopulate_effect_combo()

    def _on_effect_changed(self):
        edname = self._effect_combo.currentData()
        if edname and not self._effects.has_known_cost(edname):
            self._effect_note.setText("No known material cost for this effect — coriolis-data gap.")
        else:
            self._effect_note.setText("")

    def _held_count(self, symbol: str) -> int:
        if self._state is None:
            return 0
        cat = self._blueprints.material_type(symbol).strip().lower()
        attr = _CATEGORY_STATE_ATTR.get(cat)
        if not attr:
            return 0
        src = getattr(self._state, attr, {}) or {}
        return int(src.get(symbol.lower(), 0))

    def _combined_requirements(self, entry: Dict[str, Any]) -> Dict[str, int]:
        """Blueprint cumulative requirements plus the chosen Experimental
        Effect's flat material cost (if any), summed per material."""
        reqs = dict(self._blueprints.cumulative_requirements(entry["fdname"], entry["grade"]))
        experimental = entry.get("experimental")
        if experimental:
            for sym, qty in self._effects.requirements(experimental).items():
                reqs[sym] = reqs.get(sym, 0) + qty
        return reqs

    def _missing_count(self, entry: Dict[str, Any]) -> int:
        reqs = self._combined_requirements(entry)
        return sum(1 for sym, qty in reqs.items() if self._held_count(sym) < qty)

    def missing_materials_for_wishlist(self) -> Dict[str, int]:
        shortfall: Dict[str, int] = {}
        for entry in self._wishlist:
            reqs = self._combined_requirements(entry)
            for sym, qty in reqs.items():
                need = qty - self._held_count(sym)
                if need > 0:
                    shortfall[sym] = max(shortfall.get(sym, 0), need)
        return shortfall

    def _add_to_wishlist(self):
        fdname = self._bp_combo.currentData()
        if not fdname:
            return
        grade = self._grade_spin.value()
        experimental = self._effect_combo.currentData()
        is_weapon = self._effects.blueprint_category(fdname) == "weapon"
        weapon_type = self._weapon_type_combo.currentData() if is_weapon else None
        if any(
            e["fdname"] == fdname and e["grade"] == grade
            and e.get("experimental") == experimental and e.get("weapon_type") == weapon_type
            for e in self._wishlist
        ):
            return
        self._wishlist.append({
            "fdname": fdname, "grade": grade,
            "experimental": experimental, "weapon_type": weapon_type,
        })
        self._store.save(self._wishlist)
        self._refresh_wishlist_table()

    def _selected_wishlist_entry(self) -> Optional[Dict[str, Any]]:
        item = self._wl_table.currentItem()
        if item is None:
            return None
        # Any column's item on the selected row carries the same UserRole
        # data (only column 0 is explicitly set) -- currentItem() can
        # return any column depending on which cell was clicked, so look
        # up column 0 of that row explicitly rather than assuming.
        row = item.row()
        col0 = self._wl_table.item(row, 0)
        return col0.data(Qt.ItemDataRole.UserRole) if col0 else None

    def _remove_selected(self):
        entry = self._selected_wishlist_entry()
        if entry is None or entry not in self._wishlist:
            return
        self._wishlist.remove(entry)
        self._store.save(self._wishlist)
        self._refresh_wishlist_table()

    def _refresh_wishlist_table(self):
        selected_entry = self._selected_wishlist_entry()
        self._wl_table.setSortingEnabled(False)
        self._wl_table.setRowCount(len(self._wishlist))
        for r, entry in enumerate(self._wishlist):
            fdname = entry["fdname"]
            grade = entry["grade"]
            bp = self._blueprints.get(fdname) or {}
            label = _blueprint_label(bp, fdname)
            weapon_type = entry.get("weapon_type")
            if weapon_type:
                label += f" [{weapon_type}]"
            experimental = entry.get("experimental")
            if experimental:
                label += f" (+ {self._effects.display_name(experimental)})"
            name_item = QTableWidgetItem(label)
            name_item.setData(Qt.ItemDataRole.UserRole, entry)
            grade_item = _NumericTableWidgetItem(str(grade), grade)
            grade_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            missing = self._missing_count(entry)
            if missing == 0:
                status_item = QTableWidgetItem("Ready")
                status_item.setForeground(QColor("#6BCB77"))
            else:
                status_item = QTableWidgetItem(f"{missing} missing")
                status_item.setForeground(QColor("#FF8C00"))

            self._wl_table.setItem(r, 0, name_item)
            self._wl_table.setItem(r, 1, grade_item)
            self._wl_table.setItem(r, 2, status_item)
        self._wl_table.setSortingEnabled(True)
        # Repopulating destroys/recreates every row, and re-enabling sorting
        # re-applies the active sort -- Qt's selection highlight survives by
        # row number, not by identity, so if the sort places a different
        # entry at that row the highlight silently drifts to it. Restore by
        # matching the captured entry's identity in its post-sort position.
        if selected_entry is not None:
            found_row = None
            for row in range(self._wl_table.rowCount()):
                col0 = self._wl_table.item(row, 0)
                if col0 is not None and col0.data(Qt.ItemDataRole.UserRole) == selected_entry:
                    found_row = row
                    break
            if found_row is not None:
                self._wl_table.setCurrentCell(found_row, 0)
            else:
                self._wl_table.setCurrentCell(-1, -1)
        self._refresh_detail_table()

    def _refresh_detail_table(self):
        entry = self._selected_wishlist_entry()
        if entry is None:
            self._detail_table.setRowCount(0)
            self._refresh_engineer_table()
            self._refresh_carrier_table()
            return
        reqs = self._combined_requirements(entry)
        rows = sorted(reqs.items(), key=lambda kv: self._blueprints.material_name(kv[0]))

        self._detail_table.setSortingEnabled(False)
        self._detail_table.setRowCount(len(rows))
        for r, (sym, qty) in enumerate(rows):
            held = self._held_count(sym)
            name_item = QTableWidgetItem(self._blueprints.material_name(sym))
            type_item = QTableWidgetItem(self._blueprints.material_type(sym))
            held_item = _NumericTableWidgetItem(str(held), held)
            req_item = _NumericTableWidgetItem(str(qty), qty)
            for it in (held_item, req_item):
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            color = QColor("#6BCB77") if held >= qty else QColor("#FF6B6B")
            name_item.setForeground(color)
            held_item.setForeground(color)

            self._detail_table.setItem(r, 0, name_item)
            self._detail_table.setItem(r, 1, type_item)
            self._detail_table.setItem(r, 2, held_item)
            self._detail_table.setItem(r, 3, req_item)
        self._detail_table.setSortingEnabled(True)

        self._refresh_engineer_table()
        self._refresh_carrier_table()

    def _refresh_engineer_table(self):
        entry = self._selected_wishlist_entry()
        if entry is None:
            self._engineer_table.setRowCount(0)
            return
        engineers = self._blueprints.engineers_for(entry["fdname"], entry["grade"])

        # getattr's default only covers a missing attribute — state.system_x
        # can exist but be None (e.g. before any position data has arrived
        # yet), which getattr would pass through unchanged and crash the
        # distance calc below.
        ref_x = getattr(self._state, "system_x", None) if self._state else None
        ref_y = getattr(self._state, "system_y", None) if self._state else None
        ref_z = getattr(self._state, "system_z", None) if self._state else None
        ref_x, ref_y, ref_z = ref_x or 0.0, ref_y or 0.0, ref_z or 0.0
        progress = getattr(self._state, "engineer_progress", {}) or {} if self._state else {}

        rows = []
        for eng_name in engineers:
            home = self._blueprints.engineer_home(eng_name)
            dist = None
            system_name = "—"
            if home and isinstance(home.get("x"), (int, float)):
                dist = ((home["x"] - ref_x) ** 2 + (home["y"] - ref_y) ** 2 + (home["z"] - ref_z) ** 2) ** 0.5
                system_name = home.get("system_name") or "—"

            rec = progress.get(eng_name)
            target_grade = entry["grade"]
            if not rec:
                status_text, status_color = "Not encountered", "#888888"
            else:
                rank = rec.get("rank")
                prog = rec.get("progress") or ""
                if isinstance(rank, int) and rank >= target_grade:
                    status_text, status_color = f"Rank {rank} — ready for grade {target_grade}", "#6BCB77"
                elif isinstance(rank, int):
                    status_text, status_color = f"Rank {rank} — need Rank {target_grade}", "#FF8C00"
                elif prog:
                    status_text, status_color = f"{prog} — not yet unlocked", "#FFB347"
                else:
                    status_text, status_color = "Not encountered", "#888888"

            rows.append((dist, eng_name, system_name, status_text, status_color))

        rows.sort(key=lambda r: (r[0] is None, r[0] if r[0] is not None else 0.0))

        self._engineer_table.setSortingEnabled(False)
        self._engineer_table.setRowCount(len(rows))
        for r, (dist, eng_name, system_name, status_text, status_color) in enumerate(rows):
            name_item = QTableWidgetItem(eng_name)
            sys_item = QTableWidgetItem(system_name)
            dist_item = _NumericTableWidgetItem(
                f"{dist:.1f}" if dist is not None else "—", dist if dist is not None else float("inf")
            )
            dist_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            status_item = QTableWidgetItem(status_text)
            status_item.setForeground(QColor(status_color))

            self._engineer_table.setItem(r, 0, name_item)
            self._engineer_table.setItem(r, 1, sys_item)
            self._engineer_table.setItem(r, 2, dist_item)
            self._engineer_table.setItem(r, 3, status_item)
        self._engineer_table.setSortingEnabled(True)

    def _refresh_carrier_table(self):
        entry = self._selected_wishlist_entry()
        if entry is None:
            self._carrier_table.setRowCount(0)
            self._carrier_note.setText("")
            return
        reqs = self._combined_requirements(entry)
        missing_symbols = [sym for sym, qty in reqs.items() if self._held_count(sym) < qty]
        if not missing_symbols:
            self._carrier_table.setRowCount(0)
            self._carrier_note.setText("All required materials already held.")
            return

        ref_x = getattr(self._state, "system_x", None) if self._state else None
        ref_y = getattr(self._state, "system_y", None) if self._state else None
        ref_z = getattr(self._state, "system_z", None) if self._state else None
        if ref_x is None or ref_y is None or ref_z is None:
            self._carrier_table.setRowCount(0)
            self._carrier_note.setText("Current position unknown.")
            return

        radius = float(getattr(self._cfg, "market_search_radius_ly", 100) or 100)
        current_market_id = getattr(self._state, "current_market_id", None) if self._state else None
        try:
            by_symbol = self._repo.search_fleet_carrier_materials(
                missing_symbols, ref_x, ref_y, ref_z, radius, exclude_market_id=current_market_id,
            )
        except Exception:
            log.exception("Failed to search fleet carrier materials")
            self._carrier_table.setRowCount(0)
            self._carrier_note.setText("Carrier search failed — see log.")
            return

        rows = []
        for sym, listings in by_symbol.items():
            mat_name = self._blueprints.material_name(sym)
            for listing in listings:
                rows.append((mat_name, listing))
        rows.sort(key=lambda r: r[1]["distance_ly"])

        self._carrier_table.setSortingEnabled(False)
        self._carrier_table.setRowCount(len(rows))
        for r, (mat_name, listing) in enumerate(rows):
            name_item = QTableWidgetItem(listing['carrier_name'])
            mat_item = QTableWidgetItem(mat_name)
            sys_item = QTableWidgetItem(listing["system_name"])
            dist_item = _NumericTableWidgetItem(f"{listing['distance_ly']:.1f}", listing['distance_ly'])
            dist_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            price = listing.get("price")
            price_item = _NumericTableWidgetItem(
                f"{price:,}" if isinstance(price, int) else "—", price if isinstance(price, int) else float("inf")
            )
            price_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            stock = listing.get("stock")
            stock_item = _NumericTableWidgetItem(
                str(stock) if isinstance(stock, int) else "—", stock if isinstance(stock, int) else float("inf")
            )
            stock_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            age_text, age_sort = _format_age(listing.get("last_updated"), listing.get("last_visited"))
            age_item = _NumericTableWidgetItem(age_text, age_sort)
            age_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            self._carrier_table.setItem(r, 0, mat_item)
            self._carrier_table.setItem(r, 1, name_item)
            self._carrier_table.setItem(r, 2, sys_item)
            self._carrier_table.setItem(r, 3, dist_item)
            self._carrier_table.setItem(r, 4, price_item)
            self._carrier_table.setItem(r, 5, stock_item)
            self._carrier_table.setItem(r, 6, age_item)
        self._carrier_table.setSortingEnabled(True)

        staleness_note = "Carrier listings/locations are crowdsourced from EDDN and can be several days old."
        self._carrier_note.setText(
            staleness_note if rows else
            f"No carriers found selling these materials within {radius:.0f} ly. {staleness_note}"
        )

    def _refresh_trade_suggestions(self) -> None:
        owned: Dict[str, int] = {}
        for attr in _CATEGORY_STATE_ATTR.values():
            owned.update(getattr(self._state, attr, {}) or {})
        shortfalls = self.missing_materials_for_wishlist()
        suggestions = find_material_trades(shortfalls, owned)

        rows = sorted(suggestions.items(), key=lambda kv: self._blueprints.material_name(kv[0]))
        self._trade_table.setSortingEnabled(False)
        self._trade_table.setRowCount(len(rows))
        for r, (sym, sugg) in enumerate(rows):
            need_item = QTableWidgetItem(f"{self._blueprints.material_name(sym)} (short {shortfalls[sym]})")
            cover = "" if sugg["full_cover"] else f" — covers {sugg['missing_covered']}/{shortfalls[sym]}"
            trade_item = QTableWidgetItem(
                f"Trade {sugg['source_qty_used']}x {self._blueprints.material_name(sugg['source'])}"
                f" ({sugg['source_spare']} spare){cover}"
            )
            color = QColor("#6BCB77") if sugg["full_cover"] else QColor("#FFB347")
            need_item.setForeground(color)
            trade_item.setForeground(color)
            self._trade_table.setItem(r, 0, need_item)
            self._trade_table.setItem(r, 1, trade_item)
        self._trade_table.setSortingEnabled(True)

    def refresh(self, state) -> None:
        self._state = state
        self._refresh_wishlist_table()
        self._refresh_trade_suggestions()


_KIND_LABELS = {
    "suit_grade": "Suit Grade",
    "weapon_grade": "Weapon Grade",
    "suit_module": "Suit Mod",
    "weapon_module": "Weapon Mod",
}


class _OdysseyEngineeringTab(QWidget):
    """
    Suit/weapon grade upgrades cost materials at every step 1->5 and can be
    performed at any on-foot Engineer terminal. Modules (mod slots) are a
    single material cost each, gated to specific Engineers, and once
    applied can't be swapped — so unlike ship blueprints there's no
    "held/required" retry loop once you've committed.
    """

    def __init__(
        self,
        odyssey_table: OdysseyEngineeringTable,
        blueprint_table: EngineeringBlueprintTable,
        wishlist_store: OdysseyWishlist,
        repo,
        cfg,
        parent=None,
    ):
        super().__init__(parent)
        self.setStyleSheet("background:#080f18;")
        self._table = odyssey_table
        self._blueprints = blueprint_table  # for engineer_home() lookups only
        self._store = wishlist_store
        self._repo = repo
        self._cfg = cfg
        self._wishlist: List[Dict[str, Any]] = self._store.load()
        self._state = None

        root = QHBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 8)
        root.setSpacing(8)

        # ── Left column: add form + wishlist ────────────────────────────
        left = QVBoxLayout()
        left.setSpacing(6)

        add_frame = QFrame()
        add_frame.setStyleSheet(_CARD_STYLE)
        add_layout = QVBoxLayout(add_frame)
        add_layout.setContentsMargins(8, 6, 8, 8)
        add_layout.setSpacing(6)

        hdr = QLabel("ODYSSEY WISHLIST")
        hdr.setStyleSheet(_HDR_STYLE)
        add_layout.addWidget(hdr)

        self._kind_combo = QComboBox()
        self._kind_combo.setStyleSheet(_COMBO_STYLE)
        for kind, label in _KIND_LABELS.items():
            self._kind_combo.addItem(label, kind)
        self._kind_combo.currentIndexChanged.connect(self._on_kind_changed)
        add_layout.addWidget(self._kind_combo)

        self._item_combo = QComboBox()
        self._item_combo.setStyleSheet(_COMBO_STYLE)
        add_layout.addWidget(self._item_combo)

        grade_row = QHBoxLayout()
        self._grade_label = QLabel("Target grade:")
        self._grade_label.setStyleSheet(_LABEL_STYLE)
        self._grade_spin = QSpinBox()
        self._grade_spin.setRange(2, 5)
        self._grade_spin.setStyleSheet(_COMBO_STYLE)
        add_btn = QPushButton("Add")
        add_btn.setStyleSheet(
            "QPushButton { background:#1a3a5a; color:#FFB347; border:1px solid #2a5a8a;"
            " border-radius:3px; padding:3px 12px; font-weight:bold; }"
            "QPushButton:hover { background:#2a5a8a; }"
        )
        add_btn.clicked.connect(self._add_to_wishlist)
        grade_row.addWidget(self._grade_label)
        grade_row.addWidget(self._grade_spin, 1)
        grade_row.addWidget(add_btn)
        add_layout.addLayout(grade_row)

        left.addWidget(add_frame)
        self._on_kind_changed()

        wl_hdr_row = QHBoxLayout()
        wl_hdr = QLabel("TRACKED TARGETS")
        wl_hdr.setStyleSheet(_HDR_STYLE)
        wl_hdr_row.addWidget(wl_hdr)
        wl_hdr_row.addStretch()
        remove_btn = QPushButton("Remove")
        remove_btn.setStyleSheet(
            "QPushButton { background:#2a1010; color:#FF8080; border:1px solid #5a2a2a;"
            " border-radius:3px; padding:2px 10px; }"
            "QPushButton:hover { background:#3a1818; }"
        )
        remove_btn.clicked.connect(self._remove_selected)
        wl_hdr_row.addWidget(remove_btn)
        left.addLayout(wl_hdr_row)

        self._wl_table = _make_table(["Item", "Kind", "Status"])
        h = self._wl_table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self._wl_table.itemSelectionChanged.connect(self._refresh_detail_table)
        left.addWidget(self._wl_table, 1)

        root.addLayout(left, 2)

        # ── Right column: materials + engineer detail ───────────────────
        right = QVBoxLayout()
        right.setSpacing(6)

        detail_hdr = QLabel("MATERIALS REQUIRED")
        detail_hdr.setStyleSheet(_HDR_STYLE)
        right.addWidget(detail_hdr)

        self._detail_table = _make_table(["Material", "Held", "Required", "Source"])
        dh = self._detail_table.horizontalHeader()
        dh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        dh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        dh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        dh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        right.addWidget(self._detail_table, 1)

        eng_hdr = QLabel("AVAILABLE FROM — CLOSEST FIRST")
        eng_hdr.setStyleSheet(_HDR_STYLE)
        right.addWidget(eng_hdr)

        self._engineer_table = _make_table(["Engineer", "System", "Dist (ly)"])
        eh = self._engineer_table.horizontalHeader()
        eh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        eh.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        eh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        right.addWidget(self._engineer_table, 1)

        self._engineer_note = QLabel("")
        self._engineer_note.setWordWrap(True)
        self._engineer_note.setStyleSheet("color:#7a7a7a; font-size:11px; background:transparent; border:none;")
        right.addWidget(self._engineer_note)

        carrier_hdr = QLabel("SOLD BY CARRIERS — CLOSEST FIRST")
        carrier_hdr.setStyleSheet(_HDR_STYLE)
        right.addWidget(carrier_hdr)

        self._carrier_table = _make_table(["Material", "Carrier", "System", "Dist (ly)", "Price", "Stock", "Age"])
        ch = self._carrier_table.horizontalHeader()
        ch.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        ch.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        ch.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        ch.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        ch.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        ch.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        ch.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        right.addWidget(self._carrier_table, 1)

        self._carrier_note = QLabel("")
        self._carrier_note.setWordWrap(True)
        self._carrier_note.setStyleSheet("color:#7a7a7a; font-size:11px; background:transparent; border:none;")
        right.addWidget(self._carrier_note)

        root.addLayout(right, 3)

    # ── Helpers ──────────────────────────────────────────────────────────

    def _on_kind_changed(self):
        kind = self._kind_combo.currentData()
        is_grade = kind in ("suit_grade", "weapon_grade")
        self._grade_label.setVisible(is_grade)
        self._grade_spin.setVisible(is_grade)

        self._item_combo.clear()
        if kind == "suit_grade":
            for name in self._table.suit_names():
                self._item_combo.addItem(name, name)
        elif kind == "weapon_grade":
            for name in self._table.weapon_names():
                self._item_combo.addItem(name, name)
        elif kind == "suit_module":
            for key in self._table.suit_module_keys():
                self._item_combo.addItem(self._table.module_display_name("suit", key), key)
        elif kind == "weapon_module":
            for key in self._table.weapon_module_keys():
                self._item_combo.addItem(self._table.module_display_name("weapon", key), key)

    def _held_count(self, symbol: str) -> int:
        if self._state is None:
            return 0
        src = getattr(self._state, "shiplocker_items", None) or {}
        return int(src.get(symbol.lower(), 0))

    def _material_name(self, symbol: str) -> str:
        loc = getattr(self._state, "shiplocker_localised", None) or {} if self._state else {}
        localised = loc.get(symbol.lower())
        if localised:
            return localised
        return self._table.material_display_name(symbol) or symbol

    def _requirements_for(self, entry: Dict[str, Any]) -> Dict[str, int]:
        kind = entry["kind"]
        if kind == "suit_grade":
            return self._table.suit_cumulative_requirements(entry["name"], entry["grade"])
        if kind == "weapon_grade":
            return self._table.weapon_cumulative_requirements(entry["name"], entry["grade"])
        if kind == "suit_module":
            return self._table.module_requirements("suit", entry["name"])
        if kind == "weapon_module":
            return self._table.module_requirements("weapon", entry["name"])
        return {}

    def _missing_count(self, entry: Dict[str, Any]) -> int:
        reqs = self._requirements_for(entry)
        return sum(1 for sym, qty in reqs.items() if self._held_count(sym) < qty)

    def _add_to_wishlist(self):
        kind = self._kind_combo.currentData()
        name = self._item_combo.currentData()
        if not kind or not name:
            return
        entry = {"kind": kind, "name": name}
        if kind in ("suit_grade", "weapon_grade"):
            entry["grade"] = self._grade_spin.value()
        if any(e == entry for e in self._wishlist):
            return
        self._wishlist.append(entry)
        self._store.save(self._wishlist)
        self._refresh_wishlist_table()

    def _selected_wishlist_entry(self) -> Optional[Dict[str, Any]]:
        item = self._wl_table.currentItem()
        if item is None:
            return None
        # Any column's item on the selected row carries the same UserRole
        # data (only column 0 is explicitly set) -- currentItem() can
        # return any column depending on which cell was clicked, so look
        # up column 0 of that row explicitly rather than assuming.
        row = item.row()
        col0 = self._wl_table.item(row, 0)
        return col0.data(Qt.ItemDataRole.UserRole) if col0 else None

    def _remove_selected(self):
        entry = self._selected_wishlist_entry()
        if entry is None or entry not in self._wishlist:
            return
        self._wishlist.remove(entry)
        self._store.save(self._wishlist)
        self._refresh_wishlist_table()

    def _display_name(self, entry: Dict[str, Any]) -> str:
        kind = entry["kind"]
        if kind == "suit_grade":
            return f"{entry['name']} (grade {entry['grade']})"
        if kind == "weapon_grade":
            return f"{entry['name']} (grade {entry['grade']})"
        if kind == "suit_module":
            return self._table.module_display_name("suit", entry["name"])
        if kind == "weapon_module":
            return self._table.module_display_name("weapon", entry["name"])
        return entry["name"]

    def _refresh_wishlist_table(self):
        selected_entry = self._selected_wishlist_entry()
        self._wl_table.setSortingEnabled(False)
        self._wl_table.setRowCount(len(self._wishlist))
        for r, entry in enumerate(self._wishlist):
            name_item = QTableWidgetItem(self._display_name(entry))
            name_item.setData(Qt.ItemDataRole.UserRole, entry)
            kind_item = QTableWidgetItem(_KIND_LABELS.get(entry["kind"], entry["kind"]))

            missing = self._missing_count(entry)
            if missing == 0:
                status_item = QTableWidgetItem("Ready")
                status_item.setForeground(QColor("#6BCB77"))
            else:
                status_item = QTableWidgetItem(f"{missing} missing")
                status_item.setForeground(QColor("#FF8C00"))

            self._wl_table.setItem(r, 0, name_item)
            self._wl_table.setItem(r, 1, kind_item)
            self._wl_table.setItem(r, 2, status_item)
        self._wl_table.setSortingEnabled(True)
        # Repopulating destroys/recreates every row, and re-enabling sorting
        # re-applies the active sort -- Qt's selection highlight survives by
        # row number, not by identity, so if the sort places a different
        # entry at that row the highlight silently drifts to it. Restore by
        # matching the captured entry's identity in its post-sort position.
        if selected_entry is not None:
            found_row = None
            for row in range(self._wl_table.rowCount()):
                col0 = self._wl_table.item(row, 0)
                if col0 is not None and col0.data(Qt.ItemDataRole.UserRole) == selected_entry:
                    found_row = row
                    break
            if found_row is not None:
                self._wl_table.setCurrentCell(found_row, 0)
            else:
                self._wl_table.setCurrentCell(-1, -1)
        self._refresh_detail_table()

    def _refresh_detail_table(self):
        entry = self._selected_wishlist_entry()
        if entry is None:
            self._detail_table.setRowCount(0)
            self._refresh_engineer_table()
            self._refresh_carrier_table()
            return
        reqs = self._requirements_for(entry)
        rows = sorted(reqs.items(), key=lambda kv: self._material_name(kv[0]))

        self._detail_table.setSortingEnabled(False)
        self._detail_table.setRowCount(len(rows))
        for r, (sym, qty) in enumerate(rows):
            held = self._held_count(sym)
            name_item = QTableWidgetItem(self._material_name(sym))
            held_item = _NumericTableWidgetItem(str(held), held)
            req_item = _NumericTableWidgetItem(str(qty), qty)
            held_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            req_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            color = QColor("#6BCB77") if held >= qty else QColor("#FF6B6B")
            name_item.setForeground(color)
            held_item.setForeground(color)

            if is_bartender_tradeable(sym):
                source_item = QTableWidgetItem("Bartender")
                source_item.setForeground(QColor("#6BCB77"))
            else:
                source_item = QTableWidgetItem("Farm/loot only")
                source_item.setForeground(QColor("#888888"))

            self._detail_table.setItem(r, 0, name_item)
            self._detail_table.setItem(r, 1, held_item)
            self._detail_table.setItem(r, 2, req_item)
            self._detail_table.setItem(r, 3, source_item)
        self._detail_table.setSortingEnabled(True)

        self._refresh_engineer_table(entry)
        self._refresh_carrier_table()

    def _refresh_engineer_table(self, entry: Optional[Dict[str, Any]] = None):
        if entry is None:
            entry = self._selected_wishlist_entry()
            if entry is None:
                self._engineer_table.setRowCount(0)
                self._engineer_note.setText("")
                return

        kind = entry["kind"]
        if kind in ("suit_grade", "weapon_grade"):
            self._engineer_table.setRowCount(0)
            self._engineer_note.setText(
                "Grade upgrades can be performed at any on-foot Engineer terminal — "
                "not gated to a specific Engineer."
            )
            return

        module_kind = "suit" if kind == "suit_module" else "weapon"
        engineers = self._table.module_engineers(module_kind, entry["name"])
        self._engineer_note.setText(
            "Once a module is applied it can't be changed — buy a fresh suit/weapon copy "
            "to try a different mod."
        )

        # getattr's default only covers a missing attribute — state.system_x
        # can exist but be None (e.g. before any position data has arrived
        # yet), which getattr would pass through unchanged and crash the
        # distance calc below.
        ref_x = getattr(self._state, "system_x", None) if self._state else None
        ref_y = getattr(self._state, "system_y", None) if self._state else None
        ref_z = getattr(self._state, "system_z", None) if self._state else None
        ref_x, ref_y, ref_z = ref_x or 0.0, ref_y or 0.0, ref_z or 0.0

        rows = []
        for eng_name in engineers:
            home = self._blueprints.engineer_home(eng_name)
            dist = None
            system_name = "—"
            if home and isinstance(home.get("x"), (int, float)):
                dist = ((home["x"] - ref_x) ** 2 + (home["y"] - ref_y) ** 2 + (home["z"] - ref_z) ** 2) ** 0.5
                system_name = home.get("system_name") or "—"
            rows.append((dist, eng_name, system_name))

        rows.sort(key=lambda r: (r[0] is None, r[0] if r[0] is not None else 0.0))

        self._engineer_table.setSortingEnabled(False)
        self._engineer_table.setRowCount(len(rows))
        for r, (dist, eng_name, system_name) in enumerate(rows):
            dist_item = _NumericTableWidgetItem(
                f"{dist:.1f}" if dist is not None else "—", dist if dist is not None else float("inf")
            )
            dist_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._engineer_table.setItem(r, 0, QTableWidgetItem(eng_name))
            self._engineer_table.setItem(r, 1, QTableWidgetItem(system_name))
            self._engineer_table.setItem(r, 2, dist_item)
        self._engineer_table.setSortingEnabled(True)

    def _refresh_carrier_table(self):
        entry = self._selected_wishlist_entry()
        if entry is None:
            self._carrier_table.setRowCount(0)
            self._carrier_note.setText("")
            return
        reqs = self._requirements_for(entry)
        missing_symbols = [sym for sym, qty in reqs.items() if self._held_count(sym) < qty]
        if not missing_symbols:
            self._carrier_table.setRowCount(0)
            self._carrier_note.setText("All required materials already held.")
            return

        ref_x = getattr(self._state, "system_x", None) if self._state else None
        ref_y = getattr(self._state, "system_y", None) if self._state else None
        ref_z = getattr(self._state, "system_z", None) if self._state else None
        if ref_x is None or ref_y is None or ref_z is None:
            self._carrier_table.setRowCount(0)
            self._carrier_note.setText("Current position unknown.")
            return

        radius = float(getattr(self._cfg, "market_search_radius_ly", 100) or 100)
        current_market_id = getattr(self._state, "current_market_id", None) if self._state else None
        try:
            by_symbol = self._repo.search_fleet_carrier_materials(
                missing_symbols, ref_x, ref_y, ref_z, radius, exclude_market_id=current_market_id,
            )
        except Exception:
            log.exception("Failed to search fleet carrier materials")
            self._carrier_table.setRowCount(0)
            self._carrier_note.setText("Carrier search failed — see log.")
            return

        rows = []
        for sym, listings in by_symbol.items():
            mat_name = self._material_name(sym)
            for listing in listings:
                rows.append((mat_name, listing))
        rows.sort(key=lambda r: r[1]["distance_ly"])

        self._carrier_table.setSortingEnabled(False)
        self._carrier_table.setRowCount(len(rows))
        for r, (mat_name, listing) in enumerate(rows):
            name_item = QTableWidgetItem(listing['carrier_name'])
            mat_item = QTableWidgetItem(mat_name)
            sys_item = QTableWidgetItem(listing["system_name"])
            dist_item = _NumericTableWidgetItem(f"{listing['distance_ly']:.1f}", listing['distance_ly'])
            dist_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            price = listing.get("price")
            price_item = _NumericTableWidgetItem(
                f"{price:,}" if isinstance(price, int) else "—", price if isinstance(price, int) else float("inf")
            )
            price_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            stock = listing.get("stock")
            stock_item = _NumericTableWidgetItem(
                str(stock) if isinstance(stock, int) else "—", stock if isinstance(stock, int) else float("inf")
            )
            stock_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            age_text, age_sort = _format_age(listing.get("last_updated"), listing.get("last_visited"))
            age_item = _NumericTableWidgetItem(age_text, age_sort)
            age_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            self._carrier_table.setItem(r, 0, mat_item)
            self._carrier_table.setItem(r, 1, name_item)
            self._carrier_table.setItem(r, 2, sys_item)
            self._carrier_table.setItem(r, 3, dist_item)
            self._carrier_table.setItem(r, 4, price_item)
            self._carrier_table.setItem(r, 5, stock_item)
            self._carrier_table.setItem(r, 6, age_item)
        self._carrier_table.setSortingEnabled(True)

        staleness_note = "Carrier listings/locations are crowdsourced from EDDN and can be several days old."
        self._carrier_note.setText(
            staleness_note if rows else
            f"No carriers found selling these materials within {radius:.0f} ly. {staleness_note}"
        )

    def refresh(self, state) -> None:
        self._state = state
        self._refresh_wishlist_table()


_STATUS_ACCENT = {
    "unlocked": {"accent": "#6BCB77", "status_color": "#6BCB77", "name_color": "#CCCCCC", "check": "✓ "},
    "in_progress": {"accent": "#FFB347", "status_color": "#FFB347", "name_color": "#CCCCCC", "check": ""},
    "not_encountered": {"accent": "#555555", "status_color": "#888888", "name_color": "#999999", "check": ""},
}


class _EngineersTab(QWidget):
    """Reference list of every in-game engineer -- discovery/meeting/
    unlock/referral requirements, grouped by the player's real current
    status (state.engineer_progress, already tracked elsewhere in this
    app). Advisory only; requirement text is static reference data, not
    derived from live journal state beyond the overall unlock status."""

    def __init__(self, blueprint_table: EngineeringBlueprintTable, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:#080f18;")
        self._blueprints = blueprint_table
        self._state = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        root.addWidget(scroll, 1)

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(6)
        content_layout.setContentsMargins(8, 6, 8, 8)
        content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(content)

        self._section_grids: Dict[str, QGridLayout] = {}
        for key, label_text in (
            ("unlocked", "UNLOCKED"),
            ("in_progress", "IN PROGRESS"),
            ("not_encountered", "NOT ENCOUNTERED"),
        ):
            hdr = QLabel(label_text)
            hdr.setStyleSheet(_HDR_STYLE)
            content_layout.addWidget(hdr)

            grid_container = QWidget()
            grid_container.setStyleSheet("background: transparent;")
            grid = QGridLayout(grid_container)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(6)
            grid.setVerticalSpacing(6)
            grid.setColumnStretch(0, 1)
            grid.setColumnStretch(1, 1)
            grid.setColumnStretch(2, 1)
            content_layout.addWidget(grid_container)
            self._section_grids[key] = grid

    def _esc(self, t) -> str:
        return str(t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _status_for(self, name: str):
        """Returns (group_key, status_text) for an engineer name, per this
        plan's Global Constraints status-derivation rule."""
        progress = getattr(self._state, "engineer_progress", None) or {} if self._state else {}
        rec = progress.get(name)
        if not rec:
            return "not_encountered", "Not Encountered"
        rank = rec.get("rank")
        if isinstance(rank, int) and rank >= 1:
            return "unlocked", f"Unlocked — Rank {rank}"
        prog = rec.get("progress")
        if prog:
            return "in_progress", f"{prog} — not yet unlocked"
        return "not_encountered", "Not Encountered"

    def _clear_grid(self, grid: QGridLayout) -> None:
        while grid.count():
            item = grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _engineer_html(self, name: str, group: str, status_text: str, req: Dict[str, str], home: Optional[Dict[str, Any]]) -> str:
        accent = _STATUS_ACCENT[group]
        ref_x = getattr(self._state, "system_x", None) if self._state else None
        ref_y = getattr(self._state, "system_y", None) if self._state else None
        ref_z = getattr(self._state, "system_z", None) if self._state else None
        dist_text = ""
        if home and all(isinstance(v, (int, float)) for v in (ref_x, ref_y, ref_z)):
            dist = ((home["x"] - ref_x) ** 2 + (home["y"] - ref_y) ** 2 + (home["z"] - ref_z) ** 2) ** 0.5
            dist_text = f" — {dist:.1f} ly"
        system_text = home.get("system_name") if home else None

        # No wrapping <div style="..."> here -- QTextDocument (the rich-text
        # engine backing QLabel HTML) doesn't render CSS `border` at all, so
        # the card's background/border/padding is applied via QSS on the
        # QLabel widget itself instead (see refresh()). Only text spans live
        # in the HTML.
        line = f'<span style="color:{accent["name_color"]};font-weight:700;">{self._esc(name)}</span>'
        if system_text:
            line += f' <span style="color:#4D96FF;font-size:12px;">— {self._esc(system_text)}{dist_text}</span>'
        line += (
            f'<br><span style="color:{accent["status_color"]};font-size:12px;">'
            f'{accent["check"]}{self._esc(status_text)}</span>'
        )

        for field_key, field_label in (
            ("discover", "Discover"),
            ("meet", "Meet"),
            ("unlock", "Unlock"),
            ("referral", "Referral"),
        ):
            text = req.get(field_key)
            if text:
                line += (
                    f'<br><span style="color:#888888;font-size:12px;">'
                    f'&nbsp;&nbsp;{field_label}: {self._esc(text)}</span>'
                )

        return line

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._state is not None:
            # Switching onto this tab doesn't fire a new journal event, so
            # without this the tab stays on whatever it looked like the
            # last time refresh() ran while visible -- possibly still
            # blank from before it was ever shown.
            self.refresh(self._state)

    def refresh(self, state) -> None:
        self._state = state
        if not self.isVisible():
            # Tab isn't the one currently on screen -- no point paying for
            # 38 engineers' worth of card rebuilds the user can't see.
            # self._state is already cached above for when the tab does
            # become visible (see showEvent).
            return

        names = self._blueprints.all_engineer_names()
        requirements = self._blueprints.all_engineer_requirements()
        homes = self._blueprints.all_engineer_homes()

        grouped: Dict[str, List[str]] = {"unlocked": [], "in_progress": [], "not_encountered": []}
        statuses: Dict[str, str] = {}
        for name in names:
            group, status_text = self._status_for(name)
            grouped[group].append(name)
            statuses[name] = status_text

        for key in ("unlocked", "in_progress", "not_encountered"):
            grid = self._section_grids[key]
            self._clear_grid(grid)
            entries = sorted(grouped[key])
            if not entries:
                empty = QLabel('<span style="color:#444444;font-size:12px;">None.</span>')
                empty.setTextFormat(Qt.TextFormat.RichText)
                empty.setStyleSheet("background: transparent; border: none;")
                grid.addWidget(empty, 0, 0)
                continue
            accent = _STATUS_ACCENT[key]
            for i, name in enumerate(entries):
                card = QLabel(
                    self._engineer_html(name, key, statuses[name], requirements.get(name) or {}, homes.get(name))
                )
                card.setWordWrap(True)
                card.setTextFormat(Qt.TextFormat.RichText)
                # QSS (QLabel's own stylesheet), not the rich-text HTML --
                # QTextDocument doesn't render CSS `border` at all, but QSS
                # does, including per-side width/color for the accent stripe.
                card.setStyleSheet(
                    "background:#0d1a2a; border-top:1px solid #1e3a5a; border-right:1px solid #1e3a5a; "
                    "border-bottom:1px solid #1e3a5a; "
                    f"border-left:3px solid {accent['accent']}; "
                    "border-radius:4px; padding:4px 8px;"
                )
                row, col = divmod(i, 3)
                grid.addWidget(card, row, col)
