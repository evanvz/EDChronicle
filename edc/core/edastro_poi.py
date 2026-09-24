# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the PolyForm Noncommercial License 1.0.0.
# See the LICENSE file in the project root for full terms.

"""EDAstro's community-curated Points of Interest catalog (Galactic
Exploration Catalog + Galactic Mapping Project, merged) -- notable
stellar phenomena, historical sites, and other named points of interest,
each with real galactic coordinates.

EDAstro's own "nearest POI to a coordinate" endpoint (documented at
https://edastro.com/api-details.html) does not actually work as
documented -- confirmed live 2026-09-24: querying it with the EXACT
coordinates of a real, known POI still returned an unrelated system
("The Solar System") regardless of input. So this fetches the bulk list
instead (confirmed working) and computes nearest locally -- same
approach already used for Trailblazer supply ships, Guardian Technology
Broker stations, and Rare Goods (a curated reference list, not something
to trust blindly for correctness beyond "this endpoint returned data").

File location (portable-in-repo):
  <settings_dir>/edastro_poi_cache.json

Not a substitute for Spansh's own per-body exploration-value estimates
(estimatedValue/terraformable) -- EDAstro's own system-query endpoint
doesn't expose either field at all, confirmed against a real system.
This is a different, complementary thing: a curated "interesting places"
list, not a valuation source.
"""
from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger(__name__)

_POI_URL = "https://edastro.com/gec/json/combined"
_TIMEOUT = 60
_USER_AGENT = "EDChronicle/1.0.0 (+https://github.com/evanvz/EDChronicle)"


class EdAstroPoiCache:
    """Daily-cached list of EDAstro's Points of Interest, kept in memory
    (a few hundred small records -- no DB table needed, same approach as
    EdsmPowerPlayCache)."""

    def __init__(self, settings_dir: Path, filename: str = "edastro_poi_cache.json"):
        self.path = Path(settings_dir) / filename
        self.fetched_date: Optional[str] = None
        self._pois: List[Dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        try:
            if not self.path.exists():
                return
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return
            self.fetched_date = data.get("fetched_date")
            pois = data.get("pois")
            self._pois = pois if isinstance(pois, list) else []
        except Exception:
            log.exception("Failed to load edastro_poi_cache.json")
            self.fetched_date = None
            self._pois = []

    def is_stale(self) -> bool:
        return self.fetched_date != date.today().isoformat()

    def has_data(self) -> bool:
        return bool(self._pois)

    def poi_count(self) -> int:
        return len(self._pois)

    def get_nearest(self, x: float, y: float, z: float, min_rating: Optional[float] = None) -> Optional[dict]:
        """Nearest POI to (x, y, z), optionally filtered to a minimum
        community "rating" (EDAstro's own 0-10ish explorer-interest
        score) -- computed locally since EDAstro's own remote "nearest"
        endpoint doesn't work (see this module's docstring). Returns None
        if the cache is empty or nothing meets min_rating."""
        best = None
        best_dist = None
        for poi in self._pois:
            coords = poi.get("coordinates")
            if not (isinstance(coords, list) and len(coords) == 3):
                continue
            if min_rating is not None:
                rating = poi.get("rating")
                if not isinstance(rating, (int, float)) or rating < min_rating:
                    continue
            try:
                px, py, pz = float(coords[0]), float(coords[1]), float(coords[2])
            except (TypeError, ValueError):
                continue
            dist = ((px - x) ** 2 + (py - y) ** 2 + (pz - z) ** 2) ** 0.5
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best = dict(poi)
                best["distance_ly"] = dist
        return best

    def refresh(self) -> bool:
        """Synchronous -- downloads and parses the feed. Call from a
        worker thread only, never the UI thread."""
        try:
            resp = requests.get(_POI_URL, headers={"User-Agent": _USER_AGENT}, timeout=_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log.error("EDAstro POI feed fetch failed: %s", exc)
            return False

        if not isinstance(data, list) or not data:
            log.warning("EDAstro POI feed parsed to zero entries -- treating as failure")
            return False

        self._pois = data
        self.fetched_date = date.today().isoformat()

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps({"fetched_date": self.fetched_date, "pois": data}, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            log.exception("Failed to write edastro_poi_cache.json")

        log.info("EDAstro POI cache refreshed: %d points of interest", len(data))
        return True
