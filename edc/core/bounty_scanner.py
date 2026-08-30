"""One-shot full-history scan to reconstruct currently active bounties at
app startup. Bounties (CommitCrime with a Bounty field, cleared by
PayBounties) must survive across app restarts and journal-file boundaries —
a real in-game bounty doesn't clear just because the app restarted — so
this replays every journal file chronologically rather than relying on any
persisted app state.

Also records each faction's most recent CommitCrime timestamp: a bounty
older than 7 days goes DORMANT (hidden from scans; payable ONLY at a
station controlled by the issuing faction, not at Interstellar Factors),
so the age matters as much as the amount.

Resurrect also clears everything outstanding: dying while wanted sends
you to the nearest Detention Centre, which forcibly pays off every
accumulated bounty as part of the resurrection -- no separate PayBounties
event fires for it (confirmed live: a Resurrect event's Cost exactly
matched two outstanding on-foot murder bounties, immediately followed by
a Location event at a SystemGovernment=$government_Prison; station).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Tuple


def scan_active_bounties(journal_dir: Path) -> Dict[str, int]:
    amounts, _ = scan_active_bounties_with_dates(journal_dir)
    return amounts


def scan_active_bounties_with_dates(journal_dir: Path) -> Tuple[Dict[str, int], Dict[str, str]]:
    """Returns ({faction: amount}, {faction: last_commit_timestamp})."""
    journal_dir = Path(journal_dir)
    if not journal_dir.exists():
        return {}, {}

    active: Dict[str, int] = {}
    last_commit: Dict[str, str] = {}
    for path in sorted(journal_dir.glob("Journal.*.log")):
        try:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if ('"CommitCrime"' not in line and '"PayBounties"' not in line
                            and '"Resurrect"' not in line):
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
                            last_commit[faction] = event.get("timestamp") or ""
                    elif name == "PayBounties":
                        faction = event.get("Faction")
                        if isinstance(faction, str) and faction:
                            active.pop(faction, None)
                            last_commit.pop(faction, None)
                        else:
                            active.clear()
                            last_commit.clear()
                    elif name == "Resurrect":
                        active.clear()
                        last_commit.clear()
        except OSError:
            continue

    return active, last_commit
