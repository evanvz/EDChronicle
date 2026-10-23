# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the GNU General Public License v3.0 or later (GPL-3.0-or-later).
# See the LICENSE file in the project root for full terms.

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional

log = logging.getLogger("edc.megaship_tracker")

# Doncaster's Powerplay Reference Card: datalink merits "only once per megaship
# per fortnight", so a megaship is worth visiting again 14 days after the last visit.
RESCAN_AFTER = timedelta(days=14)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class MegashipTracker:
    """
    Persists when each specific megaship (keyed by system + its unique
    SignalName, e.g. "CAO-396 Beckett-class Researcher") was last visited for
    a PowerPlay merit scan. Its uplinks pay merits once per fortnight, and
    megaships sit in a system for many days/sessions, so this survives app
    restarts. The old "seen" list had no times and is dropped; the startup
    journal scan refills it with real visit times.
    """

    def __init__(self, path: Path):
        self.path = path
        self._visits: Dict[str, str] = self._load()

    def _load(self) -> Dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            visits = data.get("visits") if isinstance(data, dict) else None
            return dict(visits) if isinstance(visits, dict) else {}
        except Exception:
            log.exception("Failed to load megaships_seen.json")
            return {}

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps({"visits": dict(sorted(self._visits.items()))}, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            log.exception("Failed to save megaships_seen.json")

    @staticmethod
    def key(system_address, signal_name: str) -> str:
        return f"{system_address}|{signal_name}"

    def has_seen(self, key: str, now: Optional[str] = None) -> bool:
        """Visited within the last 14 days (merits not available again yet)."""
        last = self._visits.get(key)
        if not last:
            return False
        try:
            seen = datetime.fromisoformat(last.replace("Z", "+00:00"))
            current = datetime.fromisoformat((now or _now()).replace("Z", "+00:00"))
        except ValueError:
            return False
        return current - seen < RESCAN_AFTER

    def mark_seen(self, key: str, when: Optional[str] = None) -> None:
        self.merge_seen({key: when or _now()})

    def merge_seen(self, visits: Dict[str, str]) -> None:
        """Bulk-add {key: visit time} (e.g. from a full journal-history scan at
        startup), keeping the latest time per key -- one save, not one per key."""
        changed = False
        for k, ts in visits.items():
            if ts and ts > self._visits.get(k, ""):
                self._visits[k] = ts
                changed = True
        if changed:
            self._save()
