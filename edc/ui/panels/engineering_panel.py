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
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QSpinBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QFrame, QTabWidget,
)

from edc.core.engineering_blueprints import EngineeringBlueprintTable
from edc.core.engineering_wishlist import EngineeringWishlist
from edc.core.experimental_effects import ExperimentalEffectsTable
from edc.core.material_trading import find_material_trades
from edc.core.odyssey_engineering import OdysseyEngineeringTable
from edc.core.odyssey_material_source import is_bartender_tradeable
from edc.core.odyssey_wishlist import OdysseyWishlist

log = logging.getLogger(__name__)

_CATEGORY_STATE_ATTR = {
    "raw": "materials_raw",
    "manufactured": "materials_manufactured",
    "encoded": "materials_encoded",
}

_CARD_STYLE = "QFrame { background:#0d1a2a; border:1px solid #1e3a5a; border-radius:5px; }"
_HDR_STYLE = "color:#555555; font-size:12px; font-weight:bold; letter-spacing:1px; background:transparent; border:none;"
_LABEL_STYLE = "background:transparent; border:none; color:#c8c8c8;"
_COMBO_STYLE = "background:#0a1520; color:#c8c8c8; border:1px solid #1e3a5a;"
_TABLE_STYLE = (
    "QTableWidget { background:#080f18; alternate-background-color:#0a1520;"
    " gridline-color:#1e3a5a; border:1px solid #1e3a5a; }"
    "QHeaderView::section { background:#0d1a2a; color:#888888; border:none;"
    " padding:3px; font-size:12px; font-weight:bold; letter-spacing:1px; }"
    "QTableWidget::item:selected { background:#1a3a5a; color:#FFB347; }"
)


