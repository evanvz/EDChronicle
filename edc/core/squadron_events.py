"""Shared squadron event handling — used by both the live event engine
(applied to GameState) and squadron_scanner.py (applied to a plain dict
during full journal-history replay at startup), so the two can't drift.

Journal-exposed squadron data is limited to name/rank and membership
transitions — no member roster, chat, or wing-mission data is available
to third-party tools.
"""
from __future__ import annotations

from typing import Any, Dict

_MEMBERSHIP_EVENTS = {
    "JoinedSquadron", "AppliedToSquadron", "InvitedToSquadron",
    "LeftSquadron", "KickedFromSquadron", "DisbandedSquadron", "SquadronCreated",
}

SQUADRON_EVENT_NAMES = _MEMBERSHIP_EVENTS | {
    "SquadronStartup", "SquadronPromotion", "SquadronDemotion", "WonATrophyForSquadron",
}


def apply_squadron_event(current: Dict[str, Any], event: Dict[str, Any]) -> Dict[str, Any]:
    """
    current keys: name, rank, rank_history (list), trophies (int), status,
    status_timestamp. Mutates and returns current.
    """
    name = event.get("event")
    squadron_name = event.get("SquadronName")

    if name == "SquadronStartup":
        current["name"] = squadron_name or current.get("name")
        current["rank"] = event.get("CurrentRank")

    elif name in ("SquadronPromotion", "SquadronDemotion"):
        new_rank = event.get("NewRank")
        if isinstance(new_rank, int):
            current["rank"] = new_rank
        history = current.setdefault("rank_history", [])
        history.append({
            "timestamp": event.get("timestamp"),
            "old_rank": event.get("OldRank"),
            "new_rank": new_rank,
            "promotion": name == "SquadronPromotion",
        })

    elif name == "WonATrophyForSquadron":
        current["trophies"] = current.get("trophies", 0) + 1
        if squadron_name:
            current["name"] = squadron_name

    elif name in _MEMBERSHIP_EVENTS:
        if squadron_name:
            current["name"] = squadron_name
        current["status"] = name
        current["status_timestamp"] = event.get("timestamp")

    return current
