"""EDSM PowerPlay dump cache — daily-refreshed cross-check source for Spansh PP data.

File location (portable-in-repo):
  <settings_dir>/edsm_powerplay_cache.json

Cache format:
  {
    "fetched_date": "YYYY-MM-DD",
    "systems": {
      "<id64>": [
        {"power": "...", "power_state": "...", "date": "YYYY-MM-DD HH:MM:SS"},
        ...
      ]
    }
  }

The dump is NOT a clean single-truth snapshot: a system can carry one row
per (power, system) pair it has ever had presence in, each independently
timestamped. A former controller's stale row can persist alongside the
current controller's fresher one. `get_controller()` picks the most
plausible current controller — most recent non-"Unoccupied" row — rather
than trusting any single row in isolation.
"""
from __future__ import annotations

import gzip
import json
import logging
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

import cloudscraper

log = logging.getLogger(__name__)

_GZIP_MAGIC = b"\x1f\x8b"

_DUMP_URL = "https://www.edsm.net/dump/powerPlay.json.gz"
_TIMEOUT = 120


class EdsmPowerPlayCache:
    """
    Daily-cached lookup of EDSM's PowerPlay dump, keyed by system id64.

    Only covers systems that have (or recently had) a power's presence —
    i.e. reinforcement/undermining targets. Acquisition-stage systems
    (expansion/contested/unclaimed) are not meaningfully covered.
    """

    def __init__(self, settings_dir: Path, filename: str = "edsm_powerplay_cache.json"):
        self.path = Path(settings_dir) / filename
        self.fetched_date: Optional[str] = None
        self._systems: Dict[str, List[Dict[str, Any]]] = {}
        self._load()

    def _load(self) -> None:
        try:
            if not self.path.exists():
                return
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return
            self.fetched_date = data.get("fetched_date")
            systems = data.get("systems")
            self._systems = systems if isinstance(systems, dict) else {}
        except Exception:
            log.exception("Failed to load edsm_powerplay_cache.json")
            self.fetched_date = None
            self._systems = {}

    def is_stale(self) -> bool:
        return self.fetched_date != date.today().isoformat()

    def has_data(self) -> bool:
        return bool(self._systems)

    def lookup(self, id64: Optional[int]) -> Optional[List[Dict[str, Any]]]:
        """Returns all known (power, power_state, date) rows for this system, if any."""
        if not isinstance(id64, int):
            return None
        return self._systems.get(str(id64))

    def get_controller(self, id64: Optional[int]) -> Optional[Dict[str, Any]]:
        """
        Best-guess current controller for a system: the most recent row
        whose power_state isn't "Unoccupied". Falls back to the most
        recent row overall (a power with only a foothold, no control) if
        every row is Unoccupied. Returns None if the system isn't in the
        dump at all.
        """
        rows = self.lookup(id64)
        if not rows:
            return None
        controlling = [r for r in rows if r.get("power_state") != "Unoccupied"]
        pool = controlling or rows
        return max(pool, key=lambda r: r.get("date") or "")

    def refresh(self) -> bool:
        """
        Synchronous — downloads and parses the ~20MB dump. Call from a
        worker thread only, never the UI thread.

        Returns True on success (cache updated and persisted to disk).
        """
        try:
            scraper = cloudscraper.create_scraper()
            resp = scraper.get(_DUMP_URL, timeout=_TIMEOUT)
            resp.raise_for_status()
            if resp.content[:2] != _GZIP_MAGIC:
                # Cloudflare's JS challenge page returns HTTP 200 with an
                # HTML body — status alone doesn't prove we got real data.
                log.error("EDSM PowerPlay dump fetch blocked by Cloudflare challenge (non-gzip response)")
                return False
            raw = gzip.decompress(resp.content)
            records = json.loads(raw)
        except Exception as exc:
            log.error("EDSM PowerPlay dump fetch failed: %s", exc)
            return False

        if not isinstance(records, list):
            log.warning("Unexpected EDSM PowerPlay dump shape")
            return False

        systems: Dict[str, List[Dict[str, Any]]] = {}
        for rec in records:
            if not isinstance(rec, dict):
                continue
            id64 = rec.get("id64")
            if not isinstance(id64, int):
                continue
            systems.setdefault(str(id64), []).append({
                "power": rec.get("power") or "",
                "power_state": rec.get("powerState") or "",
                "date": rec.get("date") or "",
            })

        self._systems = systems
        self.fetched_date = date.today().isoformat()

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps({"fetched_date": self.fetched_date, "systems": systems}, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            log.exception("Failed to write edsm_powerplay_cache.json")

        log.info("EDSM PowerPlay cache refreshed: %d systems", len(systems))
        return True
