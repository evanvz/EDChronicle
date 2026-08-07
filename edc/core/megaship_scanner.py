"""One-shot full-history scan to reconstruct which megaships have already
been visited, at app startup — mirrors bounty_scanner.py's reasoning.
A megaship's Ship Uplinks (the real merit source, confirmed by journal
cross-reference) are a fixed, exhaustible set per megaship and can sit in a
system for many days/sessions, so "already visited" must survive app
restarts, not just live from whenever the app happened to be running.

Visited = a SupercruiseDestinationDrop whose Type matches a megaship
SignalName already seen via FSSSignalDiscovered in that same system.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Set

from edc.core.megaship_tracker import MegashipTracker


def scan_visited_megaships(journal_dir: Path) -> Set[str]:
    journal_dir = Path(journal_dir)
    if not journal_dir.exists():
        return set()

    visited: Set[str] = set()
    for path in sorted(journal_dir.glob("Journal.*.log")):
        system_address = None
        known_megaships = {}  # system_address -> {signal_name}
        try:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if (
                        '"FSDJump"' not in line and '"Location"' not in line
                        and '"FSSSignalDiscovered"' not in line
                        and '"SupercruiseDestinationDrop"' not in line
                    ):
                        continue
                    try:
                        event = json.loads(line)
                    except Exception:
                        continue
                    name = event.get("event")
                    if name in ("FSDJump", "Location"):
                        addr = event.get("SystemAddress")
                        if isinstance(addr, int):
                            system_address = addr
                    elif name == "FSSSignalDiscovered":
                        if event.get("SignalType") == "Megaship" and system_address is not None:
                            signal_name = event.get("SignalName")
                            if isinstance(signal_name, str) and signal_name:
                                known_megaships.setdefault(system_address, set()).add(signal_name)
                    elif name == "SupercruiseDestinationDrop":
                        drop_type = event.get("Type")
                        if (
                            isinstance(drop_type, str) and system_address is not None
                            and drop_type in known_megaships.get(system_address, set())
                        ):
                            visited.add(MegashipTracker.key(system_address, drop_type))
        except OSError:
            continue

    return visited
