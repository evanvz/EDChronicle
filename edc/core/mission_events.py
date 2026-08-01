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
