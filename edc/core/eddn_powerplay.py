"""EDDN live PowerPlay cross-check — real-time cache fed by the EDDN relay.

Unlike edsm_powerplay.py (a bounded daily dump), this is populated
incrementally by a persistent background listener (see EddnPowerPlayWorker
in edc/core/eddn_listener.py) subscribing to EDDN's live journal firehose.
Confirmed empirically (2026-07-26): ~1 PP-bearing journal message per
second galaxy-wide, each carrying ControllingPower/PowerplayState/
SystemAddress verbatim from real commanders' FSDJump/Location events.

File location (portable-in-repo):
  <settings_dir>/eddn_powerplay_cache.json

Cache format — same per-system shape as EdsmPowerPlayCache so both can
feed the same cross-check consumer:
  {
    "systems": {
      "<id64>": [
        {"power": "...", "power_state": "...", "date": "ISO-8601 timestamp"}
      ]
    }
  }

Only one row is kept per (system, power) pair — a fresh sighting of a
power already recorded for a system replaces the old one rather than
appending, so the file doesn't grow unbounded over a long-running
session.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


class EddnPowerPlayCache:

    def __init__(self, settings_dir: Path, filename: str = "eddn_powerplay_cache.json"):
        self.path = Path(settings_dir) / filename
        self._systems: Dict[str, List[Dict[str, Any]]] = {}
        self._load()

    def _load(self) -> None:
        try:
            if not self.path.exists():
                return
            data = json.loads(self.path.read_text(encoding="utf-8"))
            systems = data.get("systems") if isinstance(data, dict) else None
            self._systems = systems if isinstance(systems, dict) else {}
        except Exception:
            log.exception("Failed to load eddn_powerplay_cache.json")
            self._systems = {}

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps({"systems": self._systems}, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            log.exception("Failed to write eddn_powerplay_cache.json")

    def has_data(self) -> bool:
        return bool(self._systems)

    def system_count(self) -> int:
        return len(self._systems)

    def lookup(self, id64: Optional[int]) -> Optional[List[Dict[str, Any]]]:
        if not isinstance(id64, int):
            return None
        return self._systems.get(str(id64))

    def get_controller(self, id64: Optional[int]) -> Optional[Dict[str, Any]]:
        """Most recent sighting for this system. power="" is a real, explicit
        "no controller" sighting (the system was Unoccupied at that
        timestamp), not a missing entry -- callers must check for it
        rather than treating an empty power as "no data"."""
        rows = self.lookup(id64)
        if not rows:
            return None
        return max(rows, key=lambda r: r.get("date") or "")

    def ingest(self, id64: int, power: str, power_state: str, timestamp: str) -> None:
        """Called from the main thread in response to the listener's system_seen signal."""
        key = str(id64)
        rows = self._systems.setdefault(key, [])
        for row in rows:
            if row.get("power") == power:
                if (timestamp or "") > (row.get("date") or ""):
                    row["power_state"] = power_state
                    row["date"] = timestamp
                return
        rows.append({"power": power, "power_state": power_state, "date": timestamp})
