# EDChronicle — Copyright © 2026 CMDR B0B R0GERS
# Licensed under the GNU General Public License v3.0 or later (GPL-3.0-or-later).
# See the LICENSE file in the project root for full terms.
"""Expansion Forecast: where the squadron faction's next BGS expansion is
likely to land, and where the last one landed. Rules are community-
researched (squad bot's docs/expansion-logic.md, Complete BGS Guide 2025
pp. 63-67; SINC 2024), not Frontier documentation.
See docs/superpowers/specs/2026-10-08-expansion-forecast-design.md."""
from __future__ import annotations

import json
from datetime import date
from typing import Any, Dict, List, Optional

WATCH_THRESHOLD = 0.70
EXPANSION_THRESHOLD = 0.75
CUBE_LY = 20.0
OUTER_CUBE_LY = 30.0     # searched only when +-20 ly has no eligible system
LOOKUP_MAX = 40          # EDSM lookups per refresh: every candidate in the cube, capped (~5.5 s each)
NEW_SYSTEM_DAYS = 3
NEW_SYSTEM_MAX_INFLUENCE = 0.20   # heuristic: an expansion arrives small (YF-W 9.1%)
CURRENT_DAYS = 14                 # a presence older than this is treated as "left"
CACHE_MAX_AGE_H = 24
# an ending only counts as a successful expansion source if influence dropped at least this many
# points. The net drop the source shows varies with activity in the same tick (Ekono: -14.8, -11.1).
SOURCE_DROP_MIN = 5.0


def parse_states(raw) -> List[str]:
    """faction_snapshots state-list JSON ([{"State": ...}, ...]) -> state names."""
    if not raw:
        return []
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [str(s.get("State")) for s in data if isinstance(s, dict) and s.get("State")]


def is_expanding(snap: Optional[Dict[str, Any]]) -> bool:
    """Frontier's own "Expansion" state as the faction state or in active_states."""
    if not snap:
        return False
    if (snap.get("faction_state") or "").strip().lower() == "expansion":
        return True
    return "expansion" in {s.lower() for s in parse_states(snap.get("active_states"))}


def expansion_endings(history_asc: List[Dict[str, Any]]) -> List[tuple]:
    """[(index, snapshot_date, influence change in points)] for each day an
    expansion ended: the first day "Expansion" shows under recovering
    states (faction_state can still read "Expansion" that day, and not every
    source carries the state lists, so this is the reliable signal). The
    source system drops when its expansion finishes: Ekono lost 14.8 on
    2026-09-23 and 11.1 on 2026-10-07. Expansion state is faction-wide, so
    an ending also shows in every system that WASN'T the source, with no
    drop there (Ekono on 2026-08-09 and 09-11: other systems' expansions,
    confirmed by the squad) -- so the change is reported, not assumed."""
    out = []
    for i in range(1, len(history_asc)):
        prev, cur = history_asc[i - 1], history_asc[i]
        if ("Expansion" in parse_states(cur.get("recovering_states"))
                and "Expansion" not in parse_states(prev.get("recovering_states"))):
            delta = ((cur.get("influence") or 0.0) - (prev.get("influence") or 0.0)) * 100.0
            out.append((i, cur.get("snapshot_date"), delta))
    return out


def expansion_phase(snap: Dict[str, Any]) -> str:
    if "Expansion" in parse_states(snap.get("recovering_states")):
        return "recovering"
    if is_expanding(snap):
        return "active"
    if "Expansion" in parse_states(snap.get("pending_states")):
        return "pending"
    return ""


def days_at_or_above(history_asc: List[Dict[str, Any]], threshold: float = EXPANSION_THRESHOLD) -> int:
    """Consecutive latest snapshots at or above `threshold`."""
    n = 0
    for snap in reversed(history_asc):
        if (snap.get("influence") or 0.0) < threshold:
            break
        n += 1
    return n


