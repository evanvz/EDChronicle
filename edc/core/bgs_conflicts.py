"""Shared BGS War/CivilWar conflict lookups — used by both the live
ShipTargeted alert (event_engine.py) and the Combat Contacts table
(combat_panel.py) so the two don't drift out of sync.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def find_squadron_war_enemy(factions: List[dict], system_conflicts: List[dict]) -> Optional[str]:
    """
    Returns the name of the faction currently opposing our squadron-aligned
    faction in an active War/CivilWar in the current system, or None if
    we're not in a squadron-aligned faction or it isn't at war here.
    """
    squadron_faction_name = None
    for f in (factions or []):
        if isinstance(f, dict) and f.get("SquadronFaction") is True:
            squadron_faction_name = f.get("Name")
            break
    if not squadron_faction_name:
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
        if squadron_faction_name == f1_name:
            return f2_name
        if squadron_faction_name == f2_name:
            return f1_name
    return None
