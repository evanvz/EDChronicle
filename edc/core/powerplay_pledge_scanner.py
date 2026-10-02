# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the PolyForm Noncommercial License 1.0.0.
# See the LICENSE file in the project root for full terms.

"""Startup scan for the current PowerPlay pledge -- same reasoning as
squadron_scanner.py: the live bootstrap only replays the current journal
from its last jump onward, and the "Powerplay" event that carries the
pledge is written once at login, before that. Started after the game
logged in, the app otherwise thinks you're unpledged until next login.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

_PLEDGE_EVENTS = ("Powerplay", "PowerplayJoin", "PowerplayDefect", "PowerplayLeave")


def scan_powerplay_pledge(journal_dir: Path) -> Optional[Dict[str, Any]]:
    """The latest pledge state from journal history, newest file first:
    {"power": str or None (left), "rank": int|None, "merits": int|None},
    or None when no PowerPlay event was ever written."""
    journal_dir = Path(journal_dir)
    if not journal_dir.exists():
        return None
    for path in sorted(journal_dir.glob("Journal.*.log"), reverse=True):
        last = None
        try:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if '"Powerplay' not in line:
                        continue
                    try:
                        event = json.loads(line)
                    except Exception:
                        continue
                    if event.get("event") in _PLEDGE_EVENTS:
                        last = event
        except OSError:
            continue
        if last is None:
            continue
        name = last["event"]
        if name == "PowerplayLeave":
            return {"power": None, "rank": None, "merits": None}
        if name == "PowerplayDefect":
            return {"power": last.get("ToPower"), "rank": None, "merits": None}
        if name == "PowerplayJoin":
            return {"power": last.get("Power"), "rank": None, "merits": None}
        return {"power": last.get("Power"), "rank": last.get("Rank"), "merits": last.get("Merits")}
    return None


def scan_conflict_progress(journal_dir: Path) -> Dict[int, tuple]:
    """{SystemAddress: (timestamp, {power: 0-1})} from the latest jump into
    each system that carried PowerplayConflictProgress -- recovers progress
    for visits saved before the app kept it."""
    journal_dir = Path(journal_dir)
    found: Dict[int, tuple] = {}
    if not journal_dir.exists():
        return found
    for path in sorted(journal_dir.glob("Journal.*.log")):
        try:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if '"PowerplayConflictProgress"' not in line:
                        continue
                    try:
                        event = json.loads(line)
                    except Exception:
                        continue
                    addr = event.get("SystemAddress")
                    progress = {
                        p.get("Power"): float(p.get("ConflictProgress"))
                        for p in (event.get("PowerplayConflictProgress") or [])
                        if isinstance(p, dict) and isinstance(p.get("Power"), str)
                        and isinstance(p.get("ConflictProgress"), (int, float))
                    }
                    if isinstance(addr, int) and progress:
                        found[addr] = (event.get("timestamp") or "", progress)
        except OSError:
            continue
    return found


def scan_last_collects(journal_dir: Path, newest_files: int = 3) -> Dict[str, str]:
    """{commodity name lower-cased: ISO timestamp} of the latest
    PowerplayCollect per commodity in the newest journals -- the 30-minute
    allocation countdown only cares about recent ones."""
    journal_dir = Path(journal_dir)
    found: Dict[str, str] = {}
    if not journal_dir.exists():
        return found
    for path in sorted(journal_dir.glob("Journal.*.log"))[-newest_files:]:
        try:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if '"PowerplayCollect"' not in line:
                        continue
                    try:
                        event = json.loads(line)
                    except Exception:
                        continue
                    name = (event.get("Type_Localised") or event.get("Type") or "").strip().lower()
                    if name:
                        found[name] = event.get("timestamp") or ""
        except OSError:
            continue
    return found
