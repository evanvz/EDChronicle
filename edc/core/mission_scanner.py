"""Full-history scan to reconstruct currently-active missions at app
startup — same reasoning as bounty_scanner.py/squadron_scanner.py: a
mission can sit active for days, well outside the live bootstrap's
tail-replay window of the current journal.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from edc.core.mission_events import MISSION_EVENT_NAMES, apply_mission_event


def scan_active_missions(journal_dir: Path) -> Dict[int, Dict[str, Any]]:
    journal_dir = Path(journal_dir)
    active: Dict[int, Dict[str, Any]] = {}
    if not journal_dir.exists():
        return active

    for path in sorted(journal_dir.glob("Journal.*.log")):
        try:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if '"Mission' not in line:
                        continue
                    try:
                        event = json.loads(line)
                    except Exception:
                        continue
                    if event.get("event") not in MISSION_EVENT_NAMES:
                        continue
                    apply_mission_event(active, event)
        except OSError:
            continue

    return active
