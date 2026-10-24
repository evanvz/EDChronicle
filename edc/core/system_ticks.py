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
_TRUSTED = ("journal", "edsm")
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
        agreed = nxt is not None and not _differs(cur["factions"], nxt["factions"])
        confirmed = cur["source"] == "journal" or agreed
        # trusted: seen by us (journal) or EDSM, not only by unauthenticated EDDN uploads
        trusted = cur["source"] in _TRUSTED or (agreed and nxt["source"] in _TRUSTED)
        out.append({"after": prev["at"], "by": cur["at"], "confirmed": confirmed, "trusted": trusted})
    return out


def _explained(st: dict, earlier: List[dict], global_ticks: List[str]) -> bool:
    """A global tick explains a change if it falls before "by" and no more than
    12 h before "after" (the old reading may predate the system's update) --
    unless the system already changed after that tick: a tick moves a system
    once (ICZ RY-R b4-2 had updated for 10-21 03:49 by 10-21 15:48, so its
    next change was a new tick)."""
    return any(_minus_propagation(st["after"]) < g <= st["by"]
               and not any(g < e["by"] <= st["after"] for e in earlier)
               for g in global_ticks)


def merge_ticks(global_ticks: List[str], system_ticks: List[Dict[str, object]]) -> Tuple[List[str], Dict[str, dict]]:
    """Global ticks plus confirmed system ticks that no global tick explains,
    placed at "by" (the first reading that shows the change). A global tick
    explains a change if it falls before "by" and no more than 12 h before
    "after" -- the old reading may simply predate the system's update (see _explained).
    Returns (sorted tick times, {added time: the system tick})."""
    added: Dict[str, dict] = {}
    for i, st in enumerate(system_ticks):
        if not st["confirmed"]:
            continue
        if _explained(st, system_ticks[:i], global_ticks):
            continue
        added[str(st["by"])] = st
    return sorted(set(global_ticks) | set(added)), added


MIN_SYSTEMS_FOR_GLOBAL = 3      # one system can be a fluke; three agreeing is a tick nobody listed
MAX_GAP = timedelta(hours=48)   # a longer old..new gap says too little about when the tick was


def promote_missed_ticks(repo, now: Optional[datetime] = None) -> Optional[Tuple[str, str]]:
    """When several monitored systems show a change that no stored tick
    explains, and their gaps overlap, the galaxy ticked unseen (tick.edcd.io
    missed 2026-10-18; four systems showed it). A change doesn't wait for a
    second reading to agree: most systems are only read once a day, so that
    held the 10-20/10-21 ticks back (only trusted readings count, and three
    systems must overlap instead). Records it as a 'systems' tick
    known only as the range (latest old reading .. earliest new reading), so
    every "since last tick" view picks it up. Returns (start, end) or None."""
    now = now or datetime.now(timezone.utc)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    since = (now - timedelta(days=4)).strftime(fmt)
    latest_ok = (now + timedelta(minutes=5)).strftime(fmt)
    global_ticks = repo.get_bgs_ticks(since=(now - timedelta(days=14)).strftime(fmt))
    gaps = []
    for addr in repo.get_recently_read_systems(since):
        # trusted readings only (our journal, EDSM) on BOTH sides of the change:
        # EDDN is unauthenticated, so it can't make, widen or shift a promoted tick
        trusted_rows = [r for r in repo.get_system_readings(addr) if r[5] in _TRUSTED]
        changes = infer_system_ticks(trusted_rows)
        for i, st in enumerate(changes):
            if str(st["by"]) < since or str(st["by"]) > latest_ok:
                continue
            gap = (datetime.strptime(str(st["by"])[:19], "%Y-%m-%dT%H:%M:%S")
                   - datetime.strptime(str(st["after"])[:19], "%Y-%m-%dT%H:%M:%S"))
            if gap > MAX_GAP:
                continue
            if _explained(st, changes[:i], global_ticks):
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


SAMPLE_AFTER = timedelta(hours=20)   # no tick known for this long: one was probably missed
SAMPLE_EVERY = timedelta(hours=2)
SAMPLE_SYSTEMS = 10
_last_sample: Optional[datetime] = None


