"""On-demand EDSM system-factions lookup — used when manually adding a
system to the Player Faction tab, to get real current faction data
immediately instead of waiting on EDDN network traffic (EDDN only reports
sightings as they happen live; there's no way to ask it about a specific
system directly).

Same EDSM data source as edsm_powerplay.py, same reason cloudscraper is
needed (Cloudflare's generic bot challenge in front of data EDSM already
publishes for third-party tools). This is a targeted per-system query
(fast, small response) rather than the ~20MB PowerPlay dump, so it's fine
to call synchronously from a worker thread per user action rather than
caching to disk.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

import cloudscraper

log = logging.getLogger(__name__)

_FACTIONS_URL = "https://www.edsm.net/api-system-v1/factions"
_SYSTEM_URL = "https://www.edsm.net/api-v1/system"
_STATIONS_URL = "https://www.edsm.net/api-system-v1/stations"
_TIMEOUT = 20

# Confirmed via live testing (a 743-system bulk import): EDSM's Cloudflare
# challenge blocks roughly 60% of requests seemingly at random — not a
# sustained "you've been cut off" wall, since successes and failures were
# interleaved from the very first request rather than clustered. A retry
# with backoff recovers a meaningful share of these on the same call.
_RETRY_DELAYS_S = (1.0, 3.0, 6.0)

# Second element of the return tuple when the first is None — lets the UI
# distinguish "genuinely not in EDSM's database" from "the request itself
# failed" (blocked/timed out/network error), which is not a spelling issue
# and was previously shown with the same misleading message.
ERROR_BLOCKED = "blocked"
ERROR_NOT_FOUND = "not_found"


def fetch_system_factions(system_name: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Synchronous — call from a worker thread only, never the UI thread.
    Retries on a blocked/failed request (not on a genuine "not found") with
    increasing backoff before giving up.

    Returns ({"system_address": int, "system_name": str, "factions": [...]}, None)
    on success, or (None, ERROR_BLOCKED | ERROR_NOT_FOUND) on failure.
    Each entry in "factions" is normalized to the same shape as a raw
    journal Factions[] entry (Name/Influence/FactionState/ActiveStates/
    PendingStates/...) plus an "is_controlling" bool, so it can be passed
    straight into Repository.save_faction_snapshot.
    """
    attempt = 0
    while True:
        result, error = _fetch_once(system_name)
        if result is not None or error != ERROR_BLOCKED or attempt >= len(_RETRY_DELAYS_S):
            return result, error
        time.sleep(_RETRY_DELAYS_S[attempt])
        attempt += 1


def fetch_system_stations(system_name: str) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """
    Full static station/settlement list for a system, with controlling
    faction per station — from EDSM's own galaxy catalog, not from live
    Docked-event sightings. This is the fix for our station_info table
    only ever knowing about stations someone has actually docked at
    recently: confirmed live that a system can have 7 stations controlled
    by one faction while our own EDDN-sourced data only knew about 1.

    Same retry/error shape as fetch_system_factions. Each entry is
    {"market_id": int|None, "station_name": str, "station_type": str,
    "controlling_faction": str|None} — Fleet Carriers and stations with no
    recorded controlling faction are dropped, since neither is useful here.
    """
    attempt = 0
    while True:
        result, error = _fetch_stations_once(system_name)
        if result is not None or error != ERROR_BLOCKED or attempt >= len(_RETRY_DELAYS_S):
            return result, error
        time.sleep(_RETRY_DELAYS_S[attempt])
        attempt += 1


