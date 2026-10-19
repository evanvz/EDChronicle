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
from datetime import datetime, timedelta
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
