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


def _seconds(earlier, later) -> float:
    from datetime import datetime
    try:
        a = datetime.fromisoformat(str(earlier).replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(later).replace("Z", "+00:00"))
    except ValueError:
        return float("inf")
    return (b - a).total_seconds()


def scan_deliveries(journal_dir: Path) -> Dict[str, Dict[str, Any]]:
    """{system name lower-cased: {"timestamp","type","count","merits"}} --
    the latest PowerplayDeliver per system and the merits from the
    PowerplayMerits event that follows it."""
    journal_dir = Path(journal_dir)
    found: Dict[str, Dict[str, Any]] = {}
    if not journal_dir.exists():
        return found
    for path in sorted(journal_dir.glob("Journal.*.log")):
        system, pending = None, None
        try:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if '"Powerplay' not in line and '"StarSystem"' not in line:
                        continue
                    try:
                        event = json.loads(line)
                    except Exception:
                        continue
                    name = event.get("event")
                    if name in ("FSDJump", "Location", "CarrierJump"):
                        system = event.get("StarSystem") or system
                    elif name == "PowerplayDeliver" and system:
                        # merits in the next 60s add up (one hand-in can pay in
                        # several PowerplayMerits events)
                        pending = {"timestamp": event.get("timestamp") or "", "count": event.get("Count") or 0,
                                   "type": event.get("Type_Localised") or event.get("Type") or "", "merits": 0}
                        found[system.lower()] = pending
                    elif name == "PowerplayCollect":
                        pending = None
                    elif name == "PowerplayMerits" and pending:
                        gained = event.get("MeritsGained")
                        if isinstance(gained, int) and _seconds(pending["timestamp"], event.get("timestamp")) <= 60:
                            pending["merits"] += gained
                        else:
                            pending = None
        except OSError:
            continue
    return found


def add_collect(batches: Dict[str, Dict[str, Any]], commodity: str, station: str, system: str,
                timestamp: str, count: int, window_min: int = 30) -> Optional[float]:
    """Tonnes taken per commodity in the current allocation window: a
    collect at the same station within window_min of the previous one adds
    to it, anything else starts a new one. "recent" keeps the last collect
    per system -- each station has its own allocation pool (confirmed in
    game 2026-10-03), so another supporting system can still be full.
    Returns the minutes since the previous collect in this system, if any."""
    prev = batches.get(commodity)
    gap = _seconds(prev["last"], timestamp) if prev else None
    same = bool(prev and prev["station"] == (station or system or "?")
                and gap is not None and 0 <= gap <= window_min * 60)
    recent = dict((prev or {}).get("recent") or {})
    before = recent.get((system or "").lower())
    since = _seconds(before["last"], timestamp) / 60 if before else None
    if system:
        recent[system.lower()] = {"station": station or system, "last": timestamp}
    batches[commodity] = {"station": station or system or "?", "system": system,
                          "tonnes": (prev["tonnes"] if same else 0) + (count or 0), "last": timestamp,
                          "recent": recent}
    return since


def scan_last_collects(journal_dir: Path, newest_files: int = 3,
                       where: Optional[Dict[str, str]] = None,
                       batches: Optional[Dict[str, Dict[str, Any]]] = None) -> Dict[str, str]:
    """{commodity name lower-cased: ISO timestamp} of the latest
    PowerplayCollect per commodity in the newest journals -- the 30-minute
    allocation countdown only cares about recent ones. If `where` is given
    it's filled with {commodity: system it was collected in}."""
    journal_dir = Path(journal_dir)
    found: Dict[str, str] = {}
    if not journal_dir.exists():
        return found
    system = station = None
    for path in sorted(journal_dir.glob("Journal.*.log"))[-newest_files:]:
        try:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if '"PowerplayCollect"' not in line and '"StarSystem"' not in line:
                        continue
                    try:
                        event = json.loads(line)
                    except Exception:
                        continue
                    if event.get("event") in ("FSDJump", "Location", "CarrierJump", "Docked"):
                        system = event.get("StarSystem") or system
                        station = event.get("StationName")
                        continue
                    if event.get("event") != "PowerplayCollect":
                        continue
                    name = (event.get("Type_Localised") or event.get("Type") or "").strip().lower()
                    if name:
                        found[name] = event.get("timestamp") or ""
                        if where is not None and system:
                            where[name] = system
                        if batches is not None:
                            add_collect(batches, name, station or "", system or "",
                                        event.get("timestamp") or "", event.get("Count") or 0)
        except OSError:
            continue
    return found