def sample_for_missed_tick(repo, fetch, now: Optional[datetime] = None) -> int:
    """After the app was closed over a tick (no tick known for 20 h), read a few
    monitored systems from EDSM now instead of waiting for the once-a-day full
    refresh: their new readings plus the ones from before the gap bracket the
    tick for promote_missed_ticks. Systems whose newest trusted reading is
    6-48 h old, newest first. fetch = edsm_faction_lookup.fetch_system_factions.
    Returns the number of systems read (0 = not needed or not due)."""
    global _last_sample
    now = now or datetime.now(timezone.utc)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    info = repo.get_tick_info(1)
    # a promoted tick is known only as a range: its end is when it was last seen
    newest = (info[0].get("upper") or info[0]["at"]) if info else None
    if newest and now - datetime.strptime(newest[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc) < SAMPLE_AFTER:
        return 0
    if _last_sample and now - _last_sample < SAMPLE_EVERY:
        return 0
    _last_sample = now
    read = 0
    for addr, name in repo.get_systems_to_sample((now - MAX_GAP).strftime(fmt),
                                                 (now - timedelta(hours=6)).strftime(fmt), SAMPLE_SYSTEMS):
        result, _err = fetch(name)
        if not result:
            continue
        with repo.db.deferred_commit():
            for f in result["factions"]:
                f = dict(f)
                is_controlling = bool(f.pop("is_controlling", False))
                repo.save_faction_snapshot(result["system_address"], f, now.date().isoformat(), is_controlling,
                                           f.pop("LastUpdate", None), "edsm")
        read += 1
    return read


def confirm_ticks(repo, now: Optional[datetime] = None) -> List[str]:
    """EDDN-detected ticks of the last 3 days that a system's own readings now
    back: a change (from any source, EDDN included -- every reading is evidence
    here, it only clears the "unconfirmed" note) that the tick explains. One
    system is enough; a tick is never removed for lack of one. Returns the ticks
    confirmed now."""
    now = now or datetime.now(timezone.utc)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    since = (now - timedelta(days=3)).strftime(fmt)
    open_ticks = [t["at"] for t in repo.get_tick_info(10) if not t["confirmed"] and t["at"] >= since]
    if not open_ticks:
        return []
    done = []
    for addr in repo.get_recently_read_systems(min(open_ticks)):
        for st in infer_system_ticks(repo.get_system_readings(addr)):
            for t in open_ticks:
                if t not in done and _minus_propagation(st["after"]) < t <= st["by"]:
                    repo.confirm_bgs_tick(t)
                    done.append(t)
        if len(done) == len(open_ticks):
            break
    return done


def tick_label(info: Optional[dict]) -> str:
    """One line for the newest tick: when, and how we know."""
    if not info:
        return "No BGS tick known yet"
    short = lambda t: str(t)[5:16].replace("T", " ")
    if info.get("source") == "systems" and info.get("upper"):
        return (f"Last tick: between {short(info['at'])} and {short(info['upper'])} UTC — seen in several "
                f"systems' own influence changes (tick.edcd.io didn't list it); activity in that range may "
                f"count for either tick")
    how = {"eddn": "our EDDN detector, ±1 h", "edcd": "tick.edcd.io", "hub": "EDDataHub"}.get(
        info.get("source"), "tick.edcd.io")
    if info.get("confirmed") is False:
        how += "; unconfirmed until a system's readings show it"
    return f"Last tick: {short(info['at'])} UTC ({how})"


def tick_window(repo, which="current") -> Dict[str, Optional[str]]:
    """{"since", "until", "text"} for the current tick window (since the newest
    tick), the previous one (between the last two), or `which` = n windows back
    -- what Session Activity and BGS Tasks show, so earlier work can still be
    read and copied after a tick (or two: a missed tick recorded later pushes it back)."""
    back = {"current": 0, "previous": 1}.get(which, which)
    ticks = repo.get_tick_info(back + 1)
    newest = ticks[0] if ticks else None
    if back and len(ticks) == back + 1:
        short = lambda t: str(t)[5:16].replace("T", " ")
        name = "Previous tick window" if back == 1 else f"Tick window {back} back"
        since, until = ticks[back]["at"], ticks[back - 1]["at"]
        return {"since": since, "until": until,
                "text": f"{name}: {short(since)} → {short(until)} UTC. {tick_label(newest)}"}
    return {"since": newest["at"] if newest else "1970-01-01T00:00:00Z", "until": None, "text": tick_label(newest)}