def is_current(row: Dict[str, Any], today: date) -> bool:
    """Still present: influence above 0 and seen within CURRENT_DAYS."""
    last = row.get("last_seen")
    if not last or (row.get("influence") or 0.0) <= 0:
        return False
    return (today - date.fromisoformat(str(last)[:10])).days <= CURRENT_DAYS


def watched_systems(presence: List[Dict[str, Any]], histories: Dict[int, List[Dict[str, Any]]],
                    today: date) -> List[Dict[str, Any]]:
    out = []
    for r in presence:
        if not is_current(r, today) or (r.get("influence") or 0.0) < WATCH_THRESHOLD:
            continue
        hist = histories.get(r["system_address"]) or []
        out.append({**r, "days_above": days_at_or_above(hist),
                    "phase": expansion_phase(hist[-1] if hist else r)})
    return sorted(out, key=lambda w: -(w.get("influence") or 0.0))


_PHASE_TEXT = {"active": "active", "pending": "pending",
               "recovering": "recovering (cooldown after an expansion)", "": "none running"}


def faction_expansion_line(presence: List[Dict[str, Any]], histories: Dict[int, List[Dict[str, Any]]],
                           today: date) -> str:
    """The faction's expansion state in one line. Expansion is faction-wide
    (one at a time, from one source, and shown in every one of its systems
    -- seen 2026-10-09: 329 EUW systems "active", some at 1.9% influence),
    so a system's own state only says which phase its last data caught.
    The freshest snapshot gives the current phase; the last ending with a
    source-size drop gives where it last came from."""
    current = [r for r in presence if is_current(r, today)]
    if not current:
        return ""
    newest = max(current, key=lambda r: r.get("last_seen") or "")
    names = {r["system_address"]: r.get("system_name") for r in presence}
    ends = [(d, names.get(addr) or str(addr), delta)
            for addr, hist in histories.items()
            for _i, d, delta in expansion_endings(hist) if delta <= -SOURCE_DROP_MIN]
    text = (f"Faction expansion (one at a time, shown in every system): "
            f"{_PHASE_TEXT[expansion_phase(newest)]} — newest data {newest.get('last_seen')} "
            f"({newest.get('system_name')}).")
    if ends:
        d, src, _delta = max(ends)
        text += f" Last expansion ended {d} from {src}."
    return text