def _make_table(headers: List[str]) -> QTableWidget:
    t = QTableWidget()
    t.setColumnCount(len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    t.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    t.verticalHeader().setVisible(False)
    t.setAlternatingRowColors(True)
    t.setStyleSheet(_TABLE_STYLE)
    return t


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

        self._ship_tab = _ShipEngineeringTab(blueprint_table, wishlist_store, experimental_effects)
        self._odyssey_tab = _OdysseyEngineeringTab(odyssey_table, blueprint_table, odyssey_wishlist_store)
        self._tabs.addTab(self._ship_tab, "Ships")
        self._tabs.addTab(self._odyssey_tab, "Suits & Weapons")

    def missing_materials_for_wishlist(self) -> Dict[str, int]:
        """Ship-only — used by main_window's farming-location alert hook."""
        return self._ship_tab.missing_materials_for_wishlist()

    def refresh(self, state) -> None:
        self._ship_tab.refresh(state)
        self._odyssey_tab.refresh(state)


class _ShipEngineeringTab(QWidget):
    def __init__(
        self,
        blueprint_table: EngineeringBlueprintTable,
        wishlist_store: EngineeringWishlist,
        experimental_effects: ExperimentalEffectsTable,
        parent=None,
    ):
        super().__init__(parent)
        self.setStyleSheet("background:#080f18;")
        self._blueprints = blueprint_table
        self._store = wishlist_store
        self._effects = experimental_effects
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
        self._engineer_note.setStyleSheet("color:#555555; font-size:11px; background:transparent; border:none;")
        right.addWidget(self._engineer_note)

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

    def _remove_selected(self):
        row = self._wl_table.currentRow()
        if row < 0 or row >= len(self._wishlist):
            return
        del self._wishlist[row]
        self._store.save(self._wishlist)
        self._refresh_wishlist_table()

    def _refresh_wishlist_table(self):
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
            grade_item = QTableWidgetItem(str(grade))
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
        self._refresh_detail_table()

    def _refresh_detail_table(self):
        row = self._wl_table.currentRow()
        if row < 0 or row >= len(self._wishlist):
            self._detail_table.setRowCount(0)
            self._refresh_engineer_table()
            return
        entry = self._wishlist[row]
        reqs = self._combined_requirements(entry)
        rows = sorted(reqs.items(), key=lambda kv: self._blueprints.material_name(kv[0]))

        self._detail_table.setRowCount(len(rows))
        for r, (sym, qty) in enumerate(rows):
            held = self._held_count(sym)
            name_item = QTableWidgetItem(self._blueprints.material_name(sym))
            type_item = QTableWidgetItem(self._blueprints.material_type(sym))
            held_item = QTableWidgetItem(str(held))
            req_item = QTableWidgetItem(str(qty))
            for it in (held_item, req_item):
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            color = QColor("#6BCB77") if held >= qty else QColor("#FF6B6B")
            name_item.setForeground(color)
            held_item.setForeground(color)

            self._detail_table.setItem(r, 0, name_item)
            self._detail_table.setItem(r, 1, type_item)
            self._detail_table.setItem(r, 2, held_item)
            self._detail_table.setItem(r, 3, req_item)

        self._refresh_engineer_table()

    def _refresh_engineer_table(self):
        row = self._wl_table.currentRow()
        if row < 0 or row >= len(self._wishlist):
            self._engineer_table.setRowCount(0)
            return
        entry = self._wishlist[row]
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

        self._engineer_table.setRowCount(len(rows))
        for r, (dist, eng_name, system_name, status_text, status_color) in enumerate(rows):
            name_item = QTableWidgetItem(eng_name)
            sys_item = QTableWidgetItem(system_name)
            dist_item = QTableWidgetItem(f"{dist:.1f}" if dist is not None else "—")
            dist_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            status_item = QTableWidgetItem(status_text)
            status_item.setForeground(QColor(status_color))

            self._engineer_table.setItem(r, 0, name_item)
            self._engineer_table.setItem(r, 1, sys_item)
            self._engineer_table.setItem(r, 2, dist_item)
            self._engineer_table.setItem(r, 3, status_item)

    def _refresh_trade_suggestions(self) -> None:
        owned: Dict[str, int] = {}
        for attr in _CATEGORY_STATE_ATTR.values():
            owned.update(getattr(self._state, attr, {}) or {})
        shortfalls = self.missing_materials_for_wishlist()
        suggestions = find_material_trades(shortfalls, owned)

        rows = sorted(suggestions.items(), key=lambda kv: self._blueprints.material_name(kv[0]))
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
        parent=None,
    ):
        super().__init__(parent)
        self.setStyleSheet("background:#080f18;")
        self._table = odyssey_table
        self._blueprints = blueprint_table  # for engineer_home() lookups only
        self._store = wishlist_store
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
        self._engineer_note.setStyleSheet("color:#555555; font-size:11px; background:transparent; border:none;")
        right.addWidget(self._engineer_note)

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
        return loc.get(symbol.lower(), symbol)

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

    def _remove_selected(self):
        row = self._wl_table.currentRow()
        if row < 0 or row >= len(self._wishlist):
            return
        del self._wishlist[row]
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
        self._wl_table.setRowCount(len(self._wishlist))
        for r, entry in enumerate(self._wishlist):
            name_item = QTableWidgetItem(self._display_name(entry))
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
        self._refresh_detail_table()

    def _refresh_detail_table(self):
        row = self._wl_table.currentRow()
        if row < 0 or row >= len(self._wishlist):
            self._detail_table.setRowCount(0)
            self._refresh_engineer_table()
            return
        entry = self._wishlist[row]
        reqs = self._requirements_for(entry)
        rows = sorted(reqs.items(), key=lambda kv: self._material_name(kv[0]))

        self._detail_table.setRowCount(len(rows))
        for r, (sym, qty) in enumerate(rows):
            held = self._held_count(sym)
            name_item = QTableWidgetItem(self._material_name(sym))
            held_item = QTableWidgetItem(str(held))
            req_item = QTableWidgetItem(str(qty))
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

        self._refresh_engineer_table(entry)

    def _refresh_engineer_table(self, entry: Optional[Dict[str, Any]] = None):
        if entry is None:
            row = self._wl_table.currentRow()
            if row < 0 or row >= len(self._wishlist):
                self._engineer_table.setRowCount(0)
                self._engineer_note.setText("")
                return
            entry = self._wishlist[row]

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

        self._engineer_table.setRowCount(len(rows))
        for r, (dist, eng_name, system_name) in enumerate(rows):
            dist_item = QTableWidgetItem(f"{dist:.1f}" if dist is not None else "—")
            dist_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._engineer_table.setItem(r, 0, QTableWidgetItem(eng_name))
            self._engineer_table.setItem(r, 1, QTableWidgetItem(system_name))
            self._engineer_table.setItem(r, 2, dist_item)

    def refresh(self, state) -> None:
        self._state = state
        self._refresh_wishlist_table()
