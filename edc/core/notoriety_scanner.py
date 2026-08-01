"""One-shot scan for the most recently recorded Notoriety value at app
startup. Notoriety is reported via the "Statistics" event (Crime.Notoriety),
which fires automatically at the start of every journal file (commander
login) as well as whenever the player opens the in-game Statistics panel —
but the app's live bootstrap only re-reads the tail of the current journal
(see journal_watcher.py::_bootstrap_newest_system), which can miss it if
that event fell outside the re-read window. Scanning journal files newest
-> oldest and stopping at the first match is cheap and always correct.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional


def scan_latest_notoriety(journal_dir: Path) -> Optional[Dict[str, Any]]:
    journal_dir = Path(journal_dir)
    if not journal_dir.exists():
        return None

    for path in sorted(journal_dir.glob("Journal.*.log"), reverse=True):
        latest = None
        try:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if '"Statistics"' not in line:
                        continue
                    try:
                        event = json.loads(line)
                    except Exception:
                        continue
                    if event.get("event") != "Statistics":
                        continue
                    crime = event.get("Crime")
                    if isinstance(crime, dict) and isinstance(crime.get("Notoriety"), int):
                        latest = {"notoriety": crime["Notoriety"], "timestamp": event.get("timestamp")}
        except OSError:
            continue
        if latest is not None:
            return latest

    return None