def likely_source(watched: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Highest influence among systems at or above 75% for at least a day;
    otherwise the highest watched system, marked not yet eligible."""
    eligible = [w for w in watched if w["days_above"] >= 1]
    if eligible:
        return {**eligible[0], "eligible": True}
    return {**watched[0], "eligible": False} if watched else None


def in_cube(src: tuple, xyz: tuple, half: float = CUBE_LY) -> bool:
    """Expansion searches a cube (each axis within `half`), not a sphere."""
    return all(abs(a - b) <= half for a, b in zip(src, xyz))


def rank_candidates(cands: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Tier 1: <7 factions, no known history; tier 2: <7, faction was there
    before; tier 3: exactly 7 (invasion war). 8+ and systems where the
    faction is present now are dropped; not-looked-up rows go last."""
    ranked, unchecked = [], []
    for c in cands:
        if c.get("faction_present"):
            continue
        n = c.get("faction_count")
        if n is None:
            unchecked.append({**c, "tier": None})
            continue
        if n >= 8:
            continue
        tier = 3 if n == 7 else (2 if c.get("been_before") else 1)
        ranked.append({**c, "tier": tier})
    # the +-20 ly ring (all tiers) comes before the +-30 ly ring
    ranked.sort(key=lambda c: (c.get("ring") or CUBE_LY, c["tier"], c.get("distance_ly") or 0.0))
    unchecked.sort(key=lambda c: c.get("distance_ly") or 0.0)
    return ranked + unchecked


def predicted_targets(ranked: List[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    """The likely target under each order of the disputed tiers: tier 2
    (retreated from before) vs tier 3 (7 factions, invasion war). The squad
    bot's notes put retreated first ("EUW's own assessment"); per those
    notes the Complete BGS Guide puts the invasion first, and the squad
    reports retreated-first has been proven wrong in practice (2026-10-09).
    Tier 1 and the +-20 ly ring always come first either way."""
    eligible = [c for c in ranked if c.get("tier")]

    def pick(order):
        best = min(eligible, key=lambda c: (c.get("ring") or CUBE_LY, order[c["tier"]],
                                            c.get("distance_ly") or 0.0), default=None)
        return best["system_name"] if best else None
    return {"retreat_first": pick({1: 1, 2: 2, 3: 3}), "invasion_first": pick({1: 1, 3: 2, 2: 3})}


def new_systems(presence: List[Dict[str, Any]], endings: List[tuple], today: date,
                days: int = NEW_SYSTEM_DAYS, coords: Optional[Dict[str, tuple]] = None) -> List[Dict[str, Any]]:
    """Systems the faction first appeared in within `days`, small (<= 20%),
    paired with an expansion ending within +-1 day: endings are
    [(source system name, "YYYY-MM-DD"), ...]. A source must also lie within
    30 ly (the game's extended search cube) of the new system, per `coords`
    {name: (x, y, z)}; the nearest qualifying source wins, none without coords."""
    coords = coords or {}
    out = []
    for r in presence:
        first, inf = r.get("first_seen"), r.get("influence") or 0.0
        if not first or not 0 < inf <= NEW_SYSTEM_MAX_INFLUENCE:
            continue
        seen = date.fromisoformat(str(first)[:10])
        if seen > today or (today - seen).days > days:
            continue
        new_xyz = coords.get(r.get("system_name"))
        near = []
        for name, d in endings:
            src_xyz = coords.get(name)
            if (name != r.get("system_name") and new_xyz and src_xyz
                    and abs((date.fromisoformat(str(d)[:10]) - seen).days) <= 1
                    and in_cube(src_xyz, new_xyz, half=30.0)):
                near.append((sum((a - b) ** 2 for a, b in zip(src_xyz, new_xyz)), name))
        source = min(near)[1] if near else None
        # no source-size drop within range -> not an expansion: most likely the
        # faction's own colonisation (or a system first reported late)
        out.append({"system_name": r.get("system_name"), "influence": inf,
                    "first_seen": str(first)[:10], "source": source,
                    "kind": "expansion" if source else "colonisation"})
    return sorted(out, key=lambda x: x["first_seen"], reverse=True)


def alert_text(faction: str, item: Dict[str, Any]) -> str:
    pct = f"{item['influence'] * 100:.1f}%"
    if item.get("source"):
        return f"🆕 {faction} entered {item['system_name']} ({pct}) — likely expansion from {item['source']}"
    return (f"🆕 {faction} appeared in {item['system_name']} ({pct}) — no expansion source in range, "
            "likely colonisation")


def first_expansion(items: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The newest item that is an expansion (has a source), if any."""
    return next((n for n in items if n.get("source")), None)


def detect_new_systems(repo, faction: str, today: Optional[date] = None) -> List[Dict[str, Any]]:
    """new_systems() from the repository: expansion endings are only looked
    for in faction systems at 50%+ (a source sits near 60-70% after its
    expansion ends), to keep it to a few history queries."""
    today = today or date.today()
    presence = repo.get_squadron_presence(faction)
    endings = []
    for r in presence:
        if (r.get("influence") or 0.0) >= 0.5:
            hist = list(reversed(repo.get_faction_history(r["system_address"], faction)))
            endings += [(r["system_name"], d) for _i, d, delta in expansion_endings(hist)
                        if delta <= -SOURCE_DROP_MIN]
    names = {r["system_name"] for r in presence} | {n for n, _d in endings}
    return new_systems(presence, endings, today, coords=repo.get_system_coords_for_names(sorted(names)))
