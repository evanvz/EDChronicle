# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the PolyForm Noncommercial License 1.0.0.
# See the LICENSE file in the project root for full terms.

"""Ship internal symbol -> max landing pad size ('S'/'M'/'L') -- see
settings/ship_pad_sizes.json for sourcing. Distinct from
edc/core/station_pads.py, which is about a *station's* pad size; this is
about what a *ship* needs, used to auto-filter "nearest place to buy"
results down to stations the commander's current ship can actually land
at.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, Optional

log = logging.getLogger("edc.ship_pad_sizes")


class ShipPadSizeTable:
    def __init__(self, settings_dir: Path, filename: str = "ship_pad_sizes.json"):
        self.path = Path(settings_dir) / filename
        self._mtime: Optional[float] = None
        self._pad_sizes: Dict[str, str] = {}
        self._load(force=True)

    def _load(self, force: bool = False) -> None:
        try:
            if not self.path.exists():
                self._pad_sizes = {}
                self._mtime = None
                return

            m = self.path.stat().st_mtime
            if (not force) and (self._mtime is not None) and (m == self._mtime):
                return

            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._mtime = m
            pad_sizes = (data.get("pad_sizes") or {}) if isinstance(data, dict) else {}
            self._pad_sizes = pad_sizes if isinstance(pad_sizes, dict) else {}
        except Exception:
            log.exception("Failed to load ship_pad_sizes.json")
            self._pad_sizes = {}
            self._mtime = None

    def pad_size_for(self, ship_symbol: Optional[str]) -> Optional[str]:
        """'S'/'M'/'L', or None if this ship isn't in the reference data."""
        self._load(force=False)
        if not ship_symbol:
            return None
        return self._pad_sizes.get(ship_symbol.strip().lower())
