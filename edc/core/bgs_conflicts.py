"""Shared BGS War/CivilWar conflict lookups and other small journal-event
parsing helpers with no single natural owner — used across event_engine.py
and its handler modules (edc/engine/handlers/*) so they don't drift out of
sync with each other. Kept dependency-free of both to avoid circular
imports (event_engine.py imports the handler modules directly).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def is_multistate_faction(faction: dict) -> bool:
    """True if a faction is in 2+ simultaneous states, counted across
    ActiveStates/PendingStates/RecoveringStates combined -- e.g. a single
    ActiveStates bucket with both War and Outbreak already qualifies, as
    does one state in each of two different buckets. A faction with just
    one state total (the common case -- nearly every faction has at least
    one active state at any given time) does not qualify."""
    total = (
        len(faction.get("ActiveStates") or [])
        + len(faction.get("PendingStates") or [])
        + len(faction.get("RecoveringStates") or [])
    )
    return total >= 2


def squadron_faction_name(factions: List[dict]) -> Optional[str]:
    """Name of the squadron-aligned faction (SquadronFaction:true in the
    journal's Factions[] array), or None if not currently known."""
    for f in (factions or []):
        if isinstance(f, dict) and f.get("SquadronFaction") is True:
            return f.get("Name")
    return None


def find_squadron_war_enemy(factions: List[dict], system_conflicts: List[dict]) -> Optional[str]:
    """
    Returns the name of the faction currently opposing our squadron-aligned
    faction in an active War/CivilWar in the current system, or None if
    we're not in a squadron-aligned faction or it isn't at war here.
    """
    squadron_faction = squadron_faction_name(factions)
    if not squadron_faction:
        return None

    for c in (system_conflicts or []):
        if not isinstance(c, dict):
            continue
        if str(c.get("WarType", "")).lower() not in ("war", "civilwar"):
            continue
        if str(c.get("Status", "")).lower() != "active":
            continue
        f1_name = (c.get("Faction1") or {}).get("Name")
        f2_name = (c.get("Faction2") or {}).get("Name")
        if squadron_faction == f1_name:
            return f2_name
        if squadron_faction == f2_name:
            return f1_name
    return None


def parse_powerplay_conflict_progress(event: Dict[str, Any]) -> Dict[str, float]:
    """
    Journal emits PowerplayConflictProgress as a list of
    {Power, ConflictProgress} records — parses into a {power_name: pct}
    dict. Previously duplicated three times (event_engine.py's Location
    and FSDJump branches, plus edc/engine/handlers/exploration.py's own
    FSDJump handling of the same event) with inconsistent overwrite
    semantics between copies — always call this and assign its result
    unconditionally (even when empty), rather than only overwriting when
    truthy, so leaving a contested system correctly clears stale progress
    instead of leaving the previous system's numbers on screen.
    """
    prog: Dict[str, float] = {}
    for rec in (event.get("PowerplayConflictProgress") or []):
        if isinstance(rec, dict) and isinstance(rec.get("Power"), str):
            cp = rec.get("ConflictProgress")
            if isinstance(cp, (int, float)):
                prog[rec["Power"]] = float(cp)
    return prog
