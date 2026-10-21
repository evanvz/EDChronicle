# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the GNU General Public License v3.0 or later (GPL-3.0-or-later).
# See the LICENSE file in the project root for full terms.

"""Per-system ticks inferred from the system's own readings.

Faction influence and states only change when a system ticks, so two
readings of a system that differ prove it ticked between them -- whatever
the galaxy-wide tick sources say (tick.edcd.io listed no tick for 2026-10-18
while Ekono still moved). The reverse doesn't hold: a system can tick with
nothing changing, so global ticks stay the base and these only add to them.

Stale uploads can show old values after new ones (EDCAS tick.rs notes), so a
change is confirmed only if it came from our own journal or the next reading
agrees with it.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

INFLUENCE_EPS = 0.0005   # below this the sources only differ in rounding
PROPAGATION = timedelta(hours=12)   # a system can update up to 12 h after the tick (SINC BGS protocol)


def _minus_propagation(ts: str) -> str:
    return (datetime.strptime(str(ts)[:19], "%Y-%m-%dT%H:%M:%S") - PROPAGATION).strftime("%Y-%m-%dT%H:%M:%SZ")


def _state_names(raw: Optional[str]) -> Tuple[str, ...]:
    try:
        return tuple(sorted(s.get("State") for s in json.loads(raw or "[]") if s.get("State")))
    except (ValueError, TypeError, AttributeError):
        return ()


def _snapshots(rows: List[tuple]) -> List[dict]:
    """rows (observed_at, faction, influence, active, pending, source), oldest
    first -> one snapshot per upload time: {at, source, factions: {name: (inf, states)}}."""
    snaps: List[dict] = []
    for at, faction, inf, active, pending, source in rows:
        if not isinstance(inf, (int, float)):
            continue
        if not snaps or snaps[-1]["at"] != at:
            snaps.append({"at": at, "source": source, "factions": {}})
        # pending names marked apart: pending -> active is itself a tick
        snaps[-1]["factions"][faction] = (inf, _state_names(active) + tuple(f"pending:{s}" for s in _state_names(pending)))
    return snaps


def _differs(a: dict, b: dict) -> bool:
    common = set(a) & set(b)
    return any(abs(a[f][0] - b[f][0]) > INFLUENCE_EPS or a[f][1] != b[f][1] for f in common)


def infer_system_ticks(rows: List[tuple]) -> List[Dict[str, object]]:
    """[{"after": last reading with the old values, "by": first reading with
    the new ones, "confirmed": bool}], oldest first."""
    snaps = _snapshots(rows)
    out = []
    for i in range(1, len(snaps)):
        prev, cur = snaps[i - 1], snaps[i]
        if not _differs(prev["factions"], cur["factions"]):
            continue
        nxt = snaps[i + 1] if i + 1 < len(snaps) else None
        confirmed = cur["source"] == "journal" or (nxt is not None and not _differs(cur["factions"], nxt["factions"]))
        out.append({"after": prev["at"], "by": cur["at"], "confirmed": confirmed})
    return out


def merge_ticks(global_ticks: List[str], system_ticks: List[Dict[str, object]]) -> Tuple[List[str], Dict[str, dict]]:
    """Global ticks plus confirmed system ticks that no global tick explains,
    placed at "by" (the first reading that shows the change). A global tick
    explains a change if it falls before "by" and no more than 12 h before
    "after" -- the old reading may simply predate the system's update.
    Returns (sorted tick times, {added time: the system tick})."""
    added: Dict[str, dict] = {}
    for st in system_ticks:
        if not st["confirmed"]:
            continue
        if any(_minus_propagation(st["after"]) < g <= st["by"] for g in global_ticks):
            continue
        added[str(st["by"])] = st
    return sorted(set(global_ticks) | set(added)), added


MIN_SYSTEMS_FOR_GLOBAL = 2      # one system can be a fluke; two agreeing is a tick nobody listed


def promote_missed_ticks(repo, now: Optional[datetime] = None) -> Optional[Tuple[str, str]]:
    """When several monitored systems show a confirmed change that no stored
    tick explains, and their gaps overlap, the galaxy ticked unseen (tick.edcd.io
    missed 2026-10-18; four systems showed it). Records it as a 'systems' tick
    known only as the range (latest old reading .. earliest new reading), so
    every "since last tick" view picks it up. Returns (start, end) or None."""
    now = now or datetime.now(timezone.utc)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    since = (now - timedelta(days=4)).strftime(fmt)
    global_ticks = repo.get_bgs_ticks(since=(now - timedelta(days=14)).strftime(fmt))
    gaps = []
    for addr in repo.get_recently_read_systems(since):
        for st in infer_system_ticks(repo.get_system_readings(addr)):
            if not st["confirmed"] or str(st["by"]) < since:
                continue
            if any(_minus_propagation(st["after"]) < g <= st["by"] for g in global_ticks):
                continue
            gaps.append((str(st["after"]), str(st["by"])))
    # the moment most systems' gaps share (ties: the latest); their overlap is the tick's range
    best = max(({b for _, b in gaps}), key=lambda p: (sum(1 for a, b in gaps if a < p <= b), p), default=None)
    if best is None:
        return None
    group = [(a, b) for a, b in gaps if a < best <= b]
    start, end = max(a for a, _ in group), min(b for _, b in group)
    if len(group) < MIN_SYSTEMS_FOR_GLOBAL or start >= end or (global_ticks and start < max(global_ticks)):
        return None
    repo.record_bgs_tick(start, source="systems", upper=end)
    return start, end


def tick_label(info: Optional[dict]) -> str:
    """One line for the newest tick: when, and how we know."""
    if not info:
        return "No BGS tick known yet"
    short = lambda t: str(t)[5:16].replace("T", " ")
    if info.get("source") == "systems" and info.get("upper"):
        return (f"Last tick: between {short(info['at'])} and {short(info['upper'])} UTC — seen in several "
                f"systems' own influence changes (tick.edcd.io didn't list it); activity in that range may "
                f"count for either tick")
    how = {"eddn": "our EDDN detector, ±1 h", "edcd": "tick.edcd.io"}.get(info.get("source"), "tick.edcd.io")
    return f"Last tick: {short(info['at'])} UTC ({how})"


def tick_window(repo, which: str = "current") -> Dict[str, Optional[str]]:
    """{"since", "until", "text"} for the current tick window (since the newest
    tick) or the previous one (between the last two) -- what Session Activity and
    BGS Tasks show, so yesterday's work can still be read and copied after a tick."""
    ticks = repo.get_tick_info(2)
    newest = ticks[0] if ticks else None
    if which == "previous" and len(ticks) == 2:
        short = lambda t: str(t)[5:16].replace("T", " ")
        return {"since": ticks[1]["at"], "until": newest["at"],
                "text": f"Previous tick window: {short(ticks[1]['at'])} → {short(newest['at'])} UTC. {tick_label(newest)}"}
    return {"since": newest["at"] if newest else "1970-01-01T00:00:00Z", "until": None, "text": tick_label(newest)}
