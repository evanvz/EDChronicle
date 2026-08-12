"""Offline, advisory-only Odyssey (on-foot) suit/weapon engineering reference.

Recipe data ported (not code reused) from jixxed/ed-odyssey-materials-helper
(MIT licensed) — see settings/odyssey_engineering.json for provenance.
Engineer home-system lookups reuse EngineeringBlueprintTable's existing
engineer_locations table (FDevIDs), since on-foot Engineers share that same
roster with ship Engineers — no separate location dataset needed.

Suits/weapons start at grade 1 for free; each step up to grade 5 costs its
own materials (only 4 transitions exist: 1->2, 2->3, 3->4, 4->5), unlike
ship blueprints which have a material cost at every grade including 1.
Suit/weapon *modules* (the actual mod slots) aren't graded at all — picking
one is a single material cost, and once applied it can't be changed.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("edc.odyssey_engineering")


class OdysseyEngineeringTable:
    def __init__(self, settings_dir: Path, filename: str = "odyssey_engineering.json"):
        self.path = Path(settings_dir) / filename
        self._mtime: Optional[float] = None
        self.last_updated: Optional[str] = None
        self._suits: Dict[str, Dict[str, Dict[str, int]]] = {}
        self._weapons: Dict[str, Dict[str, Dict[str, int]]] = {}
        self._suit_modules: Dict[str, Dict[str, Any]] = {}
        self._weapon_modules: Dict[str, Dict[str, Any]] = {}
        self._load(force=True)

        # Odyssey microresource symbol -> English display name (EDCD/FDevIDs
        # microresources.csv, see settings/odyssey_material_names.json for
        # provenance) -- covers materials the player hasn't personally
        # picked up yet, so the UI never has to fall back to a raw internal
        # symbol like "geneticrepairmeds".
        self._material_names_path = Path(settings_dir) / "odyssey_material_names.json"
        self._material_names_mtime: Optional[float] = None
        self._material_names: Dict[str, str] = {}
        self._load_material_names(force=True)

    def _load(self, force: bool = False) -> None:
        try:
            if not self.path.exists():
                self._suits = {}
                self._weapons = {}
                self._suit_modules = {}
                self._weapon_modules = {}
                self.last_updated = None
                self._mtime = None
                return

            m = self.path.stat().st_mtime
            if (not force) and (self._mtime is not None) and (m == self._mtime):
                return

            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._mtime = m

            self.last_updated = data.get("last_updated") if isinstance(data, dict) else None
            self._suits = (data.get("suits") or {}) if isinstance(data, dict) else {}
            self._weapons = (data.get("weapons") or {}) if isinstance(data, dict) else {}
            self._suit_modules = (data.get("suit_modules") or {}) if isinstance(data, dict) else {}
            self._weapon_modules = (data.get("weapon_modules") or {}) if isinstance(data, dict) else {}
        except Exception:
            log.exception("Failed to load odyssey_engineering.json")
            self._suits = {}
            self._weapons = {}
            self._suit_modules = {}
            self._weapon_modules = {}
            self.last_updated = None
            self._mtime = None

    def has_data(self) -> bool:
        self._load(force=False)
        return bool(self._suits or self._weapons)

    def _load_material_names(self, force: bool = False) -> None:
        try:
            if not self._material_names_path.exists():
                self._material_names = {}
                self._material_names_mtime = None
                return

            m = self._material_names_path.stat().st_mtime
            if (not force) and (self._material_names_mtime is not None) and (m == self._material_names_mtime):
                return

            data = json.loads(self._material_names_path.read_text(encoding="utf-8"))
            self._material_names_mtime = m
            names = (data.get("names") or {}) if isinstance(data, dict) else {}
            self._material_names = names if isinstance(names, dict) else {}
        except Exception:
            log.exception("Failed to load odyssey_material_names.json")
            self._material_names = {}
            self._material_names_mtime = None

    def material_display_name(self, symbol: str) -> Optional[str]:
        """Static EDCD/FDevIDs-sourced display name for a microresource
        symbol, or None if unknown -- callers should prefer a live
        journal-derived localised name when one is available, and fall
        back to this only when the player hasn't personally seen the
        material yet."""
        self._load_material_names(force=False)
        return self._material_names.get((symbol or "").lower())

    # ── Suit / weapon grade upgrades ────────────────────────────────────────

    def suit_names(self) -> List[str]:
        self._load(force=False)
        return sorted(self._suits.keys())

    def weapon_names(self) -> List[str]:
        self._load(force=False)
        return sorted(self._weapons.keys())

    def suit_cumulative_requirements(self, suit_name: str, target_grade: int) -> Dict[str, int]:
        return self._cumulative(self._suits.get(suit_name) or {}, target_grade)

    def weapon_cumulative_requirements(self, weapon_name: str, target_grade: int) -> Dict[str, int]:
        return self._cumulative(self._weapons.get(weapon_name) or {}, target_grade)

    @staticmethod
    def _cumulative(grades: Dict[str, Dict[str, int]], target_grade: int) -> Dict[str, int]:
        """Grade 1 is free — sums the material cost of every transition up
        to and including reaching target_grade (2..5)."""
        total: Dict[str, int] = {}
        for g in range(2, target_grade + 1):
            reqs = grades.get(str(g))
            if not isinstance(reqs, dict):
                continue
            for material, qty in reqs.items():
                if isinstance(qty, int):
                    total[material] = total.get(material, 0) + qty
        return total

    # ── Suit / weapon modules (mod slots) ───────────────────────────────────

    def suit_module_keys(self) -> List[str]:
        self._load(force=False)
        return sorted(self._suit_modules.keys(), key=lambda k: self._suit_modules[k].get("display_name") or k)

    def weapon_module_keys(self) -> List[str]:
        self._load(force=False)
        return sorted(self._weapon_modules.keys(), key=lambda k: self._weapon_modules[k].get("display_name") or k)

    def suit_module(self, key: str) -> Optional[Dict[str, Any]]:
        return self._suit_modules.get(key)

    def weapon_module(self, key: str) -> Optional[Dict[str, Any]]:
        return self._weapon_modules.get(key)

    def module_requirements(self, kind: str, key: str) -> Dict[str, int]:
        rec = self.suit_module(key) if kind == "suit" else self.weapon_module(key)
        reqs = (rec or {}).get("materials")
        return dict(reqs) if isinstance(reqs, dict) else {}

    def module_display_name(self, kind: str, key: str) -> str:
        rec = self.suit_module(key) if kind == "suit" else self.weapon_module(key)
        return (rec or {}).get("display_name") or key

    def module_engineers(self, kind: str, key: str) -> List[str]:
        rec = self.suit_module(key) if kind == "suit" else self.weapon_module(key)
        names = (rec or {}).get("engineers")
        return list(names) if isinstance(names, list) else []
