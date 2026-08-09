"""Landing pad size determination — shared between the persistence layer
(for ranking search results) and the UI layer (for display), so both agree
on what "known" vs "unknown" means.

Two sources, in order of trust:
1. Ground truth from the player's own `Docked` journal event (LandingPads
   counts) — see edc/core/station_pads.py::extract_station_info and
   persistence station_info table.
2. A heuristic from EDDN's reported `stationType`, confirmed against
   community/wiki sources and this project's own live-captured EDDN data
   (not guessed) — see pad_size_hint().
"""
from __future__ import annotations

from typing import Any, Dict, Optional

# Confirmed against community/wiki sources + this project's own live-captured
# EDDN data — not guessed. Anything not in either set (e.g. "Bernal", or a
# blank stationType — both real values seen in practice) is unknown ("?")
# rather than asserting a pad size we're not sure of.
_LARGE_PAD_TYPES = {
    "coriolis", "orbis", "ocellus", "dodec", "surfacestation",
    "asteroidbase", "craterport", "fleetcarrier", "megaship",
}
_MEDIUM_PAD_TYPES = {"outpost", "crateroutpost"}


def pad_size_hint(station_type: Optional[str]) -> str:
    """Returns 'L', 'M', or '?' (genuinely unknown) for a station's max landing pad."""
    key = (station_type or "").strip().lower()
    if key in _LARGE_PAD_TYPES:
        return "L"
    if key in _MEDIUM_PAD_TYPES:
        return "M"
    return "?"


def confirmed_pad_size(pads_small: Any, pads_medium: Any, pads_large: Any) -> Optional[str]:
    """
    From our own Docked-event LandingPads counts (ground truth). Returns
    'L'/'M'/'S', or None if no counts are available at all.
    """
    try:
        if isinstance(pads_large, int) and pads_large > 0:
            return "L"
        if isinstance(pads_medium, int) and pads_medium > 0:
            return "M"
        if isinstance(pads_small, int) and pads_small > 0:
            return "S"
    except Exception:
        pass
    return None


def effective_pad_size(
    station_type: Optional[str],
    pads_small: Any = None,
    pads_medium: Any = None,
    pads_large: Any = None,
) -> str:
    """Ground truth first, then the stationType heuristic, then '?'."""
    confirmed = confirmed_pad_size(pads_small, pads_medium, pads_large)
    if confirmed:
        return confirmed
    return pad_size_hint(station_type)


# Ship internal name -> pad size it requires to dock. From FDev's own
# internal ship identifiers (as seen in the Loadout event's "Ship" field —
# krait_mkii, diamondbackxl, cutter, and python confirmed directly against
# this project's own journal data; the rest are well-established community
# knowledge, not individually re-verified here). Ships not yet confirmed
# (e.g. very recently released ones) are deliberately left out rather than
# guessed — ship_pad_size() returns None for anything not in this table,
# and callers should treat that as "unknown," not "small."
SHIP_PAD_SIZE: Dict[str, str] = {
    # Small
    "sidewinder": "S", "eagle": "S", "empire_eagle": "S", "hauler": "S",
    "adder": "S", "viper": "S", "viper_mkiv": "S", "cobramkiii": "S",
    "cobramkiv": "S", "diamondback": "S", "diamondbackxl": "S",
    "empire_courier": "S",
    # Medium
    "vulture": "M", "asp": "M", "asp_scout": "M",
    "federation_dropship": "M", "federation_dropship_mkii": "M",
    "federation_gunship": "M", "independant_trader": "M", "type6": "M",
    "typex": "M", "typex_2": "M", "typex_3": "M", "krait_light": "M",
    "krait_mkii": "M", "mamba": "M", "python": "M", "python_nx": "M",
    "ferdelance": "M", "dolphin": "M",
    # Large
    "type7": "L", "type9": "L", "type9_military": "L", "type10": "L",
    "anaconda": "L", "federation_corvette": "L", "cutter": "L",
    "empire_trader": "L", "imperial_clipper": "L", "orca": "L",
    "belugaliner": "L",
}


def ship_pad_size(ship_internal_name: Optional[str]) -> Optional[str]:
    """'S'/'M'/'L' for a known ship, or None if not in SHIP_PAD_SIZE —
    callers must treat None as genuinely unknown, not as any particular
    size."""
    return SHIP_PAD_SIZE.get((ship_internal_name or "").strip().lower())


def has_interstellar_factors(station_services: Any) -> bool:
    """StationServices (array of strings) includes "Facilitator" for
    stations offering Interstellar Factors (bounty/fine clearance)."""
    if not isinstance(station_services, list):
        return False
    return any(isinstance(s, str) and s.strip().lower() == "facilitator" for s in station_services)


def extract_station_info(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Pulls MarketID/StationName/StarSystem/StationType/LandingPads/
    StationServices/StationFaction out of a raw "Docked" journal event.
    Returns None if it lacks a usable MarketID. Shared by the live event
    path and the historical journal importer so both populate the same
    station_info table the same way.
    """
    market_id = event.get("MarketID")
    if not isinstance(market_id, int):
        return None

    pads = event.get("LandingPads")
    pads_small = pads_medium = pads_large = None
    if isinstance(pads, dict):
        pads_small = pads.get("Small")
        pads_medium = pads.get("Medium")
        pads_large = pads.get("Large")

    station_faction = event.get("StationFaction")
    faction_name = station_faction.get("Name") if isinstance(station_faction, dict) else None

    services = event.get("StationServices")
    services = services if isinstance(services, list) else None

    return {
        "market_id": market_id,
        "station_name": event.get("StationName"),
        "system_name": event.get("StarSystem"),
        "station_type": event.get("StationType"),
        "pads_small": pads_small if isinstance(pads_small, int) else None,
        "pads_medium": pads_medium if isinstance(pads_medium, int) else None,
        "pads_large": pads_large if isinstance(pads_large, int) else None,
        "station_faction": faction_name,
        "station_services": services,
        "timestamp": event.get("timestamp"),
    }