def _fetch_stations_once(system_name: str) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    try:
        scraper = cloudscraper.create_scraper()
        resp = scraper.get(_STATIONS_URL, params={"systemName": system_name}, timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.error("EDSM system-stations lookup failed for %r: %s", system_name, exc)
        return None, ERROR_BLOCKED

    if not isinstance(data, dict):
        return None, ERROR_BLOCKED

    raw_stations = data.get("stations")
    if not isinstance(raw_stations, list):
        log.warning("EDSM stations response for %r missing expected fields — raw body: %r", system_name, data)
        return None, ERROR_NOT_FOUND

    stations: List[Dict[str, Any]] = []
    for st in raw_stations:
        if not isinstance(st, dict):
            continue
        if st.get("type") == "Fleet Carrier":
            continue
        name = st.get("name")
        if not isinstance(name, str) or not name:
            continue
        controlling = st.get("controllingFaction")
        controlling_name = controlling.get("name") if isinstance(controlling, dict) else None
        if not controlling_name:
            continue
        stations.append({
            "market_id": st.get("marketId"),
            "station_name": name,
            "station_type": st.get("type") or "",
            "controlling_faction": controlling_name,
        })

    return stations, None


def fetch_system_coords(system_name: str) -> Optional[Tuple[float, float, float]]:
    """
    EDSM's faction endpoint has no coordinate data (confirmed via live
    testing) — this is EDSM's separate system endpoint, used to backfill
    system_coords for tracked systems EDDN has never happened to see live
    (needed for Player Faction distance sorting). One-shot, no retry —
    coords are a nice-to-have here, not worth doubling request volume for.
    """
    try:
        scraper = cloudscraper.create_scraper()
        resp = scraper.get(
            _SYSTEM_URL, params={"systemName": system_name, "showCoordinates": 1}, timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.error("EDSM system-coords lookup failed for %r: %s", system_name, exc)
        return None
    coords = data.get("coords") if isinstance(data, dict) else None
    if not isinstance(coords, dict):
        return None
    x, y, z = coords.get("x"), coords.get("y"), coords.get("z")
    if all(isinstance(v, (int, float)) for v in (x, y, z)):
        return (x, y, z)
    return None


def _fetch_once(system_name: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    try:
        scraper = cloudscraper.create_scraper()
        resp = scraper.get(
            _FACTIONS_URL, params={"systemName": system_name, "showHistory": 0}, timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.error("EDSM system-factions lookup failed for %r: %s", system_name, exc)
        return None, ERROR_BLOCKED

    if not isinstance(data, dict):
        return None, ERROR_BLOCKED

    system_address = data.get("id64")
    resolved_name = data.get("name")
    raw_factions = data.get("factions")
    if not (isinstance(system_address, int) and isinstance(resolved_name, str) and isinstance(raw_factions, list)):
        # A valid (non-blocked) response for an unknown system is an empty
        # dict/object from EDSM, not an HTTP error — that's the genuine
        # "not in EDSM's database" case. Logging the raw body here too,
        # since an unexpected-but-non-empty shape would otherwise look
        # identical to a real "not found" with no way to tell them apart.
        log.warning("EDSM response for %r missing expected fields — raw body: %r", system_name, data)
        return None, ERROR_NOT_FOUND

    controlling = data.get("controllingFaction")
    controlling_name = controlling.get("name") if isinstance(controlling, dict) else None

    factions: List[Dict[str, Any]] = []
    for f in raw_factions:
        if not isinstance(f, dict):
            continue
        name = f.get("name")
        if not isinstance(name, str) or not name:
            continue
        factions.append({
            "Name": name,
            "Influence": f.get("influence"),
            "Government": f.get("government"),
            "Allegiance": f.get("allegiance"),
            "FactionState": f.get("state"),
            "Happiness_Localised": f.get("happiness"),
            "ActiveStates": _states_to_journal_shape(f.get("activeStates")),
            "PendingStates": _states_to_journal_shape(f.get("pendingStates")),
            "RecoveringStates": _states_to_journal_shape(f.get("recoveringStates")),
            "is_controlling": bool(controlling_name and name == controlling_name),
        })

    return {"system_address": system_address, "system_name": resolved_name, "factions": factions}, None


def _states_to_journal_shape(states: Any) -> List[Dict[str, str]]:
    if not isinstance(states, list):
        return []
    out = []
    for s in states:
        if isinstance(s, dict) and s.get("state"):
            out.append({"State": s["state"]})
    return out
