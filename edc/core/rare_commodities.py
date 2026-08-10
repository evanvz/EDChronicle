"""Offline reference table of real rare goods and their one true canonical
selling station (market_id) — sourced from EDCD/FDevIDs rare_commodity.csv
(Frontier game data, no separate license grant; used non-commercially
under Frontier's community/fan content terms). Unlike regular
commodities, a rare good only ever has one
valid source station galaxy-wide, so cross-referencing by market_id (not
just commodity name) avoids the noisy/stale duplicate-station results a
plain name search over the EDDN commodity feed can produce.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("edc.rare_commodities")


class RareCommodityTable:
    def __init__(self, settings_dir: Path, filename: str = "rare_commodities.json"):
        self.path = Path(settings_dir) / filename
        self._items: List[Dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            items = data.get("items") if isinstance(data, dict) else None
            self._items = items if isinstance(items, list) else []
        except Exception:
            log.exception("Failed to load rare_commodities.json")
            self._items = []

    def all(self) -> List[Dict[str, Any]]:
        return list(self._items)
