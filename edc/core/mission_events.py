"""Shared mission event handling — used by both the live event engine and
mission_scanner.py (full journal-history replay at startup), so the two
can't drift. Tracks currently-active (accepted, not yet completed/failed/
abandoned) missions, keyed by MissionID, so the Player Faction tab can
show which missions actually help the squadron-aligned faction.
"""
from __future__ import annotations

from typing import Any, Dict

MISSION_EVENT_NAMES = {
    "MissionAccepted", "MissionCompleted", "MissionFailed",
    "MissionAbandoned", "MissionRedirected",
}


def apply_mission_event(active: Dict[int, Dict[str, Any]], event: Dict[str, Any]) -> None:
    name = event.get("event")
    mission_id = event.get("MissionID")
    if not isinstance(mission_id, int):
        return

    if name == "MissionAccepted":
        active[mission_id] = {
            "name": event.get("Name"),
            "localised_name": event.get("LocalisedName") or event.get("Name"),
            "faction": event.get("Faction"),
            "influence": event.get("Influence"),
            "reputation": event.get("Reputation"),
            "destination_system": event.get("DestinationSystem"),
            "destination_station": event.get("DestinationStation"),
            "expiry": event.get("Expiry"),
            "target_faction": event.get("TargetFaction"),
            "wing": bool(event.get("Wing")),
            "kill_count": event.get("KillCount"),
            "kills_credited": 0,
        }
    elif name in ("MissionCompleted", "MissionFailed", "MissionAbandoned"):
        active.pop(mission_id, None)
    elif name == "MissionRedirected":
        rec = active.get(mission_id)
        if rec:
            new_system = event.get("NewDestinationSystem")
            new_station = event.get("NewDestinationStation")
            if new_system:
                rec["destination_system"] = new_system
            if new_station:
                rec["destination_station"] = new_station


def credit_massacre_kill(active: Dict[int, Dict[str, Any]], victim_faction: Any, current_system: Any) -> None:
    """One kill (Bounty or FactionKillBond -- a kill against a faction with
    no individual bounty on the ship pays out as FactionKillBond only, never
    fires Bounty at all) credits exactly one currently-active massacre
    mission against that faction in the mission's destination system --
    the oldest-accepted one not yet at its kill_count.

    Previously credited every stacked mission simultaneously, on the
    assumption that's real game behavior. Confirmed wrong live: with two
    stacked missions (32 and 20 kills) against the same faction/system,
    21 kills after the second's acceptance made this code show it as
    20/20 (ready to turn in) while the game itself only had it at 11/20.
    The journal exposes no per-mission kill-credit signal at all (the
    "Missions" event carries no progress field), so there's no way to
    reconstruct the game's true per-mission split -- crediting one mission
    at a time undercounts instead, which just means checking a bit early
    rather than a wasted trip to a station that refuses the turn-in."""
    if not isinstance(victim_faction, str) or not victim_faction:
        return
    for rec in (active or {}).values():
        kill_count = rec.get("kill_count")
        if (
            isinstance(kill_count, int)
            and rec.get("target_faction") == victim_faction
            and rec.get("destination_system") == current_system
            and rec.get("kills_credited", 0) < kill_count
        ):
            rec["kills_credited"] = rec.get("kills_credited", 0) + 1
            return
