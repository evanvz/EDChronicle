"""Canonn's crowdsourced list of every known Guardian ruin system -- a
small, near-static galaxy-wide dataset (214 systems as of 2026-08-31),
unlike PowerPlay control state which changes weekly. Cached to disk and
refreshed at most once a day, same pattern as fdev_powerplay.py.

File location (portable-in-repo):
  <settings_dir>/guardian_ruins_cache.json
"""
from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from typing import Dict, Optional

import requests

log = logging.getLogger(__name__)

_URL = "https://us-central1-canonn-api-236217.cloudfunctions.net/query/get_gr_data"
_TIMEOUT = 30
_USER_AGENT = "EDChronicle/1.0.0 (+https://github.com/evanvz/EDChronicle)"


class GuardianRuinsCache:
    """Daily-cached lookup of Canonn's Guardian ruin system list, keyed by
    system name (lowercased)."""

    def __init__(self, settings_dir: Path, filename: str = "guardian_ruins_cache.json"):
        self.path = Path(settings_dir) / filename
        self.fetched_date: Optional[str] = None
        self._systems: Dict[str, dict] = {}
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
            log.exception("Failed to load guardian_ruins_cache.json")
            self.fetched_date = None
            self._systems = {}

    def is_stale(self) -> bool:
        return self.fetched_date != date.today().isoformat()

    def has_data(self) -> bool:
        return bool(self._systems)

    def has_ruins(self, system_name: Optional[str]) -> bool:
        return isinstance(system_name, str) and system_name.strip().lower() in self._systems

    def refresh(self) -> bool:
        """Synchronous -- call from a worker thread only, never the UI
        thread. Returns True on success."""
        try:
            resp = requests.get(_URL, headers={"User-Agent": _USER_AGENT}, timeout=_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            log.exception("Failed to fetch Canonn Guardian ruins list")
            return False

        if not isinstance(data, list):
            log.warning("Canonn get_gr_data returned an unexpected shape -- treating as failure")
            return False

        systems: Dict[str, dict] = {}
        for rec in data:
            if not isinstance(rec, dict):
                continue
            name = rec.get("system")
            if not isinstance(name, str) or not name.strip():
                continue
            systems[name.strip().lower()] = {"system": name.strip()}

        if not systems:
            log.warning("Canonn Guardian ruins list parsed to zero systems -- treating as failure")
            return False

        self._systems = systems
        self.fetched_date = date.today().isoformat()

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps({"fetched_date": self.fetched_date, "systems": systems}, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            log.exception("Failed to write guardian_ruins_cache.json")

        log.info("Guardian ruins cache refreshed: %d systems", len(systems))
        return True
