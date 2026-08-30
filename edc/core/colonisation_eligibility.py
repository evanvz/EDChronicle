"""Colonisation eligibility lookups via EDSM's sphere-systems endpoint --
answers "which nearby systems are unpopulated and thus colonisable" and
"is this specific system eligible right now". Advisory only: EDSM's
population data is crowdsourced and can lag real-time changes.

Real game rule (verified, not guessed): a system is colonisable only if
genuinely unpopulated and within 15 ly of an existing populated system,
claimed via a System Colonisation Contact at any starport. A second
mechanic lets you chain-expand 10 ly from your own already-completed
colony -- supported here by passing own_colony_names.

EDSM's sphere-systems response always includes the queried center system
itself at "distance": 0. A populated system's "information" is a full
object; a genuinely unpopulated system's "information" is an empty object
{} -- confirmed live against real EDSM data during development (e.g. a
system 98.53 ly from Sol returned "information":{}).

Spansh cross-check: EDSM's crowdsourced population data can lag a system
someone just claimed. Spansh's own system-search API exposes
is_colonised/is_being_colonised directly, so each EDSM-sourced candidate
is cross-checked against Spansh (fail-open: a Spansh miss or error never
excludes a candidate EDSM already confirmed unpopulated).
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
_CHAIN_RADIUS_LY = 10.0

_SPANSH_SEARCH_URL = "https://spansh.co.uk/api/systems/search"


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


def _spansh_claimed(system_name: str) -> Optional[bool]:
    """True if Spansh reports this system as colonised or under
    colonisation, False if Spansh confirms it's clear, None if Spansh has
    no data or the lookup failed (fail-open -- caller should keep the
    candidate)."""
    try:
        resp = requests.post(
            _SPANSH_SEARCH_URL,
            json={"filters": {"name": {"value": system_name}}, "size": 1, "page": 0},
            headers={"User-Agent": _USER_AGENT},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        results = resp.json().get("results") or []
    except Exception:
        log.warning("Spansh colonisation cross-check failed for %r", system_name, exc_info=True)
        return None
    if not results:
        return None
    sys_data = results[0]
    return bool(sys_data.get("is_colonised")) or bool(sys_data.get("is_being_colonised"))


def _spansh_filter(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    kept = []
    for c in candidates:
        if _spansh_claimed(c["name"]):
            continue  # Spansh says already claimed -- EDSM hasn't caught up yet
        kept.append(c)
    return kept


def find_nearby_colonisation_candidates(
    system_name: str,
    radius_ly: float = _DEFAULT_RADIUS_LY,
    own_colony_names: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Returns {"candidates": list[dict], "center_populated": Optional[bool], "lookup_failed": bool}.
    candidates: unpopulated systems within radius_ly of system_name (closest first) plus, for
    each name in own_colony_names, unpopulated systems within _CHAIN_RADIUS_LY of that completed
    colony (the real 10 ly chained-expansion rule) -- merged, deduped by name (keeping the
    shortest distance), capped at _MAX_CANDIDATES, then cross-checked against Spansh (see module
    docstring). Each result: {"name": str, "distance_ly": float, "via": Optional[str]} -- via is
    None for a candidate found near system_name, or the anchoring colony's name for a chained one.
    center_populated: True if system_name is itself a populated system (in which case every
    candidate found near it IS guaranteed genuinely eligible, since the center doubles as the
    populated reference point) -- False if system_name is itself unpopulated (those candidates are
    merely "nearby," NOT verified eligible -- each one individually might or might not have its own
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

    by_name: Dict[str, Dict[str, Any]] = {}

    def _add(entries: List[Dict[str, Any]], via: Optional[str]) -> None:
        for entry in entries:
            distance = entry.get("distance")
            name = entry.get("name")
            if not isinstance(name, str) or not name or not isinstance(distance, (int, float)):
                continue
            if distance <= 0:
                continue  # the queried system itself
            if not _is_unpopulated(entry):
                continue
            key = name.lower()
            if key not in by_name or distance < by_name[key]["distance_ly"]:
                by_name[key] = {"name": name, "distance_ly": float(distance), "via": via}

    _add(data, None)
    for colony_name in own_colony_names or []:
        colony_data = _query_sphere(colony_name, _CHAIN_RADIUS_LY)
        if colony_data:
            _add(colony_data, colony_name)

    candidates = sorted(by_name.values(), key=lambda c: c["distance_ly"])[:_MAX_CANDIDATES]
    candidates = _spansh_filter(candidates)
    return {
        "candidates": candidates,
        "center_populated": center_populated,
        "lookup_failed": False,
    }


def check_system_eligibility(system_name: str, own_colony_names: Optional[List[str]] = None) -> Dict[str, Any]:
    """For a manually-named candidate system: is it itself unpopulated,
    and is there a populated system within 15 ly of it, OR is it within
    10 ly of one of own_colony_names (the chained-expansion rule) -- either
    satisfies the actual claim requirement. Returns {"eligible": Optional[bool],
    "reason": str, "nearest_populated_ly": Optional[float]} -- eligible=None
    means the lookup itself failed or the system wasn't found in EDSM,
    distinct from a real ineligibility verdict."""
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

    if _spansh_claimed(system_name):
        return {
            "eligible": False,
            "reason": "Spansh reports this system as already colonised or under colonisation.",
            "nearest_populated_ly": None,
        }

    nearest_populated_ly = None
    for entry in data:
        distance = entry.get("distance")
        if not isinstance(distance, (int, float)) or distance <= 0:
            continue
        if _is_unpopulated(entry):
            continue
        if nearest_populated_ly is None or distance < nearest_populated_ly:
            nearest_populated_ly = float(distance)

    if nearest_populated_ly is not None:
        return {
            "eligible": True,
            "reason": f"Unpopulated, {nearest_populated_ly:.1f} ly from the nearest populated system.",
            "nearest_populated_ly": nearest_populated_ly,
        }

    for colony_name in own_colony_names or []:
        colony_distance = _distance_between(colony_name, system_name)
        if colony_distance is not None and colony_distance <= _CHAIN_RADIUS_LY:
            return {
                "eligible": True,
                "reason": f"Unpopulated, {colony_distance:.1f} ly from your completed colony at {colony_name}.",
                "nearest_populated_ly": None,
            }

    return {
        "eligible": False,
        "reason": (
            f"Unpopulated, but no populated system within {_DEFAULT_RADIUS_LY:.0f} ly "
            f"or completed colony within {_CHAIN_RADIUS_LY:.0f} ly to claim it from."
        ),
        "nearest_populated_ly": None,
    }


def _distance_between(colony_name: str, system_name: str) -> Optional[float]:
    colony_data = _query_sphere(colony_name, _CHAIN_RADIUS_LY)
    if not colony_data:
        return None
    for entry in colony_data:
        if isinstance(entry.get("name"), str) and entry["name"].lower() == system_name.lower():
            distance = entry.get("distance")
            return float(distance) if isinstance(distance, (int, float)) else None
    return None
