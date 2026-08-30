"""One-shot full-history scan to reconstruct currently active fines at app
startup. Fines (CommitCrime with a Fine field, cleared by PayFines) must
survive across app restarts and journal-file boundaries -- a real in-game
fine doesn't clear just because the app restarted -- so this replays every
journal file chronologically rather than relying on any persisted app
state. Mirrors bounty_scanner.py exactly; fines and bounties are separate
CommitCrime fields with separate payoff events.

Resurrect also clears everything outstanding -- see bounty_scanner.py's
module docstring; the same Detention Centre capture forcibly pays off
fines alongside bounties.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict


def scan_active_fines(journal_dir: Path) -> Dict[str, int]:
    journal_dir = Path(journal_dir)
    if not journal_dir.exists():
        return {}

    active: Dict[str, int] = {}
    for path in sorted(journal_dir.glob("Journal.*.log")):
        try:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if ('"CommitCrime"' not in line and '"PayFines"' not in line
                            and '"Resurrect"' not in line):
                        continue
                    try:
                        event = json.loads(line)
                    except Exception:
                        continue
                    name = event.get("event")
                    if name == "CommitCrime":
                        fine = event.get("Fine")
                        faction = event.get("Faction")
                        if isinstance(fine, int) and isinstance(faction, str) and faction:
                            active[faction] = active.get(faction, 0) + fine
                    elif name == "PayFines":
                        faction = event.get("Faction")
                        if isinstance(faction, str) and faction:
                            active.pop(faction, None)
                        else:
                            active.clear()
                    elif name == "Resurrect":
                        active.clear()
        except OSError:
            continue

    return active
