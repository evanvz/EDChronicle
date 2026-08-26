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

    # Economies arrive as [{"Name": ..., "Proportion": ...}, ...] — stored as
    # a compact "Name:proportion|Name:proportion" string for display/filter
    # without a join table.
    economies = None
    econ_list = event.get("StationEconomies")
    if isinstance(econ_list, list) and econ_list:
        parts = []
        for e in econ_list:
            if isinstance(e, dict) and e.get("Name"):
                try:
                    parts.append(f"{e['Name']}:{float(e.get('Proportion', 0))}")
                except (TypeError, ValueError):
                    parts.append(str(e["Name"]))
        if parts:
            economies = "|".join(parts)

    dist = event.get("DistFromStarLS")
    dist_from_star_ls = float(dist) if isinstance(dist, (int, float)) else None

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
        "economies": economies,
        "dist_from_star_ls": dist_from_star_ls,
        "station_government": event.get("StationGovernment"),
        "station_allegiance": event.get("StationAllegiance"),
        "timestamp": event.get("timestamp"),
    }
