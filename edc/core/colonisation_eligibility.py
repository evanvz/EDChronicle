"""Colonisation eligibility lookups via EDSM's sphere-systems endpoint --
answers "which nearby systems are unpopulated and thus colonisable" and
"is this specific system eligible right now". Advisory only: EDSM's
population data is crowdsourced and can lag real-time changes.

Real game rule (verified, not guessed): a system is colonisable only if
genuinely unpopulated and within 15 ly of an existing populated system,
claimed via a System Colonisation Contact at any starport. A second
mechanic (10 ly chained expansion from your own already-built colony) is
deliberately out of scope for this module -- only the 15 ly
current-location rule is implemented.

EDSM's sphere-systems response always includes the queried center system
itself at "distance": 0. A populated system's "information" is a full
object; a genuinely unpopulated system's "information" is an empty object
{} -- confirmed live against real EDSM data during development (e.g. a
system 98.53 ly from Sol returned "information":{}).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger(__name__)

_SPHERE_URL = "https://www.edsm.net/api-v1/sphere-systems"
_TIMEOUT = 15

# EDSM's Cloudflare front-end 403s the default python-requests User-Agent
# specifically -- same fix already applied elsewhere in this codebase (see
# edc/core/edsm_faction_lookup.py's own comment for the confirmation this
# was root-caused, not guessed).
_USER_AGENT = "EDChronicle/1.0.0 (+https://github.com/evanvz/EDChronicle)"

_MAX_CANDIDATES = 20
_DEFAULT_RADIUS_LY = 15.0


def _query_sphere(system_name: str, radius_ly: float) -> Optional[List[Dict[str, Any]]]:
    """Returns the raw sphere-systems JSON array on success (always includes
    the queried system itself at distance 0), an empty list [] if EDSM's
    response is a JSON object rather than a list -- EDSM's genuine "no such
    system" signal, confirmed live -- or None on a real failure (network
    error, bad status, or any other unparseable/unexpected response)."""
    try:
        resp = requests.get(
            _SPHERE_URL,
            params={"systemName": system_name, "radius": radius_ly, "showInformation": 1},
            headers={"User-Agent": _USER_AGENT},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        log.exception("EDSM sphere-systems lookup failed for %r", system_name)
        return None
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return []
    return None


def _is_unpopulated(entry: Dict[str, Any]) -> bool:
    info = entry.get("information")
    return isinstance(info, dict) and not info


def find_nearby_colonisation_candidates(system_name: str, radius_ly: float = _DEFAULT_RADIUS_LY) -> Dict[str, Any]:
    """Returns {"candidates": list[dict], "center_populated": Optional[bool], "lookup_failed": bool}.
    candidates: unpopulated systems within radius_ly of system_name, closest first,
    capped at _MAX_CANDIDATES. Each result: {"name": str, "distance_ly": float}.
    center_populated: True if system_name is itself a populated system (in which case every
    candidate IS guaranteed genuinely eligible, since the center doubles as the populated
    reference point) -- False if system_name is itself unpopulated (candidates are merely
    "nearby," NOT verified eligible -- each one individually might or might not have its own
    populated neighbor within range) -- None if the lookup failed or the system wasn't found.
    lookup_failed: True if EDSM was unreachable or returned something unparseable -- distinct
    from a genuine empty candidates list."""
    data = _query_sphere(system_name, radius_ly)
    if data is None:
        return {"candidates": [], "center_populated": None, "lookup_failed": True}
    if not data:
        return {"candidates": [], "center_populated": None, "lookup_failed": False}

    center = next((e for e in data if e.get("distance") == 0), None)
    center_populated = None if center is None else not _is_unpopulated(center)

    candidates = []
    for entry in data:
        distance = entry.get("distance")
        name = entry.get("name")
        if not isinstance(name, str) or not name or not isinstance(distance, (int, float)):
            continue
        if distance <= 0:
            continue  # the queried system itself
        if not _is_unpopulated(entry):
            continue
        candidates.append({"name": name, "distance_ly": float(distance)})

    candidates.sort(key=lambda c: c["distance_ly"])
    return {
        "candidates": candidates[:_MAX_CANDIDATES],
        "center_populated": center_populated,
        "lookup_failed": False,
    }


def check_system_eligibility(system_name: str) -> Dict[str, Any]:
    """For a manually-named candidate system: is it itself unpopulated,
    and is there a populated system within 15 ly of it (the actual claim
    requirement). Returns {"eligible": Optional[bool], "reason": str,
    "nearest_populated_ly": Optional[float]} -- eligible=None means the
    lookup itself failed or the system wasn't found in EDSM, distinct from
    a real ineligibility verdict."""
    data = _query_sphere(system_name, _DEFAULT_RADIUS_LY)
    if data is None:
        return {"eligible": None, "reason": "Lookup failed -- EDSM unreachable.", "nearest_populated_ly": None}
    if not data:
        return {"eligible": None, "reason": "System not found in EDSM.", "nearest_populated_ly": None}

    target = next((e for e in data if e.get("distance") == 0), None)
    if target is None:
        return {"eligible": None, "reason": "System not found in EDSM.", "nearest_populated_ly": None}

    if not _is_unpopulated(target):
        return {"eligible": False, "reason": "This system is already populated.", "nearest_populated_ly": None}

    nearest_populated_ly = None
    for entry in data:
        distance = entry.get("distance")
        if not isinstance(distance, (int, float)) or distance <= 0:
            continue
        if _is_unpopulated(entry):
            continue
        if nearest_populated_ly is None or distance < nearest_populated_ly:
            nearest_populated_ly = float(distance)

    if nearest_populated_ly is None:
        return {
            "eligible": False,
            "reason": f"Unpopulated, but no populated system within {_DEFAULT_RADIUS_LY:.0f} ly to claim it from.",
            "nearest_populated_ly": None,
        }

    return {
        "eligible": True,
        "reason": f"Unpopulated, {nearest_populated_ly:.1f} ly from the nearest populated system.",
        "nearest_populated_ly": nearest_populated_ly,
    }
