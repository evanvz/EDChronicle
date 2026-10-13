# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the GNU General Public License v3.0 or later (GPL-3.0-or-later).
# See the LICENSE file in the project root for full terms.

"""BGS Experiment Log: per-tick results for the squad's test systems.

Each row is one tick window [tick, next tick): our own effort in it (from the
activity the app records), its SINC points, the faction's influence seen during
the window (influence only changes at a tick, so any visit gives the level) and
the level after the next tick, the change as a share of headroom, and the 6-8%
likely ceiling (edc.core.bgs_points). A window with no visit has no level --
jump into each test system once after every tick.
"""
from __future__ import annotations

import json
from typing import Callable, List, Optional

from edc.core.bgs_points import bucket_points, ceiling, total_points


def _states(active: Optional[str], pending: Optional[str]) -> str:
    names = []
    for raw, suffix in ((active, ""), (pending, " (pending)")):
        try:
            names += [f"{s.get('State')}{suffix}" for s in json.loads(raw or "[]") if s.get("State")]
        except (ValueError, TypeError, AttributeError):
            pass
    return ", ".join(names)


def build_rows(ticks: List[str], readings: List[tuple], effort_for: Callable[[str, str], dict],
               now: Optional[str] = None, visits: Optional[List[tuple]] = None,
               faction_readings: Optional[dict] = None, faction: str = "") -> List[dict]:
    """ticks: tick times oldest first (...Z); readings: (observed_at, influence,
    active_states, pending_states) oldest first; effort_for(start, end) -> the
    activity dict for that window. Newest window first; the last one is still
    open (end None) and runs to `now`.

    Contamination checks (we can't see other commanders' work directly):
    visits = [(observed_at, event, source)] -- EDDN jumps/dockings minus our own
    (same event timestamp as our 'journal' rows) count as other visitors;
    faction_readings = {faction: [(observed_at, influence)]} -- any faction other
    than `faction` gaining over the tick means someone worked for it."""
    rows = []
    bounds = list(ticks) + [None]
    visits = visits or []
    own = {(v[0], v[1]) for v in visits if v[2] == "journal"}

    def at(series, start, end):
        seen = [r for r in series if r[0] >= start and (end is None or r[0] < end)]
        return seen[-1][1] if seen else None

    def level(start, end):
        seen = [r for r in readings if r[0] >= start and (end is None or r[0] < end)]
        return seen[-1] if seen else None

    for i, start in enumerate(ticks):
        end = bounds[i + 1]
        during = level(start, end)
        after = level(end, bounds[i + 2]) if end is not None else None
        effort = effort_for(start, end or now or "9999")
        before = during[1] if during else None
        after_inf = after[1] if after else None
        change = (after_inf - before) * 100 if before is not None and after_inf is not None else None
        rows.append({
            "start": start, "end": end, "effort": effort,
            "points": total_points(bucket_points(effort["tier_score"], effort["bounties"],
                                                 effort["trade_profit"], effort["exploration"])),
            "before": before, "after": after_inf, "change": change,
            "share": change / ((1 - before) * 100) * 100 if change is not None and before < 1 else None,
            "ceiling": ceiling(before),
            "states": _states(during[2], during[3]) if during else "",
        })
        stop = end or now or "9999"
        rows[-1]["other_visits"] = sum(1 for v in visits if v[2] == "eddn" and start <= v[0] < stop
                                       and (v[0], v[1]) not in own)
        up = []
        for name, series in (faction_readings or {}).items():
            if name.lower() == faction.lower() or end is None:
                continue
            b, a = at(series, start, end), at(series, end, bounds[i + 2])
            if b is not None and a is not None and (a - b) * 100 >= 0.1:
                up.append(name)
        rows[-1]["factions_up"] = sorted(up)
        # Influence should only change at a tick; differing readings inside one window
        # mean an update tick.edcd.io didn't list (seen live at Ekono, 2026-10-12/13).
        inside = {round(r[1], 4) for r in readings if r[0] >= start and (end is None or r[0] < end)}
        rows[-1]["unlisted_update"] = len(inside) > 1
        rows[-1]["contaminated"] = bool(rows[-1]["other_visits"] or up or rows[-1]["unlisted_update"])
    return rows[::-1]
