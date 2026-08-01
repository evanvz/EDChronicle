"""One-shot full-history scan to reconstruct currently active bounties at
app startup. Bounties (CommitCrime with a Bounty field, cleared by
PayBounties) must survive across app restarts and journal-file boundaries —
a real in-game bounty doesn't clear just because the app restarted — so
this replays every journal file chronologically rather than relying on any
persisted app state.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict


def scan_active_bounties(journal_dir: Path) -> Dict[str, int]:
    journal_dir = Path(journal_dir)
    if not journal_dir.exists():
        return {}

    active: Dict[str, int] = {}
    for path in sorted(journal_dir.glob("Journal.*.log")):
        try:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if '"CommitCrime"' not in line and '"PayBounties"' not in line:
                        continue
                    try:
                        event = json.loads(line)
                    except Exception:
                        continue
                    name = event.get("event")
                    if name == "CommitCrime":
                        bounty = event.get("Bounty")
                        faction = event.get("Faction")
                        if isinstance(bounty, int) and isinstance(faction, str) and faction:
                            active[faction] = active.get(faction, 0) + bounty
                    elif name == "PayBounties":
                        faction = event.get("Faction")
                        if isinstance(faction, str) and faction:
                            active.pop(faction, None)
                        else:
                            active.clear()
        except OSError:
            continue

    return active
