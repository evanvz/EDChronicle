"""Frontier's own official PowerPlay data feed — first-party ground truth
for which power currently controls a system, used to correct Spansh's
crawl (which can lag reality) in the PowerPlay Finder.

File location (portable-in-repo):
  <settings_dir>/fdev_powerplay_cache.json

Feed format (CSV, one row per power-controlled/contested system):
  "<system name> (<internal id>)","<power name> (<internal id>)",
  "<value>","<state>",<upkeep default>,<upkeep current>,<income>,
  "<contesting system, if any>",<qty for>,<qty against>,
  <threshold for>,<threshold against>,<prediction>,

state is one of ("control", "contested", "blocked", "takingControl") —
Frontier's own internal vocabulary, distinct from (but consistent with)
the "Exploited/Fortified/Stronghold/Unoccupied" tier names community
tools like Inara/EDSM/Spansh use for the same underlying data. Only
"control" (this power currently holds it) matters for validating a
Reinforcement target -- that's the one thing this feed is used for.

No coordinates or id64 in this feed, so it can't drive distance search
on its own -- keyed by system name only, purely to cross-check/correct
Spansh's controlling_power for a candidate Spansh already found.
"""
from __future__ import annotations

import csv
import io
import logging
import re
from datetime import date
from pathlib import Path
from typing import Dict, Optional

import requests

log = logging.getLogger(__name__)

_FEED_URL = "http://hosting.zaonce.net/powerplay-data/current/StarSystemsCurrent.csv"
_TIMEOUT = 60
_USER_AGENT = "EDChronicle/1.0.0 (+https://github.com/evanvz/EDChronicle)"

# "10 Arietis (62982)" -> "10 Arietis". Frontier's internal per-feed id in
# the parens isn't the game's SystemAddress/id64, so it's discarded rather
# than treated as a join key.
_NAME_RE = re.compile(r"^(.*?)\s*\(\d+\)\s*$")


def _strip_id_suffix(value: str) -> str:
    m = _NAME_RE.match(value.strip())
    return (m.group(1) if m else value).strip()


class FdevPowerPlayCache:
    """Daily-cached lookup of Frontier's official PowerPlay feed, keyed by
    system name (lowercased)."""

    def __init__(self, settings_dir: Path, filename: str = "fdev_powerplay_cache.json"):
        self.path = Path(settings_dir) / filename
        self.fetched_date: Optional[str] = None
        self._systems: Dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        import json
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
            log.exception("Failed to load fdev_powerplay_cache.json")
            self.fetched_date = None
            self._systems = {}

    def is_stale(self) -> bool:
        return self.fetched_date != date.today().isoformat()

    def has_data(self) -> bool:
        return bool(self._systems)

    def system_count(self) -> int:
        return len(self._systems)

    def get_by_name(self, system_name: Optional[str]) -> Optional[dict]:
        """Returns {"power": ..., "state": ..., "value": ...} or None if
        Frontier's feed has no row for this system (most systems aren't
        PowerPlay-exerted at all)."""
        if not isinstance(system_name, str) or not system_name.strip():
            return None
        return self._systems.get(system_name.strip().lower())

    def refresh(self) -> bool:
        """Synchronous — downloads and parses the feed. Call from a worker
        thread only, never the UI thread. Returns True on success (cache
        updated and persisted to disk)."""
        try:
            resp = requests.get(_FEED_URL, headers={"User-Agent": _USER_AGENT}, timeout=_TIMEOUT)
            resp.raise_for_status()
            text = resp.text
        except requests.RequestException as exc:
            log.error("Frontier PowerPlay feed fetch failed: %s", exc)
            return False

        systems: Dict[str, dict] = {}
        try:
            reader = csv.reader(io.StringIO(text))
            for row in reader:
                if len(row) < 4:
                    continue
                sys_field, power_field, value_field, state_field = row[0], row[1], row[2], row[3]
                name = _strip_id_suffix(sys_field)
                if not name:
                    continue
                power = _strip_id_suffix(power_field) if power_field else ""
                try:
                    value = int(value_field) if value_field.strip() else None
                except ValueError:
                    value = None
                systems[name.lower()] = {
                    "power": power,
                    "state": (state_field or "").strip(),
                    "value": value,
                }
        except Exception:
            log.exception("Failed to parse Frontier PowerPlay feed")
            return False

        if not systems:
            log.warning("Frontier PowerPlay feed parsed to zero systems -- treating as failure")
            return False

        self._systems = systems
        self.fetched_date = date.today().isoformat()

        try:
            import json
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps({"fetched_date": self.fetched_date, "systems": systems}, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            log.exception("Failed to write fdev_powerplay_cache.json")

        log.info("Frontier PowerPlay cache refreshed: %d systems", len(systems))
        return True
