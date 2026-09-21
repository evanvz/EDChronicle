# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the PolyForm Noncommercial License 1.0.0.
# See the LICENSE file in the project root for full terms.

"""Commodity symbol -> Frontier's own category (Chemicals, Metals, ...)
and proper display name -- see settings/commodity_categories.json for
sourcing. Static reference data (doesn't change at runtime), so no
mtime-based reload like the other settings loaders in this app -- load
once."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, Optional

log = logging.getLogger("edc.commodity_categories")


class CommodityCategoryTable:
    def __init__(self, settings_dir: Path, filename: str = "commodity_categories.json"):
        self._commodities: Dict[str, dict] = {}
        path = Path(settings_dir) / filename
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            commodities = data.get("commodities") if isinstance(data, dict) else None
            self._commodities = commodities if isinstance(commodities, dict) else {}
        except Exception:
            log.exception("Failed to load commodity_categories.json")

    def category_for(self, symbol: str) -> Optional[str]:
        rec = self._commodities.get((symbol or "").strip().lower())
        return rec.get("category") if rec else None

    def display_name_for(self, symbol: str) -> Optional[str]:
        rec = self._commodities.get((symbol or "").strip().lower())
        return rec.get("name") if rec else None
