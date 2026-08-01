"""Full-history scan to reconstruct squadron status (name, rank, rank
history, trophies, last membership transition) at app startup — same
reasoning as bounty_scanner.py: the live bootstrap only re-reads the tail
of the current journal, which can miss events from earlier sessions.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from edc.core.squadron_events import SQUADRON_EVENT_NAMES, apply_squadron_event


def scan_squadron_status(journal_dir: Path) -> Dict[str, Any]:
    journal_dir = Path(journal_dir)
    current: Dict[str, Any] = {
        "name": None, "rank": None, "rank_history": [], "trophies": 0,
        "status": None, "status_timestamp": None,
    }
    if not journal_dir.exists():
        return current

    for path in sorted(journal_dir.glob("Journal.*.log")):
        try:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if not any(name in line for name in SQUADRON_EVENT_NAMES):
                        continue
                    try:
                        event = json.loads(line)
                    except Exception:
                        continue
                    if event.get("event") not in SQUADRON_EVENT_NAMES:
                        continue
                    apply_squadron_event(current, event)
        except OSError:
            continue

    return current
