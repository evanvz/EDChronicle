# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the PolyForm Noncommercial License 1.0.0.
# See the LICENSE file in the project root for full terms.

"""Offline, advisory-only Guardian Technology Broker unlock-recipe reference.

Recipe data ported (not code reused) from msarilar/EDEngineer (MIT licensed)
-- see settings/guardian_technology_broker.json for provenance.

Guardian Technology Broker unlocks are one-time module unlocks: trade a
specific batch of materials/commodities once at the broker to make a module
purchasable at Outfitting -- fundamentally different from repeatable Grade
1-5 ship/Odyssey engineering upgrades (see EngineeringBlueprintTable /
OdysseyEngineeringTable for those). Each unlock's ingredients are a mix of
'material' (tracked in state.materials_raw/manufactured/encoded, from the
Materials journal event) and 'commodity' (cargo-hold items bought/hauled
from markets, from the Cargo journal event) -- not all Guardian unlock
ingredients are materials.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("edc.guardian_technology_broker")


class GuardianTechnologyBrokerTable:
    def __init__(self, settings_dir: Path, filename: str = "guardian_technology_broker.json"):
        self.path = Path(settings_dir) / filename
        self._mtime: Optional[float] = None
        self.last_updated: Optional[str] = None
        self._unlocks: Dict[str, Dict[str, Any]] = {}
        self._load(force=True)

    def _load(self, force: bool = False) -> None:
        try:
            if not self.path.exists():
                self._unlocks = {}
                self.last_updated = None
                self._mtime = None
                return

            m = self.path.stat().st_mtime
            if (not force) and (self._mtime is not None) and (m == self._mtime):
                return

            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._mtime = m
            self.last_updated = data.get("last_updated") if isinstance(data, dict) else None
            unlocks = (data.get("unlocks") or {}) if isinstance(data, dict) else {}
            self._unlocks = unlocks if isinstance(unlocks, dict) else {}
        except Exception:
            log.exception("Failed to load guardian_technology_broker.json")
            self._unlocks = {}
            self.last_updated = None
            self._mtime = None

    def has_data(self) -> bool:
        self._load(force=False)
        return bool(self._unlocks)

    def unlock_names(self) -> List[str]:
        self._load(force=False)
        return sorted(self._unlocks.keys())

    def ingredients(self, unlock_name: str) -> List[Dict[str, Any]]:
        """Each item: {"symbol", "display_name", "kind" ("material" or
        "commodity"), "quantity"}."""
        self._load(force=False)
        rec = self._unlocks.get(unlock_name) or {}
        ingredients = rec.get("ingredients")
        return list(ingredients) if isinstance(ingredients, list) else []
