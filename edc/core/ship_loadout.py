"""Classifies a ship's fitted hardpoint modules as armed/unarmed — used to
warn when an enemy contact is scanned but the player's current ship has no
weapons fitted at all, regardless of the target's own fit.
"""
from __future__ import annotations

import re
from typing import Any, List

_HARDPOINT_SLOT_RE = re.compile(r"^(Tiny|Small|Medium|Large|Huge)Hardpoint\d+$")

# Substrings of Elite Dangerous's internal hardpoint module names (hpt_...)
# that indicate an actual offensive weapon. Deliberately excludes mining
# tools (mining laser, abrasion blaster, seismic charge launcher, sub-surface
# displacement missile) and hardpoint-mounted utility modules (scanners,
# point defence, chaff) — none of those make a ship "armed" for combat.
_WEAPON_NAME_SUBSTRINGS = (
    "pulselaser", "beamlaser", "multicannon", "cannon", "railgun",
    "plasmaaccelerator", "missilerack", "torppylon", "minelauncher",
    "flakmortar", "shockcannon", "slugshot", "causticmissile",
    "guardian_plasmalauncher", "guardian_shardcannon", "guardian_gausscannon",
    "remotereleaseflechettelauncher",
)


def has_any_weapon(modules: List[Any]) -> bool:
    """Returns True if any hardpoint slot in a Loadout event's Modules
    array is fitted with a recognized offensive weapon."""
    for m in (modules or []):
        if not isinstance(m, dict):
            continue
        slot = str(m.get("Slot") or "")
        if not _HARDPOINT_SLOT_RE.match(slot):
            continue
        item = str(m.get("Item") or "").lower()
        if any(sub in item for sub in _WEAPON_NAME_SUBSTRINGS):
            return True
    return False
